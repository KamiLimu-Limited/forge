"""Programme session (Thursday, Saturday, peer mentorship) models."""

import enum
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from forge.db.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    pg_enum,
)
from forge.models.user import User

if TYPE_CHECKING:
    from forge.models.attendance import AttendanceWindow


class SessionCategory(enum.StrEnum):
    THURSDAY = "thursday"
    SATURDAY = "saturday"
    PEER_MENTORSHIP = "peer_mentorship"


class SessionType(enum.StrEnum):
    CORE = "core"
    ICT = "ict"
    PROFESSIONAL = "professional"
    PEER_MENTORSHIP = "peer_mentorship"


class SessionMode(enum.StrEnum):
    PHYSICAL = "physical"
    VIRTUAL = "virtual"
    HYBRID = "hybrid"


class SessionStatus(enum.StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class MentorRole(enum.StrEnum):
    LEAD = "lead"
    CO_MENTOR = "co_mentor"


class ResourceType(enum.StrEnum):
    SLIDES = "slides"
    RECORDING = "recording"
    DRIVE_FOLDER = "drive_folder"
    DOCUMENT = "document"
    OTHER = "other"


class ProgrammeSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sessions"

    cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    kami_limu_month: Mapped[int]
    starts_at: Mapped[datetime] = mapped_column(index=True)
    duration_minutes: Mapped[int]
    category: Mapped[SessionCategory] = mapped_column(pg_enum(SessionCategory))
    session_type: Mapped[SessionType] = mapped_column(pg_enum(SessionType))
    track: Mapped[str | None] = mapped_column(String(100))
    mode: Mapped[SessionMode] = mapped_column(
        pg_enum(SessionMode), default=SessionMode.PHYSICAL
    )
    location: Mapped[str | None] = mapped_column(String(255))
    points: Mapped[int]
    status: Mapped[SessionStatus] = mapped_column(
        pg_enum(SessionStatus), default=SessionStatus.DRAFT
    )
    # Explicit deadline for peer mentorship attendance; overrides the default window.
    attendance_deadline: Mapped[datetime | None]
    original_starts_at: Mapped[datetime | None]
    reschedule_history: Mapped[list[dict[str, Any]] | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    mentors: Mapped[list["SessionMentor"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", passive_deletes=True
    )
    resources: Mapped[list["SessionResource"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", passive_deletes=True
    )
    attendance_window: Mapped["AttendanceWindow | None"] = relationship(
        lazy="selectin", viewonly=True
    )

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_minutes)


class SessionMentor(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "session_mentors"
    __table_args__ = (UniqueConstraint("session_id", "user_id"),)

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mentor_role: Mapped[MentorRole] = mapped_column(pg_enum(MentorRole))

    user: Mapped[User] = relationship(lazy="joined")


class SessionResource(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "session_resources"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    resource_type: Mapped[ResourceType] = mapped_column(pg_enum(ResourceType))
    url: Mapped[str] = mapped_column(String(2048))
    description: Mapped[str | None] = mapped_column(String(500))
