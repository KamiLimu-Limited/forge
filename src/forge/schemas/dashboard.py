"""Role dashboard schemas."""

from uuid import UUID

from forge.schemas.activity import ExtraActivityResponse
from forge.schemas.attendance import SessionBrief
from forge.schemas.common import Schema
from forge.schemas.points import (
    AttendanceRateResponse,
    GraduationStatus,
    GraduationStatusResponse,
    PointsBreakdownResponse,
    PointsDetailResponse,
    RateBucket,
)
from forge.schemas.user import UserSummary


class MenteeOverview(Schema):
    cohort_id: UUID
    points: PointsBreakdownResponse
    graduation: GraduationStatusResponse
    next_session: SessionBrief | None
    open_attendance_windows: int
    pending_override_requests: int
    unread_notifications: int


class MenteeSummary(Schema):
    mentee: UserSummary
    ict_track: str | None
    total_points: int
    core_rate: float
    combined_rate: float
    status: GraduationStatus
    sessions_attended: int
    sessions_due: int


class GroupOverview(Schema):
    cohort_id: UUID
    mentees: list[MenteeSummary]
    average_combined_rate: float
    at_risk: int
    warning: int


class TaskCompletion(Schema):
    completed: int
    total: int


class MenteeDrilldown(Schema):
    summary: MenteeSummary
    points: PointsDetailResponse
    rates: AttendanceRateResponse
    graduation: GraduationStatusResponse
    recent_activities: list[ExtraActivityResponse]
    notes: int
    tasks: TaskCompletion


class TrackMenteeSummary(Schema):
    mentee: UserSummary
    track: RateBucket
    combined_rate: float
    status: GraduationStatus


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


class FeedbackEntry(Schema):
    respondent: str
    quality_rating: int | None
    usefulness_rating: int | None
    understanding_score: int | None
    feedback: str | None


class SessionFeedbackResponse(Schema):
    session_id: UUID
    responses: int
    averages: dict[str, float | None]
    entries: list[FeedbackEntry]
