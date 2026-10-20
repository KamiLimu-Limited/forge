"""Peer mentorship notes, tasks and skill-rating schemas."""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from forge.models import RatingPoint, SubmissionStatus
from forge.schemas.common import PageParams, Rating, RequestSchema, Schema, Title
from forge.schemas.user import UserSummary


class NoteCreateRequest(RequestSchema):
    mentee_id: UUID
    note_text: str = Field(min_length=1, max_length=10000)


class PeerMentorNoteResponse(Schema):
    id: UUID
    peer_mentor_id: UUID
    mentee_id: UUID
    note_text: str
    created_at: datetime
    updated_at: datetime


class ProgressNoteCreateRequest(RequestSchema):
    mentee_id: UUID
    session_id: UUID | None = None
    progress_note: str = Field(min_length=1, max_length=10000)


class IctProgressNoteResponse(Schema):
    id: UUID
    ict_peer_mentor_id: UUID
    mentee_id: UUID
    session_id: UUID | None
    progress_note: str
    created_at: datetime


class TaskFields(RequestSchema):
    description: str | None = Field(None, max_length=5000)
    resource_link: HttpUrl | None = None


class PeerMentorTaskRequest(TaskFields):
    title: Title
    launch_date: AwareDatetime
    deadline_date: AwareDatetime
    cohort_id: UUID | None = Field(
        None, description="Defaults to your most recent cohort"
    )

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        if self.deadline_date <= self.launch_date:
            raise ValueError("deadline_date must be after launch_date")
        return self


class PeerMentorTaskUpdateRequest(TaskFields):
    title: Title | None = None
    launch_date: AwareDatetime | None = None
    deadline_date: AwareDatetime | None = None


class PeerMentorTaskResponse(Schema):
    id: UUID
    peer_mentor_id: UUID
    cohort_id: UUID
    title: str
    description: str | None
    launch_date: datetime
    deadline_date: datetime
    resource_link: str | None
    created_at: datetime


class TaskFilters(PageParams):
    cohort_id: UUID | None = None
    peer_mentor_id: UUID | None = None


class TaskSubmissionRequest(RequestSchema):
    notes: str | None = Field(None, max_length=5000)


class TaskSubmissionResponse(Schema):
    id: UUID
    task_id: UUID
    mentee_id: UUID
    submission_status: SubmissionStatus
    submitted_at: datetime | None
    notes: str | None


class TaskSubmissionStatusEntry(Schema):
    mentee: UserSummary
    submission_status: SubmissionStatus
    submitted_at: datetime | None
    notes: str | None


class SkillRatingRequest(RequestSchema):
    cohort_id: UUID | None = Field(
        None, description="Defaults to your most recent cohort"
    )
    rating_point: RatingPoint
    ratings: dict[str, Rating] = Field(
        examples=[{"communication": 3, "leadership": 2, "technical": 4}],
        description="A 1–5 rating for every skill configured on the cohort",
    )


class SkillRatingResponse(Schema):
    id: UUID
    mentee_id: UUID
    cohort_id: UUID
    rating_point: RatingPoint
    ratings: dict[str, int]
    rated_at: datetime


class SkillRatingWindowStatus(Schema):
    rating_point: RatingPoint
    opens_at: datetime | None
    closes_at: datetime | None
    is_open: bool
    submitted: bool


class SkillProgressResponse(Schema):
    mentee_id: UUID
    cohort_id: UUID
    skill_names: list[str]
    ratings: list[SkillRatingResponse]
    change: dict[str, int] = Field(description="Latest minus earliest rating per skill")
