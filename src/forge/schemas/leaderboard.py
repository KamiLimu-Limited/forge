"""Leaderboard schemas."""

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from forge.models import LeaderboardKind
from forge.schemas.common import Schema


class LeaderboardDimension(enum.StrEnum):
    CORE_ATTENDANCE = "core_attendance"
    ACADEMIC = "academic"
    EVENTS = "events"
    APPLICATIONS = "applications"
    CONSULTATIONS = "consultations"


class PeerMentorDimension(enum.StrEnum):
    SESSIONS_ATTENDED = "sessions_attended"
    EXTRA_SESSIONS = "extra_sessions"
    CORE_RATE = "core_rate"
    OVERALL_RATE = "overall_rate"


class LeaderboardRow(Schema):
    rank: int
    mentee_id: UUID
    display_name: str
    is_me: bool
    total_points: int
    core_attendance: float
    academic: int
    events: int
    applications: int
    consultations: int


class LeaderboardResponse(Schema):
    cohort_id: UUID
    generated_at: datetime
    entries: list[LeaderboardRow]


class DimensionEntry(Schema):
    rank: int
    mentee_id: UUID
    display_name: str
    is_me: bool
    value: float


class DimensionRankingResponse(Schema):
    cohort_id: UUID
    dimension: LeaderboardDimension
    entries: list[DimensionEntry]


class PeerMentorRow(Schema):
    rank: int
    peer_mentor_id: UUID
    display_name: str
    is_me: bool
    sessions_attended: int
    extra_sessions: int
    core_rate: float
    overall_rate: float


class PeerMentorLeaderboardResponse(Schema):
    cohort_id: UUID
    ranked_by: PeerMentorDimension
    generated_at: datetime
    entries: list[PeerMentorRow]


class LeaderboardSnapshotResponse(Schema):
    id: UUID
    cohort_id: UUID
    kind: LeaderboardKind
    taken_at: datetime
    taken_by: UUID | None
    rows: list[dict[str, Any]]
