"""Participants' Human and Technical objectives, rated at Start, Mid and End."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from forge.models import Cohort, Objective, ObjectiveRating, RatingPoint, User
from forge.schemas.objective import (
    ObjectiveCreateRequest,
    ObjectiveRatingRequest,
    ObjectiveUpdateRequest,
    ObjectiveWindow,
    ObjectiveWindowsResponse,
)
from forge.services.access import (
    ensure_cohort_writable,
    get_cohort_or_404,
    get_participant_enrollment_or_404,
    is_cohort_staff,
)
from forge.services.audit import log_action


def windows(cohort: Cohort, now: datetime | None = None) -> list[ObjectiveWindow]:
    now = now or datetime.now(UTC)
    configured = cohort.objective_windows or {}
    result = []
    for point in RatingPoint:
        window = configured.get(point)
        opens = datetime.fromisoformat(window["opens_at"]) if window else None
        closes = datetime.fromisoformat(window["closes_at"]) if window else None
        result.append(
            ObjectiveWindow(
                rating_point=point,
                opens_at=opens,
                closes_at=closes,
                is_open=opens is not None
                and closes is not None
                and opens <= now < closes,
            )
        )
    return result


async def window_status(
    db: AsyncSession, user: User, cohort_id: uuid.UUID | None
) -> ObjectiveWindowsResponse:
    enrollment = await get_participant_enrollment_or_404(db, user.id, cohort_id)
    cohort = await get_cohort_or_404(db, enrollment.cohort_id)
    return ObjectiveWindowsResponse(cohort_id=cohort.id, windows=windows(cohort))


async def list_objectives(
    db: AsyncSession, user_id: uuid.UUID, cohort_id: uuid.UUID | None = None
) -> list[Objective]:
    stmt = select(Objective).where(Objective.user_id == user_id)
    if cohort_id is not None:
        stmt = stmt.where(Objective.cohort_id == cohort_id)
    return list(await db.scalars(stmt.order_by(Objective.type, Objective.created_at)))


async def create_objective(
    db: AsyncSession, user: User, data: ObjectiveCreateRequest
) -> Objective:
    enrollment = await get_participant_enrollment_or_404(db, user.id, data.cohort_id)
    ensure_cohort_writable(await get_cohort_or_404(db, enrollment.cohort_id))
    objective = Objective(
        user_id=user.id,
        cohort_id=enrollment.cohort_id,
        type=data.type,
        text=data.text,
        ratings=[],
    )
    db.add(objective)
    await db.commit()
    await db.refresh(objective)
    return objective


async def get_own_objective(
    db: AsyncSession, user: User, objective_id: uuid.UUID
) -> Objective:
    objective = await db.get(Objective, objective_id)
    if objective is None:
        raise NotFound("Objective not found")
    if objective.user_id != user.id:
        raise PermissionDenied("You can only change your own objectives")
    return objective


async def update_objective(
    db: AsyncSession, objective: Objective, data: ObjectiveUpdateRequest
) -> Objective:
    ensure_cohort_writable(await get_cohort_or_404(db, objective.cohort_id))
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(objective, key, value)
    await db.commit()
    await db.refresh(objective)
    return objective


async def rate_objective(
    db: AsyncSession, objective: Objective, data: ObjectiveRatingRequest
) -> Objective:
    """Record or change the rating for a point while its window is open."""
    cohort = await get_cohort_or_404(db, objective.cohort_id)
    ensure_cohort_writable(cohort)
    window = next(w for w in windows(cohort) if w.rating_point is data.rating_point)
    if not window.is_open:
        raise BusinessRuleViolation(
            f"The {data.rating_point.value} rating window is not open"
        )
    rating = next(
        (r for r in objective.ratings if r.rating_point is data.rating_point), None
    )
    if rating is None:
        objective.ratings.append(
            ObjectiveRating(rating_point=data.rating_point, score=data.score)
        )
    else:
        rating.score = data.score
        rating.rated_at = datetime.now(UTC)
    log_action(
        db,
        "rate_objective",
        user_id=objective.user_id,
        resource_type="objective",
        resource_id=objective.id,
        rating_point=data.rating_point.value,
        score=data.score,
    )
    await db.commit()
    await db.refresh(objective)
    return objective


async def mentee_objectives(
    db: AsyncSession, viewer: User, mentee_id: uuid.UUID, cohort_id: uuid.UUID | None
) -> list[Objective]:
    """A participant's objectives, for themselves, their 1:1 peer mentor and staff."""
    enrollment = await get_participant_enrollment_or_404(db, mentee_id, cohort_id)
    if not (
        viewer.id in (mentee_id, enrollment.peer_mentor_id)
        or is_cohort_staff(viewer, enrollment.cohort_id)
    ):
        raise PermissionDenied("Only their 1:1 peer mentor and staff can view these")
    return await list_objectives(db, mentee_id, enrollment.cohort_id)
