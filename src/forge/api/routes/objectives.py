"""Objective endpoints (replace skill ratings)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from forge.api.deps import ActiveUser, DbSession, ParticipantUser
from forge.models import Objective
from forge.schemas.objective import (
    ObjectiveCreateRequest,
    ObjectiveRatingRequest,
    ObjectiveResponse,
    ObjectiveUpdateRequest,
    ObjectiveWindowsResponse,
)
from forge.services import objectives as objective_service

router = APIRouter(tags=["Objectives"])


async def own_objective(
    objective_id: UUID, user: ActiveUser, db: DbSession
) -> Objective:
    return await objective_service.get_own_objective(db, user, objective_id)


OwnObjective = Annotated[Objective, Depends(own_objective)]


@router.get("/objectives/me", response_model=list[ObjectiveResponse])
async def my_objectives(
    user: ParticipantUser, db: DbSession, cohort_id: UUID | None = None
) -> list[Objective]:
    """Your Human and Technical objectives with their Start, Mid and End ratings."""
    return await objective_service.list_objectives(db, user.id, cohort_id)


@router.get("/objectives/windows")
async def objective_windows(
    user: ParticipantUser, db: DbSession, cohort_id: UUID | None = None
) -> ObjectiveWindowsResponse:
    """When the Start, Mid and End rating windows open and close."""
    return await objective_service.window_status(db, user, cohort_id)


@router.post(
    "/objectives",
    status_code=status.HTTP_201_CREATED,
    response_model=ObjectiveResponse,
)
async def create_objective(
    data: ObjectiveCreateRequest, user: ParticipantUser, db: DbSession
) -> Objective:
    """Create one of your objectives."""
    return await objective_service.create_objective(db, user, data)


@router.patch("/objectives/{objective_id}", response_model=ObjectiveResponse)
async def update_objective(
    data: ObjectiveUpdateRequest, objective: OwnObjective, db: DbSession
) -> Objective:
    """Edit your objective's text or type."""
    return await objective_service.update_objective(db, objective, data)


@router.post("/objectives/{objective_id}/ratings", response_model=ObjectiveResponse)
async def rate_objective(
    data: ObjectiveRatingRequest, objective: OwnObjective, db: DbSession
) -> Objective:
    """Rate your objective 1 to 5 at Start, Mid or End while that window is
    open. Rating again in the same window replaces the score."""
    return await objective_service.rate_objective(db, objective, data)


@router.get(
    "/mentees/{mentee_id}/objectives",
    response_model=list[ObjectiveResponse],
    tags=["Mentee Progress"],
)
async def mentee_objectives(
    mentee_id: UUID, user: ActiveUser, db: DbSession, cohort_id: UUID | None = None
) -> list[Objective]:
    """A mentee's objectives and ratings. **Their 1:1 peer mentor and staff.**"""
    return await objective_service.mentee_objectives(db, user, mentee_id, cohort_id)
