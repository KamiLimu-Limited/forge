"""Extra activity schemas: one typed payload per activity kind."""

import datetime as dt
import enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from forge.models import ActivityStatus, ActivityType
from forge.schemas.common import PageParams, RequestSchema, Schema, Title


class EventRole(enum.StrEnum):
    ATTENDEE = "attendee"
    SPEAKER = "speaker"
    VOLUNTEER = "volunteer"
    ORGANIZER = "organizer"
    PANELIST = "panelist"


class EventMode(enum.StrEnum):
    PHYSICAL = "physical"
    VIRTUAL = "virtual"
    HYBRID = "hybrid"


class OpportunityOutcome(enum.StrEnum):
    APPLIED = "applied"
    SHORTLISTED = "shortlisted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class AcademicDetails(RequestSchema):
    course_name: str = Field(min_length=1, max_length=200)
    related_session_ids: list[UUID] = []
    kami_limu_pillar: str | None = Field(None, max_length=100)


class EventDetails(RequestSchema):
    event_role: EventRole
    mode: EventMode
    organizer: str | None = Field(None, max_length=200)
    learnings: str = Field(min_length=1, max_length=5000)


class OpportunityDetails(RequestSchema):
    organization: str = Field(min_length=1, max_length=200)
    application_date: dt.date
    outcome_status: OpportunityOutcome = OpportunityOutcome.APPLIED


class ConsultationDetails(RequestSchema):
    mentor_id: UUID | None = Field(
        None, description="Forge user id of the mentor, if they have an account"
    )
    mentor_name: str | None = Field(None, max_length=200)
    consultation_date: dt.date
    outcome: str = Field(min_length=1, max_length=5000)


DETAILS_MODELS: dict[ActivityType, type[RequestSchema]] = {
    ActivityType.ACADEMIC: AcademicDetails,
    ActivityType.EVENT: EventDetails,
    ActivityType.OPPORTUNITY: OpportunityDetails,
    ActivityType.CONSULTATION: ConsultationDetails,
}


class ActivityBase(RequestSchema):
    cohort_id: UUID | None = Field(
        None, description="Defaults to your most recent cohort"
    )
    title: Title
    description: str | None = Field(None, max_length=5000)
    date: dt.date


class AcademicActivityRequest(ActivityBase):
    details: AcademicDetails


class ExternalEventRequest(ActivityBase):
    details: EventDetails


class OpportunityApplicationRequest(ActivityBase):
    details: OpportunityDetails


class ConsultationSessionRequest(ActivityBase):
    details: ConsultationDetails


ActivityRequest = (
    AcademicActivityRequest
    | ExternalEventRequest
    | OpportunityApplicationRequest
    | ConsultationSessionRequest
)


class ActivityUpdateRequest(RequestSchema):
    title: Title | None = None
    description: str | None = Field(None, max_length=5000)
    date: dt.date | None = None
    details: dict[str, Any] | None = Field(
        None,
        description="Partial details; merged and re-validated for the activity's type",
    )


class ActivityReviewRequest(RequestSchema):
    points_awarded: int | None = Field(
        None,
        ge=0,
        le=1000,
        description="Approval only; defaults to the configured points for the type",
    )
    reason: str | None = Field(None, max_length=2000)


class ActivityFilters(PageParams):
    cohort_id: UUID | None = None
    type: ActivityType | None = None
    status: ActivityStatus | None = None
    mentee_id: UUID | None = None


class _ActivityResponse(Schema):
    id: UUID
    mentee_id: UUID
    cohort_id: UUID
    title: str
    description: str | None
    date: dt.date
    status: ActivityStatus
    points_awarded: int
    reviewed_by: UUID | None
    reviewed_at: dt.datetime | None
    review_reason: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


class AcademicActivityResponse(_ActivityResponse):
    type: Literal[ActivityType.ACADEMIC]
    details: AcademicDetails


class ExternalEventResponse(_ActivityResponse):
    type: Literal[ActivityType.EVENT]
    details: EventDetails


class OpportunityApplicationResponse(_ActivityResponse):
    type: Literal[ActivityType.OPPORTUNITY]
    details: OpportunityDetails


class ConsultationSessionResponse(_ActivityResponse):
    type: Literal[ActivityType.CONSULTATION]
    details: ConsultationDetails


ExtraActivityResponse = Annotated[
    AcademicActivityResponse
    | ExternalEventResponse
    | OpportunityApplicationResponse
    | ConsultationSessionResponse,
    Field(discriminator="type"),
]
activity_adapter: TypeAdapter[ExtraActivityResponse] = TypeAdapter(
    ExtraActivityResponse
)
