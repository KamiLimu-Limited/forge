"""Attendance submission, windows and override workflow."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, and_, exists, func, insert, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.config import settings
from forge.core.exceptions import (
    BusinessRuleViolation,
    Conflict,
    NotFound,
    PermissionDenied,
)
from forge.models import (
    AttendanceRecord,
    AttendanceStatus,
    AttendanceWindow,
    AttendanceWindowOverride,
    CohortEnrollment,
    NotificationType,
    OverrideRequest,
    OverrideRequestStatus,
    ProgrammeSession,
    User,
    UserRole,
    UserRoleAssignment,
)
from forge.schemas.attendance import (
    AttendanceFilters,
    AttendanceStatusUpdateRequest,
    AttendanceSubmissionRequest,
    AttendanceUpdateRequest,
    OverrideFilters,
    OverrideRequestCreate,
    OverrideReviewRequest,
    WindowStatusResponse,
)
from forge.services.access import (
    ensure_cohort_staff,
    get_enrollment,
    group_mentee_ids,
    is_cohort_staff,
)
from forge.services.audit import log_action
from forge.services.eligibility import (
    COUNTED_STATUSES,
    applies_to_enrollment,
    session_applies,
)
from forge.services.notifications import notify
from forge.services.pagination import paginate
from forge.services.sessions import get_session_or_404
from forge.services.windows import (
    effective_closes_at,
    get_window,
    is_open,
    override_for,
)

SUBMITTABLE = (AttendanceStatus.PENDING, AttendanceStatus.MISSED)


def _now() -> datetime:
    return datetime.now(UTC)


async def _eligible_session(
    db: AsyncSession, mentee: User, session_id: uuid.UUID
) -> ProgrammeSession:
    session = await get_session_or_404(db, session_id)
    enrollment = await get_enrollment(db, mentee.id, session.cohort_id)
    if enrollment is None or not session_applies(session, enrollment):
        raise PermissionDenied("This session does not apply to you")
    if session.status not in COUNTED_STATUSES:
        raise BusinessRuleViolation(
            f"Attendance cannot be recorded for a {session.status.value} session"
        )
    return session


async def _open_window_or_raise(
    db: AsyncSession, session_id: uuid.UUID, mentee_id: uuid.UUID
) -> AttendanceWindow:
    window = await get_window(db, session_id)
    if window is None or not is_open(window, mentee_id):
        raise BusinessRuleViolation(
            "The attendance window for this session is not open"
        )
    return window


def _apply(
    record: AttendanceRecord,
    data: AttendanceSubmissionRequest | AttendanceUpdateRequest,
) -> None:
    # A submission replaces every field; an update only touches the fields sent.
    partial = isinstance(data, AttendanceUpdateRequest)
    for key, value in data.model_dump(
        exclude_unset=partial, exclude={"session_id"}
    ).items():
        setattr(record, key, value)
    if record.status is AttendanceStatus.NOT_ATTENDED:
        for field in (
            "quality_rating",
            "usefulness_rating",
            "understanding_score",
            "academic_application_score",
            "career_application_score",
        ):
            setattr(record, field, None)
    record.submitted_at = _now()


async def submit_attendance(
    db: AsyncSession, mentee: User, data: AttendanceSubmissionRequest
) -> AttendanceRecord:
    session = await _eligible_session(db, mentee, data.session_id)
    await _open_window_or_raise(db, session.id, mentee.id)

    record = await db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.mentee_id == mentee.id,
            AttendanceRecord.session_id == session.id,
        )
    )
    if record is not None and record.status not in SUBMITTABLE:
        raise Conflict(
            "Attendance already submitted for this session; update it instead"
        )
    if record is None:
        record = AttendanceRecord(mentee_id=mentee.id, session_id=session.id)
        db.add(record)
    _apply(record, data)
    await db.flush()
    log_action(
        db,
        "submit_attendance",
        user_id=mentee.id,
        resource_type="attendance_record",
        resource_id=record.id,
    )
    await db.commit()
    await db.refresh(record)
    return record


async def get_record_or_404(db: AsyncSession, record_id: uuid.UUID) -> AttendanceRecord:
    record = await db.get(AttendanceRecord, record_id)
    if record is None:
        raise NotFound("Attendance record not found")
    return record


async def get_visible_record(
    db: AsyncSession, user: User, record_id: uuid.UUID
) -> AttendanceRecord:
    record = await get_record_or_404(db, record_id)
    if record.mentee_id == user.id or is_cohort_staff(user, record.session.cohort_id):
        return record
    if record.mentee_id in await group_mentee_ids(
        db, user.id, record.session.cohort_id
    ):
        return record
    raise NotFound("Attendance record not found")


async def update_attendance(
    db: AsyncSession,
    mentee: User,
    record: AttendanceRecord,
    data: AttendanceUpdateRequest,
) -> AttendanceRecord:
    if record.mentee_id != mentee.id:
        raise PermissionDenied("You can only update your own attendance")
    if record.status not in (
        *SUBMITTABLE,
        AttendanceStatus.ATTENDED,
        AttendanceStatus.NOT_ATTENDED,
    ):
        raise BusinessRuleViolation(
            f"A record marked {record.status.value} can only be changed by the committee"
        )
    await _open_window_or_raise(db, record.session_id, mentee.id)
    if data.status is None and record.status in SUBMITTABLE:
        data = data.model_copy(update={"status": AttendanceStatus.ATTENDED})
    if (
        data.status or record.status
    ) is AttendanceStatus.NOT_ATTENDED and data.has_ratings():
        raise BusinessRuleViolation(
            "Ratings can only be given for sessions you attended"
        )
    _apply(record, data)
    log_action(
        db,
        "update_attendance",
        user_id=mentee.id,
        resource_type="attendance_record",
        resource_id=record.id,
    )
    await db.commit()
    await db.refresh(record)
    return record


async def set_record_status(
    db: AsyncSession,
    staff: User,
    record: AttendanceRecord,
    data: AttendanceStatusUpdateRequest,
) -> AttendanceRecord:
    ensure_cohort_staff(staff, record.session.cohort_id)
    old = record.status
    record.status = data.status
    log_action(
        db,
        "set_attendance_status",
        user_id=staff.id,
        resource_type="attendance_record",
        resource_id=record.id,
        old_status=old.value,
        new_status=data.status.value,
        reason=data.reason,
    )
    await db.commit()
    await db.refresh(record)
    return record


def _filtered(
    stmt: Select[AttendanceRecord], filters: AttendanceFilters
) -> Select[AttendanceRecord]:
    stmt = stmt.join(
        ProgrammeSession, ProgrammeSession.id == AttendanceRecord.session_id
    )
    if filters.cohort_id:
        stmt = stmt.where(ProgrammeSession.cohort_id == filters.cohort_id)
    if filters.session_id:
        stmt = stmt.where(AttendanceRecord.session_id == filters.session_id)
    if filters.mentee_id:
        stmt = stmt.where(AttendanceRecord.mentee_id == filters.mentee_id)
    if filters.status:
        stmt = stmt.where(AttendanceRecord.status == filters.status)
    if filters.kami_limu_month:
        stmt = stmt.where(ProgrammeSession.kami_limu_month == filters.kami_limu_month)
    if filters.track:
        stmt = stmt.where(ProgrammeSession.track == filters.track)
    return stmt.order_by(ProgrammeSession.starts_at.desc())


async def list_records(
    db: AsyncSession,
    filters: AttendanceFilters,
    mentee_ids: list[uuid.UUID] | None = None,
) -> tuple[list[AttendanceRecord], int]:
    stmt = select(AttendanceRecord)
    if mentee_ids is not None:
        stmt = stmt.where(AttendanceRecord.mentee_id.in_(mentee_ids))
    return await paginate(db, _filtered(stmt, filters), filters)


async def window_status(
    db: AsyncSession, user: User, session: ProgrammeSession
) -> WindowStatusResponse:
    window = await get_window(db, session.id)
    if window is None:
        raise NotFound("This session has no attendance window yet")
    record = await db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.mentee_id == user.id,
            AttendanceRecord.session_id == session.id,
        )
    )
    return WindowStatusResponse(
        session_id=session.id,
        window_id=window.id,
        opens_at=window.opens_at,
        closes_at=window.closes_at,
        effective_closes_at=effective_closes_at(window, user.id),
        is_active=window.is_active,
        is_open=is_open(window, user.id),
        has_override=override_for(window, user.id) is not None,
        record_id=record.id if record else None,
        record_status=record.status if record else None,
    )


async def close_window(
    db: AsyncSession, admin: User, window_id: uuid.UUID
) -> AttendanceWindow:
    window = await db.get(AttendanceWindow, window_id)
    if window is None:
        raise NotFound("Attendance window not found")
    if window.is_active:
        window.is_active = False
        window.closed_at = _now()
        log_action(
            db,
            "close_attendance_window",
            user_id=admin.id,
            resource_type="attendance_window",
            resource_id=window.id,
        )
        await db.commit()
    return window


async def close_expired_windows(db: AsyncSession) -> int:
    """Deactivate expired windows and record ``missed`` for eligible mentees who never submitted.

    Mentees holding an override that is still open are skipped until it expires.
    """
    now = _now()
    expired = await db.scalars(
        select(AttendanceWindow).where(
            AttendanceWindow.is_active.is_(True), AttendanceWindow.closes_at <= now
        )
    )
    for window in expired:
        window.is_active = False
        window.closed_at = window.closes_at
    await db.flush()

    window_closed = or_(
        AttendanceWindow.closes_at <= now,
        and_(AttendanceWindow.is_active.is_(False), AttendanceWindow.closed_at <= now),
    )
    has_record = exists().where(
        AttendanceRecord.mentee_id == CohortEnrollment.user_id,
        AttendanceRecord.session_id == ProgrammeSession.id,
    )
    has_open_override = exists().where(
        AttendanceWindowOverride.attendance_window_id == AttendanceWindow.id,
        AttendanceWindowOverride.mentee_id == CohortEnrollment.user_id,
        AttendanceWindowOverride.new_closes_at > now,
    )
    missing = (
        select(
            func.gen_random_uuid(),
            CohortEnrollment.user_id,
            ProgrammeSession.id,
            literal(
                AttendanceStatus.MISSED, type_=AttendanceRecord.__table__.c.status.type
            ),
        )
        .select_from(ProgrammeSession)
        .join(CohortEnrollment, applies_to_enrollment())
        .join(AttendanceWindow, AttendanceWindow.session_id == ProgrammeSession.id)
        .where(
            ProgrammeSession.status.in_(COUNTED_STATUSES),
            window_closed,
            ~has_record,
            ~has_open_override,
        )
    )
    result = await db.execute(
        insert(AttendanceRecord).from_select(
            ["id", "mentee_id", "session_id", "status"], missing
        )
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def create_override_request(
    db: AsyncSession, mentee: User, data: OverrideRequestCreate
) -> OverrideRequest:
    session = await _eligible_session(db, mentee, data.session_id)
    window = await get_window(db, session.id)
    if window is not None and is_open(window, mentee.id):
        raise BusinessRuleViolation(
            "The attendance window is still open; submit attendance instead"
        )
    pending = await db.scalar(
        select(OverrideRequest.id).where(
            OverrideRequest.mentee_id == mentee.id,
            OverrideRequest.session_id == session.id,
            OverrideRequest.status == OverrideRequestStatus.PENDING,
        )
    )
    if pending is not None:
        raise Conflict("You already have a pending override request for this session")

    request = OverrideRequest(
        mentee_id=mentee.id, session_id=session.id, reason=data.reason
    )
    db.add(request)
    await db.flush()
    committee = await db.scalars(
        select(UserRoleAssignment.user_id).where(
            UserRoleAssignment.role == UserRole.COMMITTEE,
            UserRoleAssignment.cohort_id == session.cohort_id,
        )
    )
    notify(
        db,
        committee,
        NotificationType.OVERRIDE_SUBMITTED,
        {
            "mentee": mentee.full_name,
            "title": session.title,
            "starts_at": session.starts_at,
            "ends_at": session.ends_at,
            "submitted_at": _now(),
            "reason": data.reason,
        },
        resource_type="override_request",
        resource_id=request.id,
    )
    log_action(
        db,
        "create_override_request",
        user_id=mentee.id,
        resource_type="override_request",
        resource_id=request.id,
    )
    await db.commit()
    await db.refresh(request)
    return request


async def list_override_requests(
    db: AsyncSession, user: User, filters: OverrideFilters
) -> tuple[list[OverrideRequest], int]:
    stmt = (
        select(OverrideRequest)
        .join(ProgrammeSession, ProgrammeSession.id == OverrideRequest.session_id)
        .order_by(OverrideRequest.created_at.desc())
    )
    if not user.is_admin:
        committee_scopes = {
            r.cohort_id for r in user.roles if r.role is UserRole.COMMITTEE
        }
        if None not in committee_scopes:  # a global committee role sees every cohort
            stmt = stmt.where(
                or_(
                    OverrideRequest.mentee_id == user.id,
                    ProgrammeSession.cohort_id.in_(committee_scopes),
                )
            )
    if filters.status:
        stmt = stmt.where(OverrideRequest.status == filters.status)
    if filters.cohort_id:
        stmt = stmt.where(ProgrammeSession.cohort_id == filters.cohort_id)
    if filters.session_id:
        stmt = stmt.where(OverrideRequest.session_id == filters.session_id)
    return await paginate(db, stmt, filters)


async def get_override_request_or_404(
    db: AsyncSession, request_id: uuid.UUID
) -> OverrideRequest:
    request = await db.get(OverrideRequest, request_id)
    if request is None:
        raise NotFound("Override request not found")
    return request


async def review_override_request(
    db: AsyncSession,
    reviewer: User,
    request: OverrideRequest,
    data: OverrideReviewRequest,
    approve: bool,
) -> OverrideRequest:
    ensure_cohort_staff(reviewer, request.session.cohort_id)
    if request.status is not OverrideRequestStatus.PENDING:
        raise BusinessRuleViolation(f"Request has already been {request.status.value}")

    request.status = (
        OverrideRequestStatus.APPROVED if approve else OverrideRequestStatus.DENIED
    )
    request.reviewed_by = reviewer.id
    request.reviewed_at = _now()
    request.review_reason = data.reason
    context: dict[str, object] = {
        "title": request.session.title,
        "starts_at": request.session.starts_at,
        "ends_at": request.session.ends_at,
        "reason": data.reason or "",
    }

    if approve:
        window = await get_window(db, request.session_id)
        if window is None:
            raise BusinessRuleViolation("Session has no attendance window")
        new_closes_at = data.new_closes_at or _now() + timedelta(
            hours=settings.OVERRIDE_EXTENSION_HOURS
        )
        if new_closes_at <= _now():
            raise BusinessRuleViolation("new_closes_at must be in the future")
        if (override := override_for(window, request.mentee_id)) is not None:
            override.new_closes_at = new_closes_at
            override.reason, override.granted_by = data.reason, reviewer.id
        else:
            window.overrides.append(
                AttendanceWindowOverride(
                    mentee_id=request.mentee_id,
                    new_closes_at=new_closes_at,
                    reason=data.reason,
                    granted_by=reviewer.id,
                )
            )
        context["closes_at"] = new_closes_at

    notify(
        db,
        [request.mentee_id],
        NotificationType.OVERRIDE_APPROVED
        if approve
        else NotificationType.OVERRIDE_DENIED,
        context,
        resource_type="override_request",
        resource_id=request.id,
    )
    log_action(
        db,
        "approve_override_request" if approve else "deny_override_request",
        user_id=reviewer.id,
        resource_type="override_request",
        resource_id=request.id,
    )
    await db.commit()
    await db.refresh(request)
    return request
