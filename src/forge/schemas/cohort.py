"""Cohort and enrollment schemas."""

from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from forge.core.config import settings
from forge.models import CohortStatus, ProgrammeType, RatingPoint, UserRole
from forge.schemas.common import PageParams, RequestSchema, Schema
from forge.schemas.user import UserSummary


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


class RatingWindow(Schema):
    opens_at: datetime
    closes_at: datetime

    @model_validator(mode="after")
    def check_range(self) -> Self:
        if self.closes_at <= self.opens_at:
            raise ValueError("Window must close after it opens")
        return self


class CohortFields(RequestSchema):
    kami_limu_month_boundaries: list[MonthBoundary] | None = None
    ict_tracks_offered: list[str] | None = Field(
        None, examples=[["web", "data", "mobile"]]
    )
    skill_names: list[str] | None = Field(None, min_length=1, max_length=10)
    skill_rating_windows: dict[RatingPoint, RatingWindow] | None = None
    leaderboard_anonymous: bool | None = None
    peer_mentorship_deadline_hours: int | None = Field(None, ge=1, le=24 * 30)


class CohortCreateRequest(CohortFields):
    name: str = Field(min_length=1, max_length=100, examples=["Cohort 11"])
    programme_type: ProgrammeType
    start_date: date
    end_date: date
    graduation_threshold: int = Field(
        settings.DEFAULT_GRADUATION_THRESHOLD, ge=1, le=100
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


class CohortResponse(Schema):
    id: UUID
    name: str
    programme_type: ProgrammeType
    start_date: date
    end_date: date
    graduation_threshold: int
    status: CohortStatus
    kami_limu_month_boundaries: list[MonthBoundary] | None
    ict_tracks_offered: list[str] | None
    skill_names: list[str] | None
    skill_rating_windows: dict[RatingPoint, RatingWindow] | None
    leaderboard_anonymous: bool
    peer_mentorship_deadline_hours: int | None
    created_at: datetime
    updated_at: datetime


class CohortDetailResponse(CohortResponse):
    enrollment_counts: dict[UserRole, int]


class CohortFilters(PageParams):
    status: CohortStatus | None = None
    programme_type: ProgrammeType | None = None
    search: str | None = None


class EnrollmentRequest(RequestSchema):
    user_id: UUID
    role: UserRole = UserRole.MENTEE
    peer_mentor_id: UUID | None = None
    ict_track: str | None = None


class BulkEnrollmentRequest(RequestSchema):
    enrollments: list[EnrollmentRequest] = Field(min_length=1, max_length=1000)


class EnrollmentUpdateRequest(RequestSchema):
    peer_mentor_id: UUID | None = None
    ict_track: str | None = None


class EnrollmentResponse(Schema):
    id: UUID
    cohort_id: UUID
    role: UserRole
    peer_mentor_id: UUID | None
    ict_track: str | None
    enrolled_at: datetime
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
