"""Graduation, graduation card and alumni history schemas."""

from datetime import date, datetime
from uuid import UUID

from pydantic import Field

from forge.models import UserRole
from forge.schemas.common import RequestSchema, Schema
from forge.schemas.user import CohortBrief, UserSummary


class GraduationEntry(Schema):
    mentee: UserSummary
    core_rate: float
    overall_rate: float
    core_points: int
    extra_points: int
    total_points: int
    graduated: bool


class GraduationPreview(Schema):
    cohort_id: UUID
    threshold: int
    computed_at: datetime
    graduates: list[GraduationEntry]
    non_graduates: list[GraduationEntry]


class GraduationAvailability(Schema):
    available: bool
    reasons: list[str] = Field(description="Why the cohort cannot graduate yet")


class GraduationRecord(Schema):
    cohort_id: UUID
    threshold: int
    confirmed_at: datetime
    confirmed_by: UUID | None
    graduates: list[GraduationEntry]
    non_graduates: list[GraduationEntry]


class ProgrammeStats(Schema):
    mentees: int
    graduates: int
    sessions_held: int
    points_distributed: int
    average_core_rate: float


class MentorServed(Schema):
    user: UserSummary
    roles: list[str]


class GraduationSequence(Schema):
    cohort_id: UUID
    cohort_name: str
    graduates: list[GraduationEntry] = Field(description="In reveal order")
    stats: ProgrammeStats
    mentors: list[MentorServed]


class SequenceSettingsRequest(RequestSchema):
    reveal_order: list[UUID] = Field(
        description="Every graduate's user id, in the order they are revealed"
    )


class GraduationCorrectionRequest(RequestSchema):
    user_id: UUID
    graduated: bool
    reason: str = Field(min_length=3, max_length=2000)


class GraduationCorrectionResponse(Schema):
    id: UUID
    result_id: UUID
    field: str
    old_value: str
    new_value: str
    reason: str
    corrected_by: UUID | None
    created_at: datetime


class GraduationPanel(Schema):
    cohort_id: UUID
    preview: GraduationPreview
    confirmed: bool
    confirmed_at: datetime | None
    availability: GraduationAvailability


class GraduationCard(Schema):
    cohort: CohortBrief
    graduated_on: date
    core_rate: float
    overall_rate: float
    total_points: int


class AlumniCohort(Schema):
    cohort: CohortBrief
    roles: list[UserRole]
    result: GraduationEntry | None


class ConfirmPasswordRequest(RequestSchema):
    password: str


class ConfirmationResponse(Schema):
    confirmation_token: str = Field(
        description="Send as `X-Confirmation-Token` with the sensitive request"
    )
    expires_at: datetime
