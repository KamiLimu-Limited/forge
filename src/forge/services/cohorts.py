"""Cohort and enrollment management."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.config import settings
from forge.core.exceptions import BusinessRuleViolation, Conflict, NotFound
from forge.models import (
    Cohort,
    CohortEnrollment,
    CohortStatus,
    User,
    UserRole,
    UserRoleAssignment,
)
from forge.schemas.cohort import (
    BulkEnrollmentResult,
    CohortCreateRequest,
    CohortFilters,
    CohortUpdateRequest,
    EnrollmentFilters,
    EnrollmentRequest,
    EnrollmentUpdateRequest,
)
from forge.services.access import get_cohort_or_404, is_cohort_staff
from forge.services.audit import log_action
from forge.services.pagination import paginate


def can_see_drafts(user: User) -> bool:
    return user.is_admin or UserRole.COMMITTEE in user.role_set


def _column_values(
    data: CohortCreateRequest | CohortUpdateRequest, *, exclude_unset: bool
) -> dict[str, Any]:
    values = data.model_dump(exclude_unset=exclude_unset)
    # JSONB columns need JSON-safe values (dates and datetimes as ISO strings).
    as_json = data.model_dump(mode="json", exclude_unset=exclude_unset)
    for field in ("kami_limu_month_boundaries", "skill_rating_windows"):
        if field in values:
            values[field] = as_json[field]
    return values


async def create_cohort(
    db: AsyncSession, data: CohortCreateRequest, actor: User
) -> Cohort:
    values = _column_values(data, exclude_unset=False)
    values["skill_names"] = data.skill_names or settings.DEFAULT_SKILL_NAMES
    values["leaderboard_anonymous"] = bool(data.leaderboard_anonymous)
    cohort = Cohort(**values)
    db.add(cohort)
    try:
        await db.flush()
    except IntegrityError as e:
        raise Conflict("A cohort with this name already exists") from e
    log_action(
        db,
        "create_cohort",
        user_id=actor.id,
        resource_type="cohort",
        resource_id=cohort.id,
    )
    await db.commit()
    return cohort


async def list_cohorts(
    db: AsyncSession, user: User, filters: CohortFilters
) -> tuple[list[Cohort], int]:
    stmt = (
        select(Cohort)
        .where(Cohort.deleted_at.is_(None))
        .order_by(Cohort.start_date.desc())
    )
    if not can_see_drafts(user):
        stmt = stmt.where(Cohort.status != CohortStatus.DRAFT)
    if filters.status:
        stmt = stmt.where(Cohort.status == filters.status)
    if filters.programme_type:
        stmt = stmt.where(Cohort.programme_type == filters.programme_type)
    if filters.search:
        stmt = stmt.where(Cohort.name.ilike(f"%{filters.search}%"))
    return await paginate(db, stmt, filters)


async def get_visible_cohort(
    db: AsyncSession, user: User, cohort_id: uuid.UUID
) -> Cohort:
    cohort = await get_cohort_or_404(db, cohort_id)
    if cohort.status is CohortStatus.DRAFT and not can_see_drafts(user):
        raise NotFound("Cohort not found")
    return cohort


async def enrollment_counts(
    db: AsyncSession, cohort_id: uuid.UUID
) -> dict[UserRole, int]:
    rows = await db.execute(
        select(CohortEnrollment.role, func.count())
        .where(CohortEnrollment.cohort_id == cohort_id)
        .group_by(CohortEnrollment.role)
    )
    return dict(rows.all())


async def update_cohort(
    db: AsyncSession, cohort: Cohort, data: CohortUpdateRequest, actor: User
) -> Cohort:
    values = _column_values(data, exclude_unset=True)
    for key, value in values.items():
        setattr(cohort, key, value)
    if cohort.end_date <= cohort.start_date:
        raise BusinessRuleViolation("end_date must be after start_date")
    try:
        await db.flush()
    except IntegrityError as e:
        raise Conflict("A cohort with this name already exists") from e
    log_action(
        db,
        "update_cohort",
        user_id=actor.id,
        resource_type="cohort",
        resource_id=cohort.id,
        fields=sorted(values),
    )
    await db.commit()
    await db.refresh(cohort)
    return cohort


async def soft_delete_cohort(db: AsyncSession, cohort: Cohort, actor: User) -> None:
    cohort.deleted_at = datetime.now(UTC)
    log_action(
        db,
        "delete_cohort",
        user_id=actor.id,
        resource_type="cohort",
        resource_id=cohort.id,
    )
    await db.commit()


def month_for(cohort: Cohort, when: date) -> int:
    """KamiLimu month for a date: configured boundaries first, else calendar months since start."""
    for boundary in cohort.kami_limu_month_boundaries or []:
        if (
            date.fromisoformat(boundary["start"])
            <= when
            <= date.fromisoformat(boundary["end"])
        ):
            return int(boundary["month"])
    months = (
        (when.year - cohort.start_date.year) * 12 + when.month - cohort.start_date.month
    )
    return max(months, 0) + 1


async def _validate_enrollment(
    db: AsyncSession, cohort: Cohort, data: EnrollmentRequest | EnrollmentUpdateRequest
) -> None:
    if (
        data.ict_track
        and cohort.ict_tracks_offered
        and data.ict_track not in cohort.ict_tracks_offered
    ):
        raise BusinessRuleViolation(
            f"ICT track '{data.ict_track}' is not offered in this cohort"
        )
    if data.peer_mentor_id:
        mentor = await db.scalar(
            select(CohortEnrollment.id).where(
                CohortEnrollment.cohort_id == cohort.id,
                CohortEnrollment.user_id == data.peer_mentor_id,
                CohortEnrollment.role == UserRole.PEER_MENTOR_1_1,
            )
        )
        if mentor is None:
            raise BusinessRuleViolation(
                "peer_mentor_id must be a 1:1 peer mentor enrolled in this cohort"
            )


async def ensure_role_assignment(
    db: AsyncSession,
    user_id: uuid.UUID,
    role: UserRole,
    cohort_id: uuid.UUID | None,
    assigned_by: uuid.UUID | None,
) -> None:
    exists = await db.scalar(
        select(UserRoleAssignment.id).where(
            UserRoleAssignment.user_id == user_id,
            UserRoleAssignment.role == role,
            UserRoleAssignment.cohort_id.is_(None)
            if cohort_id is None
            else UserRoleAssignment.cohort_id == cohort_id,
        )
    )
    if exists is None:
        db.add(
            UserRoleAssignment(
                user_id=user_id, role=role, cohort_id=cohort_id, assigned_by=assigned_by
            )
        )


async def add_enrollment(
    db: AsyncSession,
    cohort: Cohort,
    data: EnrollmentRequest,
    actor_id: uuid.UUID | None,
) -> CohortEnrollment:
    """Stage an enrollment (and its cohort-scoped role); caller commits."""
    if await db.get(User, data.user_id) is None:
        raise NotFound("User not found")
    await _validate_enrollment(db, cohort, data)
    duplicate = await db.scalar(
        select(CohortEnrollment.id).where(
            CohortEnrollment.cohort_id == cohort.id,
            CohortEnrollment.user_id == data.user_id,
            CohortEnrollment.role == data.role,
        )
    )
    if duplicate is not None:
        raise Conflict("User is already enrolled in this cohort with this role")

    enrollment = CohortEnrollment(
        cohort_id=cohort.id,
        user_id=data.user_id,
        role=data.role,
        peer_mentor_id=data.peer_mentor_id,
        ict_track=data.ict_track,
        enrolled_by=actor_id,
    )
    db.add(enrollment)
    await ensure_role_assignment(db, data.user_id, data.role, cohort.id, actor_id)
    await db.flush()
    return enrollment


async def enroll(
    db: AsyncSession, cohort: Cohort, data: EnrollmentRequest, actor: User
) -> CohortEnrollment:
    enrollment = await add_enrollment(db, cohort, data, actor.id)
    log_action(
        db,
        "enroll_user",
        user_id=actor.id,
        resource_type="cohort_enrollment",
        resource_id=enrollment.id,
        cohort_id=str(cohort.id),
        role=data.role.value,
    )
    await db.commit()
    await db.refresh(enrollment)
    return enrollment


async def bulk_enroll(
    db: AsyncSession, cohort: Cohort, entries: list[EnrollmentRequest], actor: User
) -> list[BulkEnrollmentResult]:
    results: list[BulkEnrollmentResult] = []
    for entry in entries:
        try:
            async with db.begin_nested():
                enrollment = await add_enrollment(db, cohort, entry, actor.id)
        except (Conflict, NotFound, BusinessRuleViolation) as e:
            results.append(
                BulkEnrollmentResult(
                    user_id=entry.user_id, success=False, message=e.detail
                )
            )
        else:
            results.append(
                BulkEnrollmentResult(
                    user_id=entry.user_id, success=True, enrollment_id=enrollment.id
                )
            )
    log_action(
        db,
        "bulk_enroll",
        user_id=actor.id,
        resource_type="cohort",
        resource_id=cohort.id,
        succeeded=sum(r.success for r in results),
    )
    await db.commit()
    return results


async def list_enrollments(
    db: AsyncSession, user: User, cohort: Cohort, filters: EnrollmentFilters
) -> tuple[list[CohortEnrollment], int]:
    stmt = (
        select(CohortEnrollment)
        .where(CohortEnrollment.cohort_id == cohort.id)
        .order_by(CohortEnrollment.enrolled_at)
    )
    if not is_cohort_staff(user, cohort.id):
        # Members see themselves and, for peer mentors, their group.
        stmt = stmt.where(
            (CohortEnrollment.user_id == user.id)
            | (CohortEnrollment.peer_mentor_id == user.id)
        )
    if filters.role:
        stmt = stmt.where(CohortEnrollment.role == filters.role)
    if filters.peer_mentor_id:
        stmt = stmt.where(CohortEnrollment.peer_mentor_id == filters.peer_mentor_id)
    if filters.ict_track:
        stmt = stmt.where(CohortEnrollment.ict_track == filters.ict_track)
    return await paginate(db, stmt, filters)


async def get_enrollment_or_404(
    db: AsyncSession, cohort: Cohort, enrollment_id: uuid.UUID
) -> CohortEnrollment:
    enrollment = await db.get(CohortEnrollment, enrollment_id)
    if enrollment is None or enrollment.cohort_id != cohort.id:
        raise NotFound("Enrollment not found")
    return enrollment


async def update_enrollment(
    db: AsyncSession,
    cohort: Cohort,
    enrollment: CohortEnrollment,
    data: EnrollmentUpdateRequest,
    actor: User,
) -> CohortEnrollment:
    await _validate_enrollment(db, cohort, data)
    values = data.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(enrollment, key, value)
    log_action(
        db,
        "update_enrollment",
        user_id=actor.id,
        resource_type="cohort_enrollment",
        resource_id=enrollment.id,
        fields=sorted(values),
    )
    await db.commit()
    await db.refresh(enrollment)
    return enrollment


async def remove_enrollment(
    db: AsyncSession, enrollment: CohortEnrollment, actor: User
) -> None:
    role_assignment = await db.scalar(
        select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == enrollment.user_id,
            UserRoleAssignment.role == enrollment.role,
            UserRoleAssignment.cohort_id == enrollment.cohort_id,
        )
    )
    if role_assignment is not None:
        await db.delete(role_assignment)
    await db.delete(enrollment)
    log_action(
        db,
        "remove_enrollment",
        user_id=actor.id,
        resource_type="cohort_enrollment",
        resource_id=enrollment.id,
    )
    await db.commit()
