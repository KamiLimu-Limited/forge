"""Attendance engine models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from forge.db.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    pg_enum,
)
from forge.models.programme_session import ProgrammeSession

RATING_QUESTION_COUNT = 9


class AttendanceStatus(enum.StrEnum):
    PENDING = "pending"
    PRESENT = "present"
    ABSENT = "absent"
    MISSED = "missed"
    EXCUSED = "excused"


class AttendanceSource(enum.StrEnum):
    ON_TIME = "on_time"
    REOPENED = "reopened"


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
    __table_args__ = (
        UniqueConstraint("mentee_id", "session_id"),
        CheckConstraint(
            f"ratings IS NULL OR cardinality(ratings) = {RATING_QUESTION_COUNT}",
            name="ratings_count",
        ),
    )

    mentee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[AttendanceStatus] = mapped_column(
        pg_enum(AttendanceStatus), default=AttendanceStatus.PENDING
    )
    source: Mapped[AttendanceSource | None] = mapped_column(pg_enum(AttendanceSource))
    # Answers to the cohort's nine rating questions, in question order (1 to 5 each).
    ratings: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    feedback: Mapped[str | None] = mapped_column(Text)
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
    # The deadline the participant asks for; used when approval sets none.
    requested_closes_at: Mapped[datetime | None]
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


class SessionNote(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A participant's personal notes on a session, visible only to them."""

    __tablename__ = "session_notes"
    __table_args__ = (UniqueConstraint("user_id", "session_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(Text)
