"""Facilitator rating schemas for peer mentors."""

from datetime import datetime
from uuid import UUID

from forge.schemas.attendance import SessionBrief
from forge.schemas.common import Schema
from forge.schemas.dashboard import FeedbackEntry, QuestionAverage


class FacilitatedSession(Schema):
    session: SessionBrief
    responses: int
    average: float | None


class FacilitatorSummary(Schema):
    cohort_id: UUID
    sessions_completed: int
    sessions_in_progress: int
    average: float | None
    best_rated_session: FacilitatedSession | None


class SessionRatings(Schema):
    session: SessionBrief
    responses: int
    average: float | None
    questions: list[QuestionAverage]
    feedback: list[FeedbackEntry]


class RatingTrendPoint(Schema):
    session_id: UUID
    title: str
    starts_at: datetime
    average: float | None


class PeerMentorAverage(Schema):
    cohort_id: UUID
    peer_mentors: int
    average: float | None
