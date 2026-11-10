"""Facilitator ratings for peer mentors."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from forge.api.deps import DbSession, OneOnOnePeerMentorUser, PeerMentorUser
from forge.schemas.facilitator import (
    FacilitatedSession,
    FacilitatorSummary,
    PeerMentorAverage,
    RatingTrendPoint,
    SessionRatings,
)
from forge.services import facilitator as facilitator_service

router = APIRouter(tags=["Facilitator Ratings"])

CohortParam = Annotated[
    UUID | None, Query(description="Defaults to your most recent cohort")
]


@router.get("/facilitator/me/summary")
async def my_summary(
    user: PeerMentorUser, db: DbSession, cohort_id: CohortParam = None
) -> FacilitatorSummary:
    """Sessions you mentored that are completed or in progress, your average
    rating and your best-rated session."""
    return await facilitator_service.summary(db, user, cohort_id)


@router.get("/facilitator/me/sessions")
async def my_sessions(
    user: PeerMentorUser, db: DbSession, cohort_id: CohortParam = None
) -> list[FacilitatedSession]:
    """Sessions you mentored with their average rating. On peer mentorship
    sessions only your group's ratings count."""
    cohort = await facilitator_service.peer_mentor_cohort(db, user, cohort_id)
    return await facilitator_service.facilitated(db, user.id, cohort)


@router.get("/facilitator/me/sessions/{session_id}/ratings")
async def my_session_ratings(
    session_id: UUID, user: PeerMentorUser, db: DbSession
) -> SessionRatings:
    """The average of each of the nine questions and the written feedback for
    one session you mentored, from anonymous respondents."""
    return await facilitator_service.session_ratings(db, user, session_id)


@router.get("/facilitator/me/ratings-over-time")
async def my_ratings_over_time(
    user: PeerMentorUser, db: DbSession, cohort_id: CohortParam = None
) -> list[RatingTrendPoint]:
    """Your average rating per session, in date order."""
    return await facilitator_service.ratings_over_time(db, user, cohort_id)


@router.get("/facilitator/peer-mentor-average")
async def peer_mentor_average(
    user: PeerMentorUser, db: DbSession, cohort_id: CohortParam = None
) -> PeerMentorAverage:
    """The average rating across all peer mentors in your cohort, for comparison."""
    return await facilitator_service.peer_mentor_average(db, user, cohort_id)


@router.get("/peer-mentor/me/peer-mentorship-feedback")
async def my_peer_mentorship_feedback(
    user: OneOnOnePeerMentorUser, db: DbSession, cohort_id: CohortParam = None
) -> list[SessionRatings]:
    """Ratings and written feedback your own mentees gave on each peer mentorship
    session, from anonymous respondents. **1:1 peer mentors.**"""
    return await facilitator_service.peer_mentorship_feedback(db, user, cohort_id)
