"""Points, attendance-rate and graduation schemas."""

import enum
from datetime import datetime
from uuid import UUID

from pydantic import Field

from forge.models import ActivityType, SessionType
from forge.schemas.common import Schema
from forge.schemas.user import UserSummary


class SessionOutcome(enum.StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    MISSED = "missed"
    EXCUSED = "excused"
    REMAINING = "remaining"


class GraduationStatus(enum.StrEnum):
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
    sessions_absent: int
    sessions_missed: int
    points_missed: int
    sessions_excused: int
    sessions_remaining: int = Field(
        description="Sessions not counted yet: upcoming or with an open window"
    )
    points_remaining: int


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
    overall_rate: float
    by_month: list[RateBucket]
    by_track: list[RateBucket]
    by_session_type: list[RateBucket]


class GraduationStatusResponse(Schema):
    mentee_id: UUID
    cohort_id: UUID
    status: GraduationStatus | None = Field(
        description="Set once the cohort has graduated"
    )
    core_rate: float
    overall_rate: float
    threshold: int
    points_to_threshold: int = Field(
        description="Core points still needed to reach the threshold"
    )
    is_final: bool


class GraduationReportEntry(Schema):
    mentee: UserSummary
    peer_mentor_id: UUID | None
    ict_track: str | None
    total_points: int
    core_rate: float
    overall_rate: float
    status: GraduationStatus | None


class GraduationReportResponse(Schema):
    cohort_id: UUID
    threshold: int
    generated_at: datetime
    counts: dict[GraduationStatus, int]
    mentees: list[GraduationReportEntry]
