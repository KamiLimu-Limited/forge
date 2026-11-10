"""Programme session scheduling."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.config import settings
from forge.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from forge.models import (
    PEER_MENTOR_ROLES,
    AttendanceRecord,
    AttendanceWindow,
    Cohort,
    CohortEnrollment,
    NotificationType,
    ProgrammeSession,
    SessionMentor,
    SessionNote,
    SessionResource,
    SessionStatus,
    User,
    UserRoleAssignment,
)
from forge.schemas.session import (
    CalendarMonth,
    InProgressSession,
    MentorAssignment,
    ResourceIn,
    SessionCreateRequest,
    SessionFilters,
    SessionRescheduleRequest,
    SessionResponse,
    SessionUpdateRequest,
    check_times,
)
from forge.services.access import (
    can_manage_session,
    ensure_can_manage_session,
    ensure_cohort_writable,
    get_cohort_or_404,
    get_participant_enrollment,
    is_cohort_staff,
)
from forge.services.audit import log_action
from forge.services.cohorts import month_for
from forge.services.eligibility import (
    COUNTED_STATUSES,
    applies_to_enrollment,
    eligible_mentee_ids,
)
from forge.services.notifications import cohort_member_ids, notify
from forge.services.pagination import paginate
from forge.services.windows import effective_closes_at, get_window, sync_window

# Sessions whose attendance window has been opened.
SCHEDULED_STATUSES = (
    SessionStatus.PUBLISHED,
    SessionStatus.LIVE,
    SessionStatus.RESCHEDULED,
)


async def get_session_or_404(
    db: AsyncSession, session_id: uuid.UUID
) -> ProgrammeSession:
    session = await db.get(ProgrammeSession, session_id)
    if session is None:
        raise NotFound("Session not found")
    return session


def is_session_mentor(user: User, session: ProgrammeSession) -> bool:
    return any(m.user_id == user.id for m in session.mentors)


async def accessible_cohort_ids(db: AsyncSession, user: User) -> list[uuid.UUID]:
    enrolled = select(CohortEnrollment.cohort_id).where(
        CohortEnrollment.user_id == user.id
    )
    scoped = select(UserRoleAssignment.cohort_id).where(
        UserRoleAssignment.user_id == user.id, UserRoleAssignment.cohort_id.is_not(None)
    )
    return list(await db.scalars(enrolled.union(scoped)))


async def get_visible_session(
    db: AsyncSession, user: User, session_id: uuid.UUID
) -> ProgrammeSession:
    session = await get_session_or_404(db, session_id)
    staff = is_cohort_staff(user, session.cohort_id)
    if staff or is_session_mentor(user, session):
        return session
    if (
        session.status is SessionStatus.DRAFT
        or session.cohort_id not in await accessible_cohort_ids(db, user)
    ):
        raise NotFound("Session not found")
    return session


async def _managed_cohort(
    db: AsyncSession, actor: User, session: ProgrammeSession
) -> Cohort:
    ensure_can_manage_session(actor, session.cohort_id, session.category)
    cohort = await get_cohort_or_404(db, session.cohort_id)
    ensure_cohort_writable(cohort)
    return cohort


async def _validate(
    db: AsyncSession, cohort: Cohort, track: str | None, mentors: list[MentorAssignment]
) -> None:
    if track and track not in cohort.ict_track_names:
        raise BusinessRuleViolation(f"Track '{track}' is not offered in this cohort")
    for mentor in mentors:
        if await db.get(User, mentor.user_id) is None:
            raise NotFound(f"Mentor {mentor.user_id} not found")


def _mentors(assignments: list[MentorAssignment]) -> list[SessionMentor]:
    unique = {m.user_id: m for m in assignments}
    return [
        SessionMentor(user_id=m.user_id, mentor_role=m.mentor_role)
        for m in unique.values()
    ]


def _resources(resources: list[ResourceIn]) -> list[SessionResource]:
    return [
        SessionResource(
            resource_type=r.resource_type, url=str(r.url), description=r.description
        )
        for r in resources
    ]


async def _announce(
    db: AsyncSession,
    session: ProgrammeSession,
    kind: NotificationType,
    reason: str | None = None,
    previous: tuple[datetime, datetime] | None = None,
) -> None:
    recipients = await eligible_mentee_ids(db, session)
    recipients += [m.user_id for m in session.mentors]
    recipients += await cohort_member_ids(db, session.cohort_id, PEER_MENTOR_ROLES)
    notify(
        db,
        recipients,
        kind,
        {
            "title": session.title,
            "starts_at": session.starts_at,
            "ends_at": session.ends_at,
            "location": session.location or "",
            "reason": reason or "",
            **(
                {"previous_starts_at": previous[0], "previous_ends_at": previous[1]}
                if previous
                else {}
            ),
        },
        resource_type="session",
        resource_id=session.id,
    )


async def create_session(
    db: AsyncSession, data: SessionCreateRequest, actor: User
) -> ProgrammeSession:
    ensure_can_manage_session(actor, data.cohort_id, data.category)
    cohort = await get_cohort_or_404(db, data.cohort_id)
    ensure_cohort_writable(cohort)
    await _validate(db, cohort, data.track, data.mentors)

    values = data.model_dump(exclude={"mentors", "resources"})
    values["kami_limu_month"] = data.kami_limu_month or month_for(
        cohort, data.starts_at.date()
    )
    values["points"] = (
        settings.DEFAULT_SESSION_POINTS if data.points is None else data.points
    )
    session = ProgrammeSession(
        **values,
        created_by=actor.id,
        mentors=_mentors(data.mentors),
        resources=_resources(data.resources),
    )
    db.add(session)
    await db.flush()
    if session.status is SessionStatus.PUBLISHED:
        await sync_window(db, session, cohort)
    log_action(
        db,
        "create_session",
        user_id=actor.id,
        resource_type="session",
        resource_id=session.id,
    )
    await db.commit()
    await db.refresh(session)
    return session


async def list_sessions(
    db: AsyncSession, user: User, filters: SessionFilters
) -> tuple[list[ProgrammeSession], int]:
    stmt = select(ProgrammeSession).order_by(ProgrammeSession.starts_at)
    if not user.is_admin:
        cohort_ids = await accessible_cohort_ids(db, user)
        staff_ids = [c for c in cohort_ids if is_cohort_staff(user, c)]
        mentor_of = select(SessionMentor.session_id).where(
            SessionMentor.user_id == user.id
        )
        stmt = stmt.where(
            or_(
                ProgrammeSession.cohort_id.in_(staff_ids),
                ProgrammeSession.id.in_(mentor_of),
                ProgrammeSession.cohort_id.in_(cohort_ids)
                & (ProgrammeSession.status != SessionStatus.DRAFT),
            )
        )
    for field in (
        "cohort_id",
        "track",
        "kami_limu_month",
        "status",
        "category",
        "session_type",
    ):
        if (value := getattr(filters, field)) is not None:
            stmt = stmt.where(getattr(ProgrammeSession, field) == value)
    if filters.starts_after:
        stmt = stmt.where(ProgrammeSession.starts_at >= filters.starts_after)
    if filters.starts_before:
        stmt = stmt.where(ProgrammeSession.starts_at < filters.starts_before)
    return await paginate(db, stmt, filters)


async def update_session(
    db: AsyncSession, session: ProgrammeSession, data: SessionUpdateRequest, actor: User
) -> ProgrammeSession:
    cohort = await _managed_cohort(db, actor, session)
    if session.status is SessionStatus.CANCELLED:
        raise BusinessRuleViolation("Cancelled sessions cannot be edited")

    values = data.model_dump(exclude_unset=True)
    new_status = values.pop("status", None)
    if new_status not in (None, SessionStatus.PUBLISHED, SessionStatus.COMPLETED):
        raise BusinessRuleViolation(
            "Sessions can only be published or completed here; use DELETE to "
            "cancel and /reschedule to move them"
        )
    if new_status is SessionStatus.PUBLISHED and session.status is not (
        SessionStatus.DRAFT
    ):
        raise BusinessRuleViolation("Only draft sessions can be published")
    if "category" in values:
        ensure_can_manage_session(actor, session.cohort_id, values["category"])
    await _validate(db, cohort, values.get("track", session.track), [])
    for key, value in values.items():
        setattr(session, key, value)
    try:
        check_times(session.starts_at, session.ends_at, session.category)
    except ValueError as e:
        raise BusinessRuleViolation(str(e)) from e

    publishing = new_status is SessionStatus.PUBLISHED
    if new_status is not None:
        session.status = new_status
    if session.status is not SessionStatus.DRAFT and (
        publishing or "category" in values
    ):
        await sync_window(db, session, cohort)

    log_action(
        db,
        "update_session",
        user_id=actor.id,
        resource_type="session",
        resource_id=session.id,
        fields=sorted(data.model_dump(exclude_unset=True)),
    )
    await db.commit()
    await db.refresh(session)
    return session


async def reschedule_session(
    db: AsyncSession,
    session: ProgrammeSession,
    data: SessionRescheduleRequest,
    actor: User,
) -> ProgrammeSession:
    """Move a session, keeping its original time and history, and reset its window."""
    cohort = await _managed_cohort(db, actor, session)
    if session.status in (SessionStatus.CANCELLED, SessionStatus.COMPLETED):
        raise BusinessRuleViolation(
            f"Cannot reschedule a {session.status.value} session"
        )
    ends_at = data.ends_at or data.starts_at + (session.ends_at - session.starts_at)
    try:
        check_times(data.starts_at, ends_at, session.category)
    except ValueError as e:
        raise BusinessRuleViolation(str(e)) from e

    entry: dict[str, Any] = {
        "from": session.starts_at.isoformat(),
        "to": data.starts_at.isoformat(),
        "reason": data.reason,
        "by": str(actor.id),
        "at": datetime.now(UTC).isoformat(),
    }
    previous = (session.starts_at, session.ends_at)
    session.original_starts_at = session.original_starts_at or session.starts_at
    session.reschedule_history = [*(session.reschedule_history or []), entry]
    session.starts_at, session.ends_at = data.starts_at, ends_at
    session.kami_limu_month = month_for(cohort, data.starts_at.date())

    if session.status is not SessionStatus.DRAFT:
        session.status = SessionStatus.RESCHEDULED
        await sync_window(db, session, cohort, reset_overrides=True)
        await _announce(
            db, session, NotificationType.SESSION_RESCHEDULED, data.reason, previous
        )
    log_action(
        db,
        "reschedule_session",
        user_id=actor.id,
        resource_type="session",
        resource_id=session.id,
        **entry,
    )
    await db.commit()
    await db.refresh(session)
    return session


async def cancel_session(
    db: AsyncSession, session: ProgrammeSession, actor: User, reason: str | None
) -> None:
    await _managed_cohort(db, actor, session)
    if session.status is SessionStatus.CANCELLED:
        return
    was_published = session.status is not SessionStatus.DRAFT
    session.status = SessionStatus.CANCELLED
    if window := await get_window(db, session.id):
        window.is_active = False
        window.closed_at = datetime.now(UTC)
    if was_published:
        await _announce(db, session, NotificationType.SESSION_CANCELLED, reason)
    log_action(
        db,
        "cancel_session",
        user_id=actor.id,
        resource_type="session",
        resource_id=session.id,
        reason=reason,
    )
    await db.commit()


async def replace_mentors(
    db: AsyncSession,
    session: ProgrammeSession,
    mentors: list[MentorAssignment],
    actor: User,
) -> ProgrammeSession:
    cohort = await _managed_cohort(db, actor, session)
    await _validate(db, cohort, None, mentors)
    session.mentors.clear()
    await db.flush()
    session.mentors.extend(_mentors(mentors))
    await db.commit()
    await db.refresh(session)
    return session


async def replace_resources(
    db: AsyncSession,
    session: ProgrammeSession,
    resources: list[ResourceIn],
    actor: User,
) -> ProgrammeSession:
    """Session managers and the session's own mentors may manage its material links."""
    if not (
        can_manage_session(actor, session.cohort_id, session.category)
        or is_session_mentor(actor, session)
    ):
        raise PermissionDenied(
            "Only session managers or this session's mentors can update resources"
        )
    session.resources = _resources(resources)
    log_action(
        db,
        "update_session_resources",
        user_id=actor.id,
        resource_type="session",
        resource_id=session.id,
    )
    await db.commit()
    await db.refresh(session)
    return session


async def cohort_calendar(
    db: AsyncSession, user: User, cohort: Cohort, month: int | None = None
) -> list[CalendarMonth]:
    stmt = (
        select(ProgrammeSession)
        .where(ProgrammeSession.cohort_id == cohort.id)
        .order_by(ProgrammeSession.starts_at)
    )
    if not is_cohort_staff(user, cohort.id):
        stmt = stmt.where(ProgrammeSession.status != SessionStatus.DRAFT)
    if month is not None:
        stmt = stmt.where(ProgrammeSession.kami_limu_month == month)

    by_month: defaultdict[int, list[SessionResponse]] = defaultdict(list)
    for session in await db.scalars(stmt):
        by_month[session.kami_limu_month].append(
            SessionResponse.model_validate(session)
        )
    names = {b["month"]: b.get("name") for b in cohort.kami_limu_month_boundaries or []}
    return [
        CalendarMonth(month=m, name=names.get(m), sessions=s)
        for m, s in sorted(by_month.items())
    ]


async def in_progress(db: AsyncSession, user: User) -> list[InProgressSession]:
    """Sessions whose window is open for the caller, including tasks before their
    deadline and windows reopened for them, soonest closing first."""
    now = datetime.now(UTC)
    rows = await db.execute(
        select(ProgrammeSession, AttendanceWindow)
        .join(AttendanceWindow, AttendanceWindow.session_id == ProgrammeSession.id)
        .join(CohortEnrollment, applies_to_enrollment())
        .where(
            CohortEnrollment.user_id == user.id,
            ProgrammeSession.status.in_(COUNTED_STATUSES),
            AttendanceWindow.opens_at <= now,
        )
    )
    submitted = set(
        await db.scalars(
            select(AttendanceRecord.session_id).where(
                AttendanceRecord.mentee_id == user.id,
                AttendanceRecord.submitted_at.is_not(None),
            )
        )
    )
    items = [
        InProgressSession(
            session=SessionResponse.model_validate(session),
            closes_at=closes_at,
            submitted=session.id in submitted,
        )
        for session, window in rows.unique()
        if (closes_at := effective_closes_at(window, user.id)) > now
    ]
    return sorted(items, key=lambda i: i.closes_at)


async def ensure_participant(
    db: AsyncSession, user: User, session: ProgrammeSession
) -> None:
    if await get_participant_enrollment(db, user.id, session.cohort_id) is None:
        raise PermissionDenied("Only the session's participants keep notes on it")


async def get_note(
    db: AsyncSession, user: User, session: ProgrammeSession
) -> SessionNote:
    await ensure_participant(db, user, session)
    note = await db.scalar(
        select(SessionNote).where(
            SessionNote.user_id == user.id, SessionNote.session_id == session.id
        )
    )
    if note is None:
        raise NotFound("No notes for this session yet")
    return note


async def save_note(
    db: AsyncSession, user: User, session: ProgrammeSession, body: str
) -> SessionNote:
    await ensure_participant(db, user, session)
    note = await db.scalar(
        select(SessionNote).where(
            SessionNote.user_id == user.id, SessionNote.session_id == session.id
        )
    )
    if note is None:
        note = SessionNote(user_id=user.id, session_id=session.id, body=body)
        db.add(note)
    else:
        note.body = body
    await db.commit()
    await db.refresh(note)
    return note


async def advance_statuses(db: AsyncSession) -> int:
    """Mark sessions live while their window is open and completed once it has
    closed; participants are told when a window opens."""
    now = datetime.now(UTC)
    rows = await db.execute(
        select(ProgrammeSession, AttendanceWindow)
        .join(AttendanceWindow, AttendanceWindow.session_id == ProgrammeSession.id)
        .where(ProgrammeSession.status.in_(SCHEDULED_STATUSES))
    )
    changed = 0
    for session, window in rows:
        closed = not window.is_active or window.closes_at <= now
        if closed:
            session.status = SessionStatus.COMPLETED
        elif window.opens_at <= now and session.status is not SessionStatus.LIVE:
            session.status = SessionStatus.LIVE
            notify(
                db,
                await eligible_mentee_ids(db, session),
                NotificationType.WINDOW_OPENS,
                {"title": session.title, "closes_at": window.closes_at},
                resource_type="session",
                resource_id=session.id,
            )
        else:
            continue
        changed += 1
    await db.commit()
    return changed
