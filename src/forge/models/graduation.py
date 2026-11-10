"""Leaderboard snapshots and the graduation record."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from forge.db.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    pg_enum,
)
from forge.models.user import User


class LeaderboardKind(enum.StrEnum):
    MENTEE = "mentee"
    PEER_MENTOR = "peer_mentor"


class LeaderboardSnapshot(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "leaderboard_snapshots"

    cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[LeaderboardKind] = mapped_column(pg_enum(LeaderboardKind))
    taken_at: Mapped[datetime] = mapped_column(server_default=func.now())
    taken_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    rows: Mapped[list[dict[str, Any]]]


class CohortGraduation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A cohort's graduation: the latest preview, then the confirmed record."""

    __tablename__ = "cohort_graduations"

    cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE"), unique=True
    )
    threshold: Mapped[int]
    preview: Mapped[dict[str, Any] | None]
    preview_computed_at: Mapped[datetime | None]
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None]
    # User ids in the order the graduation sequence reveals them.
    reveal_order: Mapped[list[str] | None]

    results: Mapped[list["GraduationResult"]] = relationship(
        back_populates="graduation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_at is not None


class GraduationResult(Base, UUIDPrimaryKeyMixin):
    """A mentee's frozen final figures."""

    __tablename__ = "graduation_results"
    __table_args__ = (UniqueConstraint("graduation_id", "user_id"),)

    graduation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cohort_graduations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    core_rate: Mapped[float]
    overall_rate: Mapped[float]
    core_points: Mapped[int]
    extra_points: Mapped[int]
    total_points: Mapped[int]
    graduated: Mapped[bool]

    graduation: Mapped[CohortGraduation] = relationship(back_populates="results")
    user: Mapped[User] = relationship(lazy="joined")


class GraduationCorrection(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "graduation_corrections"

    result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graduation_results.id", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String(50))
    old_value: Mapped[str] = mapped_column(String(50))
    new_value: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(Text)
    corrected_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
