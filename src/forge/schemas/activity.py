"""Extra activity and consultant schemas: one typed payload per log type."""

import datetime as dt
import enum
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import EmailStr, Field, model_validator

from forge.models import ActivityStatus, ActivityType
from forge.models.activity import (
    ConsultationStatus,
    EventRole,
    FinalOutcome,
    OpportunityStage,
)
from forge.schemas.common import PageParams, RequestSchema, Schema, Title

LongText = Annotated[str, Field(min_length=1, max_length=5000)]
OFFER_OUTCOMES = (FinalOutcome.OFFER_ACCEPTED, FinalOutcome.OFFER_REJECTED)


class EventMode(enum.StrEnum):
    IN_PERSON = "in_person"
    VIRTUAL = "virtual"


class AcademicDetails(RequestSchema):
    kami_limu_pillar: str = Field(
        min_length=1, max_length=100, description="The programme track it relates to"
    )
    related_session_ids: list[UUID] = Field(
        min_length=1, description="Sessions whose lessons you applied"
    )
    how_applied: LongText


class EventDetails(RequestSchema):
    event_role: EventRole
    mode: EventMode
    learnings: LongText = Field(
        description="What you learned and how it relates to the programme"
    )


class ApplicationDetails(RequestSchema):
    """A job, scholarship or fellowship application."""

    organisation: str = Field(min_length=1, max_length=200)
    date_applied: dt.date
    related_session_ids: list[UUID] = []
    how_applied: LongText = Field(description="How you applied KamiLimu lessons")
    stage: OpportunityStage = OpportunityStage.APPLIED
    final_outcome: FinalOutcome = FinalOutcome.WAITING

    @model_validator(mode="after")
    def check_outcome(self) -> Self:
        if self.final_outcome in OFFER_OUTCOMES and (
            self.stage is not OpportunityStage.OFFER_MADE
        ):
            raise ValueError("An offer outcome needs stage `offer_made`")
        return self


class ConsultationDetails(RequestSchema):
    consultation_type: str = Field(
        min_length=1, max_length=100, examples=["Career guidance"]
    )
    summary: LongText
    support_received: str | None = Field(None, max_length=5000)
    status: ConsultationStatus = ConsultationStatus.COMPLETED


DETAILS_MODELS: dict[ActivityType, type[RequestSchema]] = {
    ActivityType.ACADEMIC: AcademicDetails,
    ActivityType.EVENT: EventDetails,
    ActivityType.OPPORTUNITY: ApplicationDetails,
    ActivityType.SCHOLARSHIP: ApplicationDetails,
    ActivityType.CONSULTATION: ConsultationDetails,
}


class ActivityBase(RequestSchema):
    cohort_id: UUID | None = Field(
        None, description="Defaults to your most recent cohort"
    )
    title: Title = Field(description="Course, event, opportunity or consultation name")
    description: str | None = Field(None, max_length=5000)
    date: dt.date


class AcademicActivityRequest(ActivityBase):
    details: AcademicDetails


class ExternalEventRequest(ActivityBase):
    details: EventDetails


class OpportunityApplicationRequest(ActivityBase):
    details: ApplicationDetails


class ScholarshipApplicationRequest(ActivityBase):
    details: ApplicationDetails


class ConsultationSessionRequest(ActivityBase):
    consultant_id: UUID = Field(description="A consultant from `/consultants`")
    details: ConsultationDetails


ActivityRequest = (
    AcademicActivityRequest
    | ExternalEventRequest
    | OpportunityApplicationRequest
    | ScholarshipApplicationRequest
    | ConsultationSessionRequest
)


class ActivityUpdateRequest(RequestSchema):
    title: Title | None = None
    description: str | None = Field(None, max_length=5000)
    date: dt.date | None = None
    consultant_id: UUID | None = None
    details: dict[str, Any] | None = Field(
        None,
        description="Partial details, e.g. a new `stage` or `final_outcome`; merged "
        "and re-validated for the activity's type",
    )


class ActivityReversalRequest(RequestSchema):
    reason: str = Field(min_length=3, max_length=2000)


class ActivityFilters(PageParams):
    cohort_id: UUID | None = None
    type: ActivityType | None = None
    status: ActivityStatus | None = None
    mentee_id: UUID | None = None


class ExtraActivityResponse(Schema):
    id: UUID
    type: ActivityType
    mentee_id: UUID
    cohort_id: UUID
    title: str
    description: str | None
    date: dt.date
    status: ActivityStatus
    points_awarded: int
    consultant_id: UUID | None
    details: dict[str, Any] = Field(
        description="The type-specific fields submitted for this log"
    )
    reversed_by: UUID | None
    reversed_at: dt.datetime | None
    reversal_reason: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


class TypeProgress(Schema):
    type: ActivityType
    logged: int
    target: int
    points: int


class ActivityProgressResponse(Schema):
    cohort_id: UUID
    types: list[TypeProgress]


class ConsultantRequest(RequestSchema):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    organisation: str | None = Field(None, max_length=200)
    expertise: str | None = Field(None, max_length=2000)


class ConsultantUpdateRequest(RequestSchema):
    name: str | None = Field(None, min_length=1, max_length=200)
    email: EmailStr | None = None
    organisation: str | None = Field(None, max_length=200)
    expertise: str | None = Field(None, max_length=2000)


class ConsultantResponse(Schema):
    id: UUID
    name: str
    email: str | None
    organisation: str | None
    expertise: str | None
    is_active: bool
