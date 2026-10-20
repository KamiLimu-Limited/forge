"""Leaderboard and competition schemas."""

import enum
from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from forge.models import CompetitionStatus, CompetitionType, EntryStatus
from forge.schemas.common import PageParams, RequestSchema, Schema, Title


class LeaderboardDimension(enum.StrEnum):
    CORE_ATTENDANCE = "core_attendance"
    GRADUATION_RATE = "graduation_rate"
    ACADEMIC = "academic"
    EVENTS = "events"
    OPPORTUNITIES = "opportunities"
    CONSULTATIONS = "consultations"


class LeaderboardRow(Schema):
    rank: int
    mentee_id: UUID | None = Field(
        description="Hidden for other mentees when the leaderboard is anonymous"
    )
    display_name: str
    is_me: bool
    total_points: int
    core_attendance: float
    graduation_rate: float
    academic: int
    events: int
    opportunities: int
    consultations: int


class LeaderboardResponse(Schema):
    cohort_id: UUID
    anonymous: bool
    generated_at: datetime
    entries: list[LeaderboardRow]


class DimensionEntry(Schema):
    rank: int
    mentee_id: UUID | None
    display_name: str
    is_me: bool
    value: float


class DimensionRankingResponse(Schema):
    cohort_id: UUID
    dimension: LeaderboardDimension
    anonymous: bool
    entries: list[DimensionEntry]


class LeaderboardSettings(RequestSchema):
    leaderboard_anonymous: bool


class CompetitionCreateRequest(RequestSchema):
    cohort_id: UUID
    name: Title
    description: str | None = Field(None, max_length=5000)
    competition_type: CompetitionType
    start_date: date
    end_date: date
    status: CompetitionStatus = CompetitionStatus.UPCOMING

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class CompetitionUpdateRequest(RequestSchema):
    name: Title | None = None
    description: str | None = Field(None, max_length=5000)
    start_date: date | None = None
    end_date: date | None = None
    status: CompetitionStatus | None = None


class RoundCreateRequest(RequestSchema):
    round_number: int = Field(ge=1)
    round_name: Title
    round_date: date | None = None
    status: CompetitionStatus = CompetitionStatus.UPCOMING


class RoundUpdateRequest(RequestSchema):
    round_name: Title | None = None
    round_date: date | None = None
    status: CompetitionStatus | None = None


class RoundResponse(Schema):
    id: UUID
    competition_id: UUID
    round_number: int
    round_name: str
    round_date: date | None
    status: CompetitionStatus


class CompetitionResponse(Schema):
    id: UUID
    cohort_id: UUID
    name: str
    description: str | None
    competition_type: CompetitionType
    start_date: date
    end_date: date
    status: CompetitionStatus
    rounds: list[RoundResponse]


class CompetitionFilters(PageParams):
    cohort_id: UUID | None = None
    competition_type: CompetitionType | None = None
    status: CompetitionStatus | None = None


class EntryCreate(RequestSchema):
    mentee_id: UUID | None = Field(None, description="Individual entry")
    team_name: str | None = Field(None, max_length=200, description="Team entry")
    team_member_ids: list[UUID] | None = None
    round_id: UUID | None = None

    @model_validator(mode="after")
    def individual_or_team(self) -> Self:
        if (self.mentee_id is None) == (self.team_name is None):
            raise ValueError("Provide either mentee_id or team_name")
        if self.team_name and not self.team_member_ids:
            raise ValueError("Team entries need team_member_ids")
        return self


class EntriesCreateRequest(RequestSchema):
    entries: list[EntryCreate] = Field(min_length=1, max_length=500)


class EntryUpdateRequest(RequestSchema):
    round_id: UUID | None = None
    status: EntryStatus | None = None
    result: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=5000)


class EntryResponse(Schema):
    id: UUID
    competition_id: UUID
    round_id: UUID | None
    mentee_id: UUID | None
    team_name: str | None
    team_member_ids: list[UUID] | None
    status: EntryStatus
    result: str | None
    notes: str | None
    updated_at: datetime


class CompetitionStatusEntry(Schema):
    competition_id: UUID
    competition_name: str
    competition_type: CompetitionType
    entry: EntryResponse
    round_name: str | None
