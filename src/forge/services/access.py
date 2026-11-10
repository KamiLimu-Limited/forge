"""Row-level access rules, enforced in the API layer.

Users see their own records, peer mentors see their group, committee members read
their cohort, and cohort managers (System Admins and Program Leads) read and
change everything.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from forge.models import (
    PARTICIPANT_ROLES,
    Cohort,
    CohortEnrollment,
    SessionCategory,
    User,
    UserRole,
)


def is_cohort_manager(user: User, cohort_id: uuid.UUID | None) -> bool:
    return user.is_admin or user.has_role(UserRole.PROGRAM_LEAD, cohort_id=cohort_id)


def ensure_cohort_manager(user: User, cohort_id: uuid.UUID | None) -> None:
    if not is_cohort_manager(user, cohort_id):
        raise PermissionDenied("Requires System Admin or Program Lead access")


def is_cohort_staff(user: User, cohort_id: uuid.UUID) -> bool:
    """Read access to everything in the cohort."""
    return is_cohort_manager(user, cohort_id) or user.has_role(
        UserRole.COMMITTEE, UserRole.PROGRAM_DELIVERY_LEAD, cohort_id=cohort_id
    )


def ensure_cohort_staff(user: User, cohort_id: uuid.UUID) -> None:
    if not is_cohort_staff(user, cohort_id):
        raise PermissionDenied("Requires committee access to this cohort")


def can_manage_session(
    user: User, cohort_id: uuid.UUID, category: SessionCategory
) -> bool:
    """Managers handle every session; the Program Delivery Lead runs peer mentorship."""
    return is_cohort_manager(user, cohort_id) or (
        category is SessionCategory.PEER_MENTORSHIP
        and user.has_role(UserRole.PROGRAM_DELIVERY_LEAD, cohort_id=cohort_id)
    )


def ensure_can_manage_session(
    user: User, cohort_id: uuid.UUID, category: SessionCategory
) -> None:
    if not can_manage_session(user, cohort_id, category):
        raise PermissionDenied("Not allowed to manage this session")


def ensure_cohort_writable(cohort: Cohort) -> None:
    if cohort.is_read_only:
        raise BusinessRuleViolation(f"Cohort is {cohort.status} and read-only")


async def get_cohort_or_404(db: AsyncSession, cohort_id: uuid.UUID) -> Cohort:
    cohort = await db.get(Cohort, cohort_id)
    if cohort is None:
        raise NotFound("Cohort not found")
    return cohort


async def get_writable_cohort(db: AsyncSession, cohort_id: uuid.UUID) -> Cohort:
    cohort = await get_cohort_or_404(db, cohort_id)
    ensure_cohort_writable(cohort)
    return cohort


async def get_enrollment(
    db: AsyncSession,
    user_id: uuid.UUID,
    cohort_id: uuid.UUID | None = None,
    role: UserRole = UserRole.MENTEE,
) -> CohortEnrollment | None:
    """The user's enrollment in ``cohort_id``, or their most recent one in ``role``."""
    stmt = select(CohortEnrollment).where(
        CohortEnrollment.user_id == user_id, CohortEnrollment.role == role
    )
    if cohort_id is not None:
        stmt = stmt.where(CohortEnrollment.cohort_id == cohort_id)
    return await db.scalar(stmt.order_by(CohortEnrollment.enrolled_at.desc()).limit(1))


async def get_mentee_enrollment_or_404(
    db: AsyncSession, mentee_id: uuid.UUID, cohort_id: uuid.UUID | None = None
) -> CohortEnrollment:
    enrollment = await get_enrollment(db, mentee_id, cohort_id)
    if enrollment is None:
        raise NotFound("Mentee enrollment not found")
    return enrollment


async def is_enrolled(
    db: AsyncSession, user_id: uuid.UUID, cohort_id: uuid.UUID
) -> bool:
    found = await db.scalar(
        select(CohortEnrollment.id)
        .where(
            CohortEnrollment.user_id == user_id, CohortEnrollment.cohort_id == cohort_id
        )
        .limit(1)
    )
    return found is not None


async def ensure_cohort_member(
    db: AsyncSession, user: User, cohort_id: uuid.UUID
) -> None:
    if is_cohort_staff(user, cohort_id) or await is_enrolled(db, user.id, cohort_id):
        return
    raise PermissionDenied("Not a member of this cohort")


def can_view_mentee(user: User, enrollment: CohortEnrollment) -> bool:
    return (
        user.id == enrollment.user_id
        or user.id == enrollment.peer_mentor_id
        or is_cohort_staff(user, enrollment.cohort_id)
    )


async def ensure_can_view_mentee(
    db: AsyncSession, user: User, mentee_id: uuid.UUID, cohort_id: uuid.UUID | None
) -> CohortEnrollment:
    enrollment = await get_participant_enrollment_or_404(db, mentee_id, cohort_id)
    if can_view_mentee(user, enrollment):
        return enrollment
    # ICT peer mentors may view mentees on the track they mentor.
    ict = await get_enrollment(
        db, user.id, enrollment.cohort_id, UserRole.PEER_MENTOR_ICT
    )
    if ict is not None and ict.ict_track and ict.ict_track == enrollment.ict_track:
        return enrollment
    raise PermissionDenied("Not allowed to view this mentee")


async def group_mentee_ids(
    db: AsyncSession, peer_mentor_id: uuid.UUID, cohort_id: uuid.UUID | None = None
) -> list[uuid.UUID]:
    stmt = select(CohortEnrollment.user_id).where(
        CohortEnrollment.peer_mentor_id == peer_mentor_id,
        CohortEnrollment.role == UserRole.MENTEE,
    )
    if cohort_id is not None:
        stmt = stmt.where(CohortEnrollment.cohort_id == cohort_id)
    return list(await db.scalars(stmt))


async def get_participant_enrollment(
    db: AsyncSession, user_id: uuid.UUID, cohort_id: uuid.UUID | None = None
) -> CohortEnrollment | None:
    """The user's mentee or peer mentor enrollment, most recent first."""
    stmt = select(CohortEnrollment).where(
        CohortEnrollment.user_id == user_id,
        CohortEnrollment.role.in_(PARTICIPANT_ROLES),
    )
    if cohort_id is not None:
        stmt = stmt.where(CohortEnrollment.cohort_id == cohort_id)
    return await db.scalar(stmt.order_by(CohortEnrollment.enrolled_at.desc()).limit(1))


async def get_participant_enrollment_or_404(
    db: AsyncSession, user_id: uuid.UUID, cohort_id: uuid.UUID | None = None
) -> CohortEnrollment:
    enrollment = await get_participant_enrollment(db, user_id, cohort_id)
    if enrollment is None:
        raise NotFound("No mentee or peer mentor enrollment found")
    return enrollment
