"""Role dashboard schemas."""

from datetime import datetime
from uuid import UUID

from forge.models.cohort import RatingGroup
from forge.schemas.activity import ExtraActivityResponse
from forge.schemas.attendance import SessionBrief
from forge.schemas.common import Schema
from forge.schemas.objective import ObjectiveResponse
from forge.schemas.points import (
    AttendanceRateResponse,
    GraduationStatusResponse,
    PointsBreakdownResponse,
    PointsDetailResponse,
    RateBucket,
)
from forge.schemas.user import UserSummary


class QuestionAverage(Schema):
    number: int
    group: RatingGroup
    text: str
    average: float | None


class MenteeOverview(Schema):
    cohort_id: UUID
    points: PointsBreakdownResponse
    core_rate: float
    overall_rate: float
    graduation_threshold: int
    next_session: SessionBrief | None
    open_attendance_windows: int
    pending_override_requests: int
    unread_notifications: int


class MenteeSummary(Schema):
    mentee: UserSummary
    ict_track: str | None
    total_points: int
    core_rate: float
    overall_rate: float
    sessions_attended: int
    sessions_due: int


class GroupOverview(Schema):
    cohort_id: UUID
    mentees: list[MenteeSummary]
    average_core_rate: float
    average_overall_rate: float


class MenteeSessionFeedback(Schema):
    session: SessionBrief
    ratings: list[int | None] | None
    feedback: str | None
    submitted_at: datetime | None


class MenteeDrilldown(Schema):
    summary: MenteeSummary
    points: PointsDetailResponse
    rates: AttendanceRateResponse
    graduation: GraduationStatusResponse
    objectives: list[ObjectiveResponse]
    session_feedback: list[MenteeSessionFeedback]
    recent_activities: list[ExtraActivityResponse]


class TrackMenteeSummary(Schema):
    mentee: UserSummary
    track: RateBucket
    core_rate: float
    overall_rate: float


class TrackOverview(Schema):
    cohort_id: UUID
    track: str
    mentees: list[TrackMenteeSummary]


class SessionAttendanceSummary(Schema):
    session: SessionBrief
    eligible: int
    attended: int
    responses: int
    average_quality: float | None
    question_averages: list[QuestionAverage]


class FeedbackEntry(Schema):
    respondent: str
    mentee_id: UUID | None = None
    ratings: list[int | None] | None
    feedback: str | None


class SessionFeedbackResponse(Schema):
    session_id: UUID
    responses: int
    anonymous: bool
    questions: list[QuestionAverage]
    entries: list[FeedbackEntry]
