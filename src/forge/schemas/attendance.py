"""Attendance engine schemas."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from forge.models import (
    RATING_QUESTION_COUNT,
    AttendanceSource,
    AttendanceStatus,
    OverrideRequestStatus,
    SessionCategory,
    SessionStatus,
    SessionType,
)
from forge.schemas.common import PageParams, Rating, RequestSchema, Schema

SelfReportedStatus = Literal[AttendanceStatus.PRESENT, AttendanceStatus.ABSENT]
Ratings = Annotated[
    list[Rating],
    Field(
        min_length=RATING_QUESTION_COUNT,
        max_length=RATING_QUESTION_COUNT,
        description="Answers (1-5) to the cohort's nine rating questions, in order",
    ),
]
Feedback = Annotated[str, Field(min_length=1, max_length=5000)]


def check_submission(
    status: AttendanceStatus, ratings: list[int] | None, feedback: str | None
) -> None:
    """Present needs all nine ratings and feedback; absent takes no ratings."""
    if status is AttendanceStatus.PRESENT and (ratings is None or not feedback):
        raise ValueError("Present submissions need all nine ratings and feedback")
    if status is AttendanceStatus.ABSENT and ratings is not None:
        raise ValueError("Ratings can only be given for sessions you attended")


class AttendanceSubmissionRequest(RequestSchema):
    session_id: UUID
    status: SelfReportedStatus
    ratings: Ratings | None = None
    feedback: Feedback | None = None

    @model_validator(mode="after")
    def check(self) -> Self:
        check_submission(self.status, self.ratings, self.feedback)
        return self


class AttendanceUpdateRequest(RequestSchema):
    status: SelfReportedStatus | None = None
    ratings: Ratings | None = None
    feedback: Feedback | None = None


class AttendanceStatusUpdateRequest(RequestSchema):
    status: AttendanceStatus = Field(description="Manager override, e.g. `excused`")
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
    status: SessionStatus


class AttendanceResponse(Schema):
    id: UUID
    mentee_id: UUID
    session_id: UUID
    status: AttendanceStatus
    source: AttendanceSource | None
    ratings: list[int | None] | None
    feedback: str | None
    submitted_at: datetime | None
    updated_at: datetime
    session: SessionBrief


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
    requested_closes_at: AwareDatetime | None = Field(
        None, description="The new deadline you are asking for"
    )


class OverrideReviewRequest(RequestSchema):
    reason: str | None = Field(None, max_length=2000)
    new_closes_at: AwareDatetime | None = Field(
        None,
        description="Approval only: the participant's new deadline. Defaults to the "
        "deadline they asked for, else now + OVERRIDE_EXTENSION_HOURS",
    )


class OverrideRequestResponse(Schema):
    id: UUID
    mentee_id: UUID
    session_id: UUID
    reason: str
    requested_closes_at: datetime | None
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
