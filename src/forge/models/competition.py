"""Competition models."""

import enum
import uuid
from datetime import date

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from forge.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum


class CompetitionType(enum.StrEnum):
    INNOVATION = "innovation"
    PUBLIC_SPEAKING = "public_speaking"
    SCHOLARSHIP = "scholarship"
    PROFESSIONAL = "professional"


class CompetitionStatus(enum.StrEnum):
    UPCOMING = "upcoming"
    ONGOING = "ongoing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EntryStatus(enum.StrEnum):
    REGISTERED = "registered"
    ADVANCED = "advanced"
    ELIMINATED = "eliminated"
    WITHDRAWN = "withdrawn"
    WINNER = "winner"


class Competition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "competitions"

    cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    competition_type: Mapped[CompetitionType] = mapped_column(pg_enum(CompetitionType))
    start_date: Mapped[date]
    end_date: Mapped[date]
    status: Mapped[CompetitionStatus] = mapped_column(
        pg_enum(CompetitionStatus), default=CompetitionStatus.UPCOMING
    )

    rounds: Mapped[list["CompetitionRound"]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        passive_deletes=True,
        order_by="CompetitionRound.round_number",
    )


class CompetitionRound(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "competition_rounds"
    __table_args__ = (UniqueConstraint("competition_id", "round_number"),)

    competition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), index=True
    )
    round_number: Mapped[int]
    round_name: Mapped[str] = mapped_column(String(200))
    round_date: Mapped[date | None]
    status: Mapped[CompetitionStatus] = mapped_column(
        pg_enum(CompetitionStatus), default=CompetitionStatus.UPCOMING
    )


class CompetitionEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "competition_entries"

    competition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), index=True
    )
    round_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("competition_rounds.id", ondelete="SET NULL")
    )
    mentee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Team entries list member user ids in ``team_member_ids``.
    team_name: Mapped[str | None] = mapped_column(String(200))
    team_member_ids: Mapped[list[str] | None]
    status: Mapped[EntryStatus] = mapped_column(
        pg_enum(EntryStatus), default=EntryStatus.REGISTERED
    )
    result: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
