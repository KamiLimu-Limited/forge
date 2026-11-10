"""Cohort, enrollment and cohort configuration schemas."""

from datetime import date, datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from forge.core.config import settings
from forge.models import (
    RATING_QUESTION_COUNT,
    ActivityType,
    CohortStatus,
    ProgrammeType,
    RatingPoint,
    UserRole,
)
from forge.models.cohort import RatingGroup
from forge.schemas.common import PageParams, RequestSchema, Schema
from forge.schemas.user import UserSummary

Points = Annotated[int, Field(ge=0, le=100)]


class MonthBoundary(Schema):
    month: int = Field(ge=1, le=24)
    name: str | None = None
    start: date
    end: date

    @model_validator(mode="after")
    def check_range(self) -> Self:
        if self.end < self.start:
            raise ValueError("Month end must not precede its start")
        return self


class TimeWindow(Schema):
    opens_at: datetime
    closes_at: datetime

    @model_validator(mode="after")
    def check_range(self) -> Self:
        if self.closes_at <= self.opens_at:
            raise ValueError("Window must close after it opens")
        return self


class CohortFields(RequestSchema):
    kami_limu_month_boundaries: list[MonthBoundary] | None = None
    thursday_window_hours: int | None = Field(None, ge=1, le=24 * 14)
    saturday_window_hours: int | None = Field(None, ge=1, le=24 * 14)
    objective_windows: dict[RatingPoint, TimeWindow] | None = None
    extra_log_window_days: int | None = Field(None, ge=1, le=365)
    track_selection_opens_at: datetime | None = None
    track_selection_closes_at: datetime | None = None

    @model_validator(mode="after")
    def check_track_selection_window(self) -> Self:
        opens, closes = self.track_selection_opens_at, self.track_selection_closes_at
        if opens and closes and closes <= opens:
            raise ValueError("Track selection must close after it opens")
        return self


class CohortCreateRequest(CohortFields):
    name: str = Field(min_length=1, max_length=100, examples=["Cohort 11"])
    programme_type: ProgrammeType
    start_date: date
    end_date: date
    graduation_threshold: int = Field(
        settings.DEFAULT_GRADUATION_THRESHOLD,
        ge=1,
        le=100,
        description="Minimum core attendance rate (percent) required to graduate.",
    )
    status: CohortStatus = CohortStatus.DRAFT

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class CohortUpdateRequest(CohortFields):
    name: str | None = Field(None, min_length=1, max_length=100)
    programme_type: ProgrammeType | None = None
    start_date: date | None = None
    end_date: date | None = None
    graduation_threshold: int | None = Field(None, ge=1, le=100)
    status: CohortStatus | None = None


class IctTrackResponse(Schema):
    id: UUID
    name: str
    description: str | None
    lead_mentor: UserSummary | None


class CohortResponse(Schema):
    id: UUID
    name: str
    programme_type: ProgrammeType
    start_date: date
    end_date: date
    graduation_threshold: int
    status: CohortStatus
    kami_limu_month_boundaries: list[MonthBoundary] | None
    thursday_window_hours: int
    saturday_window_hours: int
    objective_windows: dict[RatingPoint, TimeWindow] | None
    extra_log_window_days: int
    track_selection_opens_at: datetime | None
    track_selection_closes_at: datetime | None
    is_imported: bool
    closed_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CohortDetailResponse(CohortResponse):
    ict_tracks: list[IctTrackResponse]
    enrollment_counts: dict[UserRole, int]


class CohortFilters(PageParams):
    status: CohortStatus | None = None
    programme_type: ProgrammeType | None = None
    search: str | None = None


class EnrollmentRequest(RequestSchema):
    """Peer mentors and ICT tracks are assigned later, not at enrolment."""

    user_id: UUID
    role: UserRole = UserRole.MENTEE


class BulkEnrollmentRequest(RequestSchema):
    enrollments: list[EnrollmentRequest] = Field(min_length=1, max_length=1000)


class EnrollmentUpdateRequest(RequestSchema):
    peer_mentor_id: UUID | None


class EnrollmentResponse(Schema):
    id: UUID
    cohort_id: UUID
    role: UserRole
    peer_mentor_id: UUID | None
    ict_track: str | None
    enrolled_at: datetime
    archived_at: datetime | None
    user: UserSummary


class BulkEnrollmentResult(Schema):
    user_id: UUID
    success: bool
    message: str | None = None
    enrollment_id: UUID | None = None


class EnrollmentFilters(PageParams):
    role: UserRole | None = None
    peer_mentor_id: UUID | None = None
    ict_track: str | None = None


class StagePoints(Schema):
    applied: Points
    general_interview: Points
    technical_interview: Points
    final_interview: Points
    offer_made: Points


class PointsConfig(Schema):
    """Points per extra-activity log, and the per-type logging targets."""

    academic: Points
    event: Points
    consultation: Points
    opportunity: StagePoints
    scholarship: StagePoints
    targets: dict[ActivityType, Annotated[int, Field(ge=0, le=1000)]]


class PointsConfigRequest(PointsConfig, RequestSchema):
    pass


QuestionText = Annotated[str, StringConstraints(min_length=1, max_length=300)]


class RatingQuestion(Schema):
    number: int = Field(ge=1, le=RATING_QUESTION_COUNT)
    group: RatingGroup
    text: str


class RatingQuestionsRequest(RequestSchema):
    """Wording for each question, in order; groups follow from the position."""

    questions: list[QuestionText] = Field(
        min_length=RATING_QUESTION_COUNT, max_length=RATING_QUESTION_COUNT
    )


class IctTrackEntry(RequestSchema):
    name: str = Field(min_length=1, max_length=100, examples=["Cloud Engineering"])
    description: str | None = None
    lead_mentor_id: UUID | None = None


class IctTracksRequest(RequestSchema):
    tracks: list[IctTrackEntry] = Field(max_length=20)

    @model_validator(mode="after")
    def check_unique(self) -> Self:
        names = [t.name for t in self.tracks]
        if len(names) != len(set(names)):
            raise ValueError("Track names must be unique")
        return self


class TrackSelectionWindowRequest(RequestSchema):
    """Set both dates to open or change the window; clear them to close it."""

    opens_at: datetime | None
    closes_at: datetime | None

    @model_validator(mode="after")
    def check_range(self) -> Self:
        if (self.opens_at is None) != (self.closes_at is None):
            raise ValueError("Set both opens_at and closes_at, or neither")
        if self.opens_at and self.closes_at and self.closes_at <= self.opens_at:
            raise ValueError("Window must close after it opens")
        return self


class TrackSelectionWindow(Schema):
    opens_at: datetime | None
    closes_at: datetime | None
    is_open: bool


class TrackSelectionResponse(Schema):
    window: TrackSelectionWindow
    ict_track: str | None


class TrackChoiceRequest(RequestSchema):
    ict_track: str = Field(min_length=1, max_length=100)


class TrackOverrideRequest(TrackChoiceRequest):
    reason: str | None = Field(None, max_length=1000)


class TrackCount(Schema):
    ict_track: str
    mentees: int


class TrackSelectionSummary(Schema):
    window: TrackSelectionWindow
    counts: list[TrackCount]
    not_selected: list[UserSummary]
