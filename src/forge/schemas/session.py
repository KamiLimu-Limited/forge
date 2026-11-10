"""Programme session schemas."""

from datetime import datetime, timedelta
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

# Calendar sessions are short; peer mentorship sessions (tasks) run for weeks.
MAX_SESSION_LENGTH = timedelta(hours=12)
MAX_TASK_LENGTH = timedelta(days=60)


def check_times(
    starts_at: datetime, ends_at: datetime, category: SessionCategory
) -> None:
    if ends_at <= starts_at:
        raise ValueError("ends_at must be after starts_at")
    limit = (
        MAX_TASK_LENGTH
        if category is SessionCategory.PEER_MENTORSHIP
        else MAX_SESSION_LENGTH
    )
    if ends_at - starts_at > limit:
        raise ValueError(f"A {category.value} session can last at most {limit}")


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
    track: str | None = Field(
        None, description="ICT track for ICT sessions; core sessions have none"
    )
    mode: SessionMode | None = None
    location: str | None = Field(
        None, max_length=255, description="Venue, or meeting link when virtual"
    )
    points: int | None = Field(None, ge=0, le=1000)


class SessionCreateRequest(SessionFields):
    cohort_id: UUID
    title: Title
    starts_at: AwareDatetime
    ends_at: AwareDatetime = Field(
        description="End time; for peer mentorship sessions, the task deadline"
    )
    category: SessionCategory
    session_type: SessionType = SessionType.THEORY
    mode: SessionMode = SessionMode.PHYSICAL
    status: SessionStatus = Field(
        SessionStatus.DRAFT, description="`draft` or `published`"
    )
    mentors: list[MentorAssignment] = []
    resources: list[ResourceIn] = []

    @model_validator(mode="after")
    def check(self) -> Self:
        if self.status not in (SessionStatus.DRAFT, SessionStatus.PUBLISHED):
            raise ValueError("New sessions must be draft or published")
        check_times(self.starts_at, self.ends_at, self.category)
        return self


class SessionUpdateRequest(SessionFields):
    title: Title | None = None
    category: SessionCategory | None = None
    session_type: SessionType | None = None
    status: SessionStatus | None = Field(
        None,
        description="Publish (`published`) or close out (`completed`); use DELETE "
        "to cancel and `/reschedule` to move it",
    )


class SessionRescheduleRequest(RequestSchema):
    starts_at: AwareDatetime
    ends_at: AwareDatetime | None = Field(
        None, description="Defaults to keeping the session's length"
    )
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
    category: SessionCategory
    session_type: SessionType
    track: str | None
    mode: SessionMode
    location: str | None
    points: int
    status: SessionStatus
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


class InProgressSession(Schema):
    session: SessionResponse
    closes_at: datetime = Field(description="When the caller's window closes")
    submitted: bool


class SessionNoteRequest(RequestSchema):
    body: str = Field(max_length=20_000)


class SessionNoteResponse(Schema):
    session_id: UUID
    body: str
    updated_at: datetime
