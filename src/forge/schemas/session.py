"""Programme session schemas."""

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from forge.models import (
    MentorRole,
    ResourceType,
    SessionCategory,
    SessionMode,
    SessionStatus,
    SessionType,
)
from forge.schemas.common import PageParams, RequestSchema, Schema, Title
from forge.schemas.user import UserSummary


class MentorAssignment(RequestSchema):
    user_id: UUID
    mentor_role: MentorRole = MentorRole.LEAD


class ResourceIn(RequestSchema):
    resource_type: ResourceType
    url: HttpUrl = Field(examples=["https://drive.google.com/drive/folders/abc"])
    description: str | None = Field(None, max_length=500)


class SessionFields(RequestSchema):
    description: str | None = None
    kami_limu_month: int | None = Field(
        None, ge=1, le=24, description="Derived from the cohort calendar when omitted"
    )
    track: str | None = Field(None, description="ICT track; required for ICT sessions")
    mode: SessionMode | None = None
    location: str | None = Field(None, max_length=255)
    points: int | None = Field(None, ge=0, le=1000)
    attendance_deadline: AwareDatetime | None = Field(
        None, description="Explicit attendance deadline (peer mentorship sessions)"
    )


class SessionCreateRequest(SessionFields):
    cohort_id: UUID
    title: Title
    starts_at: AwareDatetime
    duration_minutes: int = Field(ge=15, le=12 * 60)
    category: SessionCategory
    session_type: SessionType = SessionType.CORE
    mode: SessionMode = SessionMode.PHYSICAL
    status: SessionStatus = Field(
        SessionStatus.DRAFT,
        description="`draft` or `published`; publishing notifies the cohort",
    )
    mentors: list[MentorAssignment] = []
    resources: list[ResourceIn] = []

    @model_validator(mode="after")
    def check(self) -> Self:
        if self.status not in (SessionStatus.DRAFT, SessionStatus.PUBLISHED):
            raise ValueError("New sessions must be draft or published")
        if self.session_type is SessionType.ICT and not self.track:
            raise ValueError("ICT sessions require a track")
        return self


class SessionUpdateRequest(SessionFields):
    title: Title | None = None
    category: SessionCategory | None = None
    session_type: SessionType | None = None
    status: SessionStatus | None = Field(
        None,
        description="Publish (`published`) or close out (`completed`); use DELETE to cancel",
    )


class SessionRescheduleRequest(RequestSchema):
    starts_at: AwareDatetime
    duration_minutes: int | None = Field(None, ge=15, le=12 * 60)
    reason: str | None = Field(None, max_length=500)


class SessionCancelRequest(RequestSchema):
    reason: str | None = Field(None, max_length=500)


class ResourcesUpdateRequest(RequestSchema):
    resources: list[ResourceIn]


class MentorsUpdateRequest(RequestSchema):
    mentors: list[MentorAssignment]


class SessionMentorResponse(Schema):
    mentor_role: MentorRole
    user: UserSummary


class SessionResourceResponse(Schema):
    id: UUID
    resource_type: ResourceType
    url: str
    description: str | None


class SessionResponse(Schema):
    id: UUID
    cohort_id: UUID
    title: str
    description: str | None
    kami_limu_month: int
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int
    category: SessionCategory
    session_type: SessionType
    track: str | None
    mode: SessionMode
    location: str | None
    points: int
    status: SessionStatus
    attendance_deadline: datetime | None
    original_starts_at: datetime | None
    mentors: list[SessionMentorResponse]
    resources: list[SessionResourceResponse]


class AttendanceWindowSummary(Schema):
    id: UUID
    opens_at: datetime
    closes_at: datetime
    is_active: bool


class SessionDetailResponse(SessionResponse):
    reschedule_history: list[dict[str, Any]] | None
    attendance_window: AttendanceWindowSummary | None


class SessionFilters(PageParams):
    cohort_id: UUID | None = None
    track: str | None = None
    kami_limu_month: int | None = None
    status: SessionStatus | None = None
    category: SessionCategory | None = None
    session_type: SessionType | None = None
    starts_after: datetime | None = None
    starts_before: datetime | None = None


class CalendarMonth(Schema):
    month: int
    name: str | None
    sessions: list[SessionResponse]
