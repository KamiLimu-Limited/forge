"""Attendance engine models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from forge.db.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    pg_enum,
)
from forge.models.programme_session import ProgrammeSession


class AttendanceStatus(enum.StrEnum):
    PENDING = "pending"
    ATTENDED = "attended"
    NOT_ATTENDED = "not_attended"
    MISSED = "missed"
    EXCUSED = "excused"
    DISPUTED = "disputed"


class OverrideRequestStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class AttendanceWindow(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "attendance_windows"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), unique=True
    )
    opens_at: Mapped[datetime]
    closes_at: Mapped[datetime] = mapped_column(index=True)
    # False once closed manually or by the scheduler.
    is_active: Mapped[bool] = mapped_column(default=True)
    closed_at: Mapped[datetime | None]

    session: Mapped[ProgrammeSession] = relationship(lazy="joined")
    overrides: Mapped[list["AttendanceWindowOverride"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", passive_deletes=True
    )


class AttendanceWindowOverride(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "attendance_window_overrides"
    __table_args__ = (UniqueConstraint("attendance_window_id", "mentee_id"),)

    attendance_window_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attendance_windows.id", ondelete="CASCADE"), index=True
    )
    mentee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    new_closes_at: Mapped[datetime]
    reason: Mapped[str | None] = mapped_column(Text)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AttendanceRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("mentee_id", "session_id"),)

    mentee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[AttendanceStatus] = mapped_column(
        pg_enum(AttendanceStatus), default=AttendanceStatus.PENDING
    )
    quality_rating: Mapped[int | None] = mapped_column(SmallInteger)
    usefulness_rating: Mapped[int | None] = mapped_column(SmallInteger)
    understanding_score: Mapped[int | None] = mapped_column(SmallInteger)
    academic_application_score: Mapped[int | None] = mapped_column(SmallInteger)
    career_application_score: Mapped[int | None] = mapped_column(SmallInteger)
    feedback: Mapped[str | None] = mapped_column(Text)
    personal_notes: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None]

    session: Mapped[ProgrammeSession] = relationship(lazy="joined")


class OverrideRequest(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "override_requests"

    mentee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[OverrideRequestStatus] = mapped_column(
        pg_enum(OverrideRequestStatus),
        default=OverrideRequestStatus.PENDING,
        index=True,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None]
    review_reason: Mapped[str | None] = mapped_column(Text)

    session: Mapped[ProgrammeSession] = relationship(lazy="joined")
