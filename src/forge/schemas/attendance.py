"""Attendance engine schemas."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from forge.models import (
    AttendanceStatus,
    OverrideRequestStatus,
    SessionCategory,
    SessionType,
)
from forge.schemas.common import PageParams, Rating, RequestSchema, Schema

SelfReportedStatus = Literal[AttendanceStatus.ATTENDED, AttendanceStatus.NOT_ATTENDED]


class AttendanceFields(RequestSchema):
    quality_rating: Rating | None = None
    usefulness_rating: Rating | None = None
    understanding_score: Rating | None = None
    academic_application_score: Rating | None = None
    career_application_score: Rating | None = None
    feedback: str | None = Field(None, max_length=5000)
    personal_notes: str | None = Field(
        None, max_length=5000, description="Private to you"
    )

    def has_ratings(self) -> bool:
        return any(
            getattr(self, f) is not None
            for f in (
                "quality_rating",
                "usefulness_rating",
                "understanding_score",
                "academic_application_score",
                "career_application_score",
            )
        )


class AttendanceSubmissionRequest(AttendanceFields):
    session_id: UUID
    status: SelfReportedStatus = AttendanceStatus.ATTENDED

    @model_validator(mode="after")
    def ratings_only_when_attended(self) -> Self:
        if self.status is AttendanceStatus.NOT_ATTENDED and self.has_ratings():
            raise ValueError("Ratings can only be given for sessions you attended")
        return self


class AttendanceUpdateRequest(AttendanceFields):
    status: SelfReportedStatus | None = None


class AttendanceStatusUpdateRequest(RequestSchema):
    status: AttendanceStatus = Field(description="Committee override, e.g. `excused`")
    reason: str | None = Field(None, max_length=1000)


class SessionBrief(Schema):
    id: UUID
    cohort_id: UUID
    title: str
    starts_at: datetime
    kami_limu_month: int
    category: SessionCategory
    session_type: SessionType
    track: str | None
    points: int


class AttendanceResponse(Schema):
    id: UUID
    mentee_id: UUID
    session_id: UUID
    status: AttendanceStatus
    quality_rating: int | None
    usefulness_rating: int | None
    understanding_score: int | None
    academic_application_score: int | None
    career_application_score: int | None
    feedback: str | None
    submitted_at: datetime | None
    updated_at: datetime
    session: SessionBrief


class MyAttendanceResponse(AttendanceResponse):
    personal_notes: str | None


class AttendanceFilters(PageParams):
    cohort_id: UUID | None = None
    session_id: UUID | None = None
    mentee_id: UUID | None = None
    status: AttendanceStatus | None = None
    kami_limu_month: int | None = None
    track: str | None = None


class WindowStatusResponse(Schema):
    session_id: UUID
    window_id: UUID
    opens_at: datetime
    closes_at: datetime
    effective_closes_at: datetime
    is_active: bool
    is_open: bool
    has_override: bool
    record_id: UUID | None
    record_status: AttendanceStatus | None


class AttendanceWindowResponse(Schema):
    id: UUID
    session_id: UUID
    opens_at: datetime
    closes_at: datetime
    is_active: bool
    closed_at: datetime | None


class OverrideRequestCreate(RequestSchema):
    session_id: UUID
    reason: str = Field(min_length=5, max_length=2000)


class OverrideReviewRequest(RequestSchema):
    reason: str | None = Field(None, max_length=2000)
    new_closes_at: AwareDatetime | None = Field(
        None, description="Approval only; defaults to now + OVERRIDE_EXTENSION_HOURS"
    )


class OverrideRequestResponse(Schema):
    id: UUID
    mentee_id: UUID
    session_id: UUID
    reason: str
    status: OverrideRequestStatus
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_reason: str | None
    created_at: datetime
    session: SessionBrief


class OverrideFilters(PageParams):
    status: OverrideRequestStatus | None = None
    cohort_id: UUID | None = None
    session_id: UUID | None = None
