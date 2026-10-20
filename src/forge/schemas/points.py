"""Points, attendance-rate and graduation schemas."""

import enum
from datetime import datetime
from uuid import UUID

from forge.models import ActivityType, SessionType
from forge.schemas.common import Schema
from forge.schemas.user import UserSummary


class SessionOutcome(enum.StrEnum):
    ATTENDED = "attended"
    ABSENT = "absent"
    EXCUSED = "excused"
    UPCOMING = "upcoming"


class GraduationStatus(enum.StrEnum):
    ON_TRACK = "on_track"
    WARNING = "warning"
    AT_RISK = "at_risk"
    GRADUATED = "graduated"
    NOT_GRADUATED = "not_graduated"


class PointsBreakdownResponse(Schema):
    mentee_id: UUID
    cohort_id: UUID
    core_points_earned: int
    core_points_available: int
    extra_points: int
    total_points: int
    sessions_attended: int
    sessions_due: int
    sessions_excused: int
    sessions_upcoming: int


class SessionPointsEntry(Schema):
    session_id: UUID
    title: str
    starts_at: datetime
    kami_limu_month: int
    track: str | None
    session_type: SessionType
    points: int
    outcome: SessionOutcome
    points_earned: int


class ActivityPointsEntry(Schema):
    activity_id: UUID
    type: ActivityType
    title: str
    points_awarded: int


class PointsDetailResponse(PointsBreakdownResponse):
    sessions: list[SessionPointsEntry]
    extra_activities: list[ActivityPointsEntry]


class RateBucket(Schema):
    key: str
    points_earned: int
    points_available: int
    sessions_attended: int
    sessions_due: int
    rate: float


class AttendanceRateResponse(Schema):
    mentee_id: UUID
    cohort_id: UUID
    core_rate: float
    combined_rate: float
    by_month: list[RateBucket]
    by_track: list[RateBucket]
    by_session_type: list[RateBucket]


class GraduationStatusResponse(Schema):
    mentee_id: UUID
    cohort_id: UUID
    status: GraduationStatus
    combined_rate: float
    threshold: int
    warning_threshold: int
    points_to_threshold: int
    is_final: bool


class GraduationReportEntry(Schema):
    mentee: UserSummary
    peer_mentor_id: UUID | None
    ict_track: str | None
    total_points: int
    core_rate: float
    combined_rate: float
    status: GraduationStatus


class GraduationReportResponse(Schema):
    cohort_id: UUID
    threshold: int
    generated_at: datetime
    counts: dict[GraduationStatus, int]
    mentees: list[GraduationReportEntry]
