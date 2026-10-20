"""Row-level access rules, enforced in the API layer.

These mirror the RLS policies from the implementation plan: users see their own
records, peer mentors see their group, committee members see their cohort and
admins see everything.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.exceptions import NotFound, PermissionDenied
from forge.models import Cohort, CohortEnrollment, User, UserRole


def is_cohort_staff(user: User, cohort_id: uuid.UUID) -> bool:
    return user.is_admin or user.has_role(UserRole.COMMITTEE, cohort_id=cohort_id)


def ensure_cohort_staff(user: User, cohort_id: uuid.UUID) -> None:
    if not is_cohort_staff(user, cohort_id):
        raise PermissionDenied("Requires committee access to this cohort")


async def get_cohort_or_404(db: AsyncSession, cohort_id: uuid.UUID) -> Cohort:
    cohort = await db.get(Cohort, cohort_id)
    if cohort is None or cohort.deleted_at is not None:
        raise NotFound("Cohort not found")
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
    enrollment = await get_mentee_enrollment_or_404(db, mentee_id, cohort_id)
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
