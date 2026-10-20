"""Cohort and enrollment models."""

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from forge.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from forge.models.user import User, UserRole


class CohortStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"


class ProgrammeType(enum.StrEnum):
    UNDERGRADUATE = "undergraduate"
    POSTGRADUATE = "postgraduate"


class Cohort(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "cohorts"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    programme_type: Mapped[ProgrammeType] = mapped_column(pg_enum(ProgrammeType))
    start_date: Mapped[date]
    end_date: Mapped[date]
    graduation_threshold: Mapped[int] = mapped_column(default=80, server_default="80")
    # [{"month": 1, "name": "...", "start": "2026-01-01", "end": "2026-01-31"}, ...]
    kami_limu_month_boundaries: Mapped[list[dict[str, Any]] | None]
    ict_tracks_offered: Mapped[list[str] | None]
    status: Mapped[CohortStatus] = mapped_column(
        pg_enum(CohortStatus), default=CohortStatus.DRAFT, server_default="draft"
    )
    skill_names: Mapped[list[str] | None]
    # {"early": {"opens_at": ..., "closes_at": ...}, "mid": {...}, "late": {...}}
    skill_rating_windows: Mapped[dict[str, Any] | None]
    leaderboard_anonymous: Mapped[bool] = mapped_column(
        default=False, server_default="false"
    )
    peer_mentorship_deadline_hours: Mapped[int | None]
    deleted_at: Mapped[datetime | None]

    enrollments: Mapped[list["CohortEnrollment"]] = relationship(
        back_populates="cohort", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Cohort {self.name}>"


class CohortEnrollment(Base, UUIDPrimaryKeyMixin):
    """A user's participation in a cohort in a given role."""

    __tablename__ = "cohort_enrollments"
    __table_args__ = (UniqueConstraint("user_id", "cohort_id", "role"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole))
    # The 1:1 peer mentor responsible for this mentee; mentees sharing it form a group.
    peer_mentor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    ict_track: Mapped[str | None] = mapped_column(String(100))
    enrolled_at: Mapped[datetime] = mapped_column(server_default=func.now())
    enrolled_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    cohort: Mapped[Cohort] = relationship(back_populates="enrollments")
    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")
