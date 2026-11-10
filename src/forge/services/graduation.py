"""Graduation: preview, confirmation, the graduation sequence, corrections, and
closing and archiving the cohort.

Graduation is decided once, on each mentee's core rate against the cohort
threshold. Confirming it freezes the results; corrections change a frozen result
with a recorded reason.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.exceptions import BusinessRuleViolation, NotFound
from forge.models import (
    PEER_MENTOR_ROLES,
    AttendanceWindow,
    Cohort,
    CohortEnrollment,
    CohortGraduation,
    CohortStatus,
    GraduationCorrection,
    GraduationResult,
    OverrideRequest,
    OverrideRequestStatus,
    ProgrammeSession,
    SessionMentor,
    SessionStatus,
    User,
    UserRole,
    UserRoleAssignment,
)
from forge.schemas.graduation import (
    AlumniCohort,
    GraduationAvailability,
    GraduationCard,
    GraduationEntry,
    GraduationPanel,
    GraduationPreview,
    GraduationRecord,
    GraduationSequence,
    MentorServed,
    ProgrammeStats,
)
from forge.schemas.user import CohortBrief, UserSummary
from forge.services.audit import log_action
from forge.services.cohorts import ensure_role_assignment
from forge.services.points import compute_stats, mentee_enrollments


def _now() -> datetime:
    return datetime.now(UTC)


async def get_record(db: AsyncSession, cohort: Cohort) -> CohortGraduation | None:
    return await db.scalar(
        select(CohortGraduation).where(CohortGraduation.cohort_id == cohort.id)
    )


async def _confirmed_record(db: AsyncSession, cohort: Cohort) -> CohortGraduation:
    record = await get_record(db, cohort)
    if record is None or not record.is_confirmed:
        raise NotFound("This cohort has not graduated yet")
    return record


async def compute_preview(db: AsyncSession, cohort: Cohort) -> GraduationPreview:
    enrollments = await mentee_enrollments(db, cohort.id)
    stats = await compute_stats(db, cohort.id, [e.user_id for e in enrollments])
    entries = sorted(
        (
            GraduationEntry(
                mentee=UserSummary.model_validate(e.user),
                core_rate=stats[e.user_id].core_rate,
                overall_rate=stats[e.user_id].overall_rate,
                core_points=stats[e.user_id].total.earned,
                extra_points=stats[e.user_id].extra_points,
                total_points=stats[e.user_id].total_points,
                graduated=stats[e.user_id].meets_threshold(cohort.graduation_threshold),
            )
            for e in enrollments
        ),
        key=lambda entry: (-entry.core_rate, entry.mentee.last_name),
    )
    return GraduationPreview(
        cohort_id=cohort.id,
        threshold=cohort.graduation_threshold,
        computed_at=_now(),
        graduates=[e for e in entries if e.graduated],
        non_graduates=[e for e in entries if not e.graduated],
    )


async def preview(db: AsyncSession, cohort: Cohort) -> GraduationPreview:
    """The last stored preview, or a fresh one when none has been run."""
    record = await get_record(db, cohort)
    if record is not None and record.preview is not None:
        return GraduationPreview.model_validate(record.preview)
    return await compute_preview(db, cohort)


async def refresh_preview(db: AsyncSession, cohort: Cohort) -> GraduationPreview:
    record = await get_record(db, cohort)
    if record is not None and record.is_confirmed:
        raise BusinessRuleViolation("This cohort has already graduated")
    result = await compute_preview(db, cohort)
    if record is None:
        record = CohortGraduation(cohort_id=cohort.id, threshold=result.threshold)
        db.add(record)
    record.threshold = result.threshold
    record.preview = result.model_dump(mode="json")
    record.preview_computed_at = result.computed_at
    await db.commit()
    return result


async def availability(db: AsyncSession, cohort: Cohort) -> GraduationAvailability:
    reasons = []
    record = await get_record(db, cohort)
    if record is not None and record.is_confirmed:
        reasons.append("The cohort has already graduated")
    elif cohort.status is not CohortStatus.ACTIVE:
        reasons.append(f"The cohort is {cohort.status.value}, not active")
    if cohort.end_date > date.today():
        reasons.append(f"The programme ends on {cohort.end_date.isoformat()}")
    open_windows = await db.scalar(
        select(func.count())
        .select_from(AttendanceWindow)
        .join(ProgrammeSession, ProgrammeSession.id == AttendanceWindow.session_id)
        .where(
            ProgrammeSession.cohort_id == cohort.id,
            AttendanceWindow.is_active.is_(True),
            AttendanceWindow.closes_at > _now(),
        )
    )
    if open_windows:
        reasons.append(f"{open_windows} attendance window(s) are still open")
    pending = await db.scalar(
        select(func.count())
        .select_from(OverrideRequest)
        .join(ProgrammeSession, ProgrammeSession.id == OverrideRequest.session_id)
        .where(
            ProgrammeSession.cohort_id == cohort.id,
            OverrideRequest.status == OverrideRequestStatus.PENDING,
        )
    )
    if pending:
        reasons.append(f"{pending} window extension request(s) are pending")
    return GraduationAvailability(available=not reasons, reasons=reasons)


async def _grant_alumni(db: AsyncSession, user: User, actor: User) -> None:
    user.alumni_since = user.alumni_since or date.today()
    await ensure_role_assignment(db, user.id, UserRole.ALUMNI, None, actor.id)


async def _revoke_alumni(db: AsyncSession, user: User) -> None:
    """Clear alumni status unless another confirmed graduation still grants it."""
    other = await db.scalar(
        select(GraduationResult.id).where(
            GraduationResult.user_id == user.id, GraduationResult.graduated.is_(True)
        )
    )
    if other is not None:
        return
    user.alumni_since = None
    role = await db.scalar(
        select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user.id,
            UserRoleAssignment.role == UserRole.ALUMNI,
            UserRoleAssignment.cohort_id.is_(None),
        )
    )
    if role is not None:
        await db.delete(role)


async def graduate(db: AsyncSession, cohort: Cohort, actor: User) -> GraduationRecord:
    """Freeze results, complete the cohort and make its graduates alumni."""
    check = await availability(db, cohort)
    if not check.available:
        raise BusinessRuleViolation("; ".join(check.reasons))
    result = await compute_preview(db, cohort)
    record = await get_record(db, cohort)
    if record is None:
        record = CohortGraduation(cohort_id=cohort.id, threshold=result.threshold)
        db.add(record)
    record.threshold = result.threshold
    record.preview = result.model_dump(mode="json")
    record.preview_computed_at = result.computed_at
    record.confirmed_by = actor.id
    record.confirmed_at = _now()
    await db.flush()

    for entry in [*result.graduates, *result.non_graduates]:
        db.add(
            GraduationResult(
                graduation_id=record.id,
                user_id=entry.mentee.id,
                core_rate=entry.core_rate,
                overall_rate=entry.overall_rate,
                core_points=entry.core_points,
                extra_points=entry.extra_points,
                total_points=entry.total_points,
                graduated=entry.graduated,
            )
        )
    for entry in result.graduates:
        user = await db.get(User, entry.mentee.id)
        assert user is not None
        await _grant_alumni(db, user, actor)
    cohort.status = CohortStatus.COMPLETED
    log_action(
        db,
        "graduate_cohort",
        user_id=actor.id,
        resource_type="cohort",
        resource_id=cohort.id,
        threshold=result.threshold,
        graduates=len(result.graduates),
        non_graduates=len(result.non_graduates),
    )
    await db.commit()
    return await confirmed(db, cohort)


def _entry(result: GraduationResult) -> GraduationEntry:
    return GraduationEntry(
        mentee=UserSummary.model_validate(result.user),
        core_rate=result.core_rate,
        overall_rate=result.overall_rate,
        core_points=result.core_points,
        extra_points=result.extra_points,
        total_points=result.total_points,
        graduated=result.graduated,
    )


async def confirmed(db: AsyncSession, cohort: Cohort) -> GraduationRecord:
    record = await _confirmed_record(db, cohort)
    await db.refresh(record, ["results"])
    entries = sorted(
        (_entry(r) for r in record.results),
        key=lambda e: (-e.core_rate, e.mentee.last_name),
    )
    assert record.confirmed_at is not None
    return GraduationRecord(
        cohort_id=cohort.id,
        threshold=record.threshold,
        confirmed_at=record.confirmed_at,
        confirmed_by=record.confirmed_by,
        graduates=[e for e in entries if e.graduated],
        non_graduates=[e for e in entries if not e.graduated],
    )


async def frozen_result(
    db: AsyncSession, cohort_id: uuid.UUID, user_id: uuid.UUID
) -> GraduationResult | None:
    return await db.scalar(
        select(GraduationResult)
        .join(CohortGraduation, CohortGraduation.id == GraduationResult.graduation_id)
        .where(
            CohortGraduation.cohort_id == cohort_id,
            GraduationResult.user_id == user_id,
        )
    )


async def sequence(db: AsyncSession, cohort: Cohort) -> GraduationSequence:
    record = await _confirmed_record(db, cohort)
    graduates = (await confirmed(db, cohort)).graduates
    order = {uid: i for i, uid in enumerate(record.reveal_order or [])}
    graduates.sort(
        key=lambda e: (order.get(str(e.mentee.id), len(order)), e.mentee.last_name)
    )

    session_mentors = await db.execute(
        select(User, func.count(func.distinct(SessionMentor.session_id)))
        .join(SessionMentor, SessionMentor.user_id == User.id)
        .join(ProgrammeSession, ProgrammeSession.id == SessionMentor.session_id)
        .where(
            ProgrammeSession.cohort_id == cohort.id,
            ProgrammeSession.status != SessionStatus.CANCELLED,
        )
        .group_by(User.id)
    )
    mentors: dict[uuid.UUID, MentorServed] = {
        user.id: MentorServed(
            user=UserSummary.model_validate(user), roles=["session_mentor"]
        )
        for user, _ in session_mentors
    }
    for enrollment in await mentee_enrollments(db, cohort.id, PEER_MENTOR_ROLES):
        served = mentors.setdefault(
            enrollment.user_id,
            MentorServed(user=UserSummary.model_validate(enrollment.user), roles=[]),
        )
        served.roles.append(enrollment.role.value)

    sessions_held = await db.scalar(
        select(func.count()).where(
            ProgrammeSession.cohort_id == cohort.id,
            ProgrammeSession.status == SessionStatus.COMPLETED,
        )
    )
    results = record.results
    return GraduationSequence(
        cohort_id=cohort.id,
        cohort_name=cohort.name,
        graduates=graduates,
        stats=ProgrammeStats(
            mentees=len(results),
            graduates=len(graduates),
            sessions_held=sessions_held or 0,
            points_distributed=sum(r.total_points for r in results),
            average_core_rate=round(sum(r.core_rate for r in results) / len(results), 2)
            if results
            else 0.0,
        ),
        mentors=sorted(
            mentors.values(), key=lambda m: (m.user.last_name, m.user.first_name)
        ),
    )


async def set_reveal_order(
    db: AsyncSession, cohort: Cohort, order: list[uuid.UUID], actor: User
) -> GraduationSequence:
    record = await _confirmed_record(db, cohort)
    graduates = {r.user_id for r in record.results if r.graduated}
    if set(order) != graduates or len(order) != len(graduates):
        raise BusinessRuleViolation("reveal_order must list every graduate once")
    record.reveal_order = [str(uid) for uid in order]
    log_action(
        db,
        "set_graduation_reveal_order",
        user_id=actor.id,
        resource_type="cohort",
        resource_id=cohort.id,
    )
    await db.commit()
    return await sequence(db, cohort)


async def correct(
    db: AsyncSession,
    cohort: Cohort,
    user_id: uuid.UUID,
    graduated: bool,
    reason: str,
    actor: User,
) -> GraduationCorrection:
    """Change a confirmed result, keeping the old value and the reason."""
    await _confirmed_record(db, cohort)
    result = await frozen_result(db, cohort.id, user_id)
    if result is None:
        raise NotFound("No graduation result for this mentee")
    if result.graduated is graduated:
        raise BusinessRuleViolation("The result already has this value")
    correction = GraduationCorrection(
        result_id=result.id,
        field="graduated",
        old_value=str(result.graduated).lower(),
        new_value=str(graduated).lower(),
        reason=reason,
        corrected_by=actor.id,
    )
    db.add(correction)
    result.graduated = graduated
    await db.flush()
    user = result.user
    if graduated:
        await _grant_alumni(db, user, actor)
    else:
        await _revoke_alumni(db, user)
    log_action(
        db,
        "correct_graduation_result",
        user_id=actor.id,
        resource_type="graduation_result",
        resource_id=result.id,
        mentee_id=str(user_id),
        graduated=graduated,
        reason=reason,
    )
    await db.commit()
    await db.refresh(correction)
    return correction


async def close(db: AsyncSession, cohort: Cohort, actor: User) -> Cohort:
    """Close a graduated cohort and archive its peer mentor assignments."""
    await _confirmed_record(db, cohort)
    if cohort.closed_at is not None:
        raise BusinessRuleViolation("The cohort is already closed")
    now = _now()
    cohort.closed_at = now
    await db.execute(
        update(CohortEnrollment)
        .where(
            CohortEnrollment.cohort_id == cohort.id,
            CohortEnrollment.role.in_(PEER_MENTOR_ROLES),
            CohortEnrollment.archived_at.is_(None),
        )
        .values(archived_at=now)
    )
    roles = await db.scalars(
        select(UserRoleAssignment).where(
            UserRoleAssignment.cohort_id == cohort.id,
            UserRoleAssignment.role.in_(PEER_MENTOR_ROLES),
        )
    )
    for role in roles:
        await db.delete(role)
    log_action(
        db,
        "close_cohort",
        user_id=actor.id,
        resource_type="cohort",
        resource_id=cohort.id,
    )
    await db.commit()
    await db.refresh(cohort)
    return cohort


async def archive(db: AsyncSession, cohort: Cohort, actor: User) -> Cohort:
    """Make a closed (or imported) cohort an archived, read-only record."""
    if cohort.status is CohortStatus.ARCHIVED:
        raise BusinessRuleViolation("The cohort is already archived")
    if not (cohort.closed_at is not None or cohort.is_imported):
        raise BusinessRuleViolation("Close the cohort before archiving it")
    cohort.status = CohortStatus.ARCHIVED
    cohort.archived_at = _now()
    log_action(
        db,
        "archive_cohort",
        user_id=actor.id,
        resource_type="cohort",
        resource_id=cohort.id,
    )
    await db.commit()
    await db.refresh(cohort)
    return cohort


async def panel(db: AsyncSession, cohort: Cohort) -> GraduationPanel:
    record = await get_record(db, cohort)
    return GraduationPanel(
        cohort_id=cohort.id,
        preview=await preview(db, cohort),
        confirmed=record is not None and record.is_confirmed,
        confirmed_at=record.confirmed_at if record else None,
        availability=await availability(db, cohort),
    )


async def graduation_card(db: AsyncSession, user: User) -> GraduationCard:
    row = (
        await db.execute(
            select(GraduationResult, CohortGraduation, Cohort)
            .join(
                CohortGraduation,
                CohortGraduation.id == GraduationResult.graduation_id,
            )
            .join(Cohort, Cohort.id == CohortGraduation.cohort_id)
            .where(
                GraduationResult.user_id == user.id,
                GraduationResult.graduated.is_(True),
            )
            .order_by(CohortGraduation.confirmed_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise NotFound("You have no graduation on record")
    result, record, cohort = row
    assert record.confirmed_at is not None
    return GraduationCard(
        cohort=CohortBrief.model_validate(cohort),
        graduated_on=record.confirmed_at.date(),
        core_rate=result.core_rate,
        overall_rate=result.overall_rate,
        total_points=result.total_points,
    )


async def alumni_history(db: AsyncSession, user: User) -> list[AlumniCohort]:
    """Every finished cohort the user took part in, with their frozen result."""
    enrollments = await db.execute(
        select(Cohort, CohortEnrollment.role)
        .join(CohortEnrollment, CohortEnrollment.cohort_id == Cohort.id)
        .where(
            CohortEnrollment.user_id == user.id,
            Cohort.status.in_((CohortStatus.COMPLETED, CohortStatus.ARCHIVED)),
        )
        .order_by(Cohort.start_date.desc())
    )
    by_cohort: dict[uuid.UUID, tuple[Cohort, list[UserRole]]] = {}
    for cohort, role in enrollments:
        by_cohort.setdefault(cohort.id, (cohort, []))[1].append(role)
    history = []
    for cohort, roles in by_cohort.values():
        result = await frozen_result(db, cohort.id, user.id)
        history.append(
            AlumniCohort(
                cohort=CohortBrief.model_validate(cohort),
                roles=roles,
                result=_entry(result) if result else None,
            )
        )
    return history
