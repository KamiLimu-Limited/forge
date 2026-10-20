"""Analytics and dashboard schemas."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from forge.models import ActivityStatus, ActivityType
from forge.schemas.common import Schema
from forge.schemas.points import GraduationStatus, RateBucket


class TrendPoint(Schema):
    month: int
    sessions: int
    points_earned: int
    points_available: int
    rate: float


class AttendanceTrendResponse(Schema):
    cohort_id: UUID
    months: list[TrendPoint]


class TrackPerformance(Schema):
    track: str
    mentees: int
    bucket: RateBucket


class TrackPerformanceResponse(Schema):
    cohort_id: UUID
    tracks: list[TrackPerformance]


class SessionQuality(Schema):
    session_id: UUID
    title: str
    starts_at: datetime
    kami_limu_month: int
    responses: int
    quality: float | None
    usefulness: float | None
    understanding: float | None
    academic_application: float | None
    career_application: float | None


class SessionQualityResponse(Schema):
    cohort_id: UUID
    overall_quality: float | None
    overall_usefulness: float | None
    sessions: list[SessionQuality]


class HealthPoint(Schema):
    month: int
    average_rate: float
    counts: dict[GraduationStatus, int]


class HealthTrajectoryResponse(Schema):
    cohort_id: UUID
    months: list[HealthPoint]


class ActivityEngagement(Schema):
    type: ActivityType
    counts: dict[ActivityStatus, int]
    points_awarded: int
    mentees_participating: int


class ActivityEngagementResponse(Schema):
    cohort_id: UUID
    mentees: int
    types: list[ActivityEngagement]


class CohortHealthResponse(Schema):
    cohort_id: UUID
    total_mentees: int
    counts: dict[GraduationStatus, int]
    average_core_rate: float
    average_combined_rate: float
    pending_override_requests: int
    pending_activities: int


class CohortComparison(Schema):
    cohort_id: UUID
    name: str
    start_date: date
    health: CohortHealthResponse
    activities_per_mentee: float


class CrossCohortResponse(Schema):
    cohorts: list[CohortComparison]


class SnapshotResponse(Schema):
    id: UUID
    cohort_id: UUID
    snapshot_date: date
    metrics: dict[str, Any] = Field(
        description="Health, trends, tracks and engagement at that date"
    )
    created_at: datetime
