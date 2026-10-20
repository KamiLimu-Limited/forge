"""Skill self-assessment endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from forge.api.deps import DbSession, MenteeUser
from forge.models import SkillRating
from forge.schemas.mentorship import (
    SkillRatingRequest,
    SkillRatingResponse,
    SkillRatingWindowStatus,
)
from forge.services import mentorship as mentorship_service

router = APIRouter(prefix="/skill-ratings", tags=["Skills"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SkillRatingResponse,
    responses={
        200: {"model": SkillRatingResponse, "description": "Existing rating replaced"}
    },
)
async def submit_skill_rating(
    data: SkillRatingRequest, response: Response, mentee: MenteeUser, db: DbSession
) -> SkillRating:
    """Rate yourself 1–5 on each of the cohort's skills at the early, mid or late
    point of the programme. Only allowed while that point's window is open;
    resubmitting inside the window replaces the earlier rating (`200`)."""
    rating, created = await mentorship_service.submit_skill_rating(db, mentee, data)
    if not created:
        response.status_code = status.HTTP_200_OK
    return rating


@router.get("/windows")
async def rating_windows(
    mentee: MenteeUser, db: DbSession, cohort_id: Annotated[UUID | None, Query()] = None
) -> list[SkillRatingWindowStatus]:
    """Whether each rating window is open, and whether you have submitted for it."""
    return await mentorship_service.rating_windows(db, mentee, cohort_id)
