"""Peer mentorship, notes and skill tracking models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forge.db.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    pg_enum,
)
from forge.db.types import EncryptedText


class RatingPoint(enum.StrEnum):
    EARLY = "early"
    MID = "mid"
    LATE = "late"


class SubmissionStatus(enum.StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"


class PeerMentorNote(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "peer_mentor_notes"

    peer_mentor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mentee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    note_text: Mapped[str] = mapped_column(EncryptedText)


class IctProgressNote(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "ict_progress_notes"

    ict_peer_mentor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mentee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    progress_note: Mapped[str] = mapped_column(Text)


class SkillRating(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "skill_ratings"
    __table_args__ = (UniqueConstraint("mentee_id", "cohort_id", "rating_point"),)

    mentee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE"), index=True
    )
    rating_point: Mapped[RatingPoint] = mapped_column(pg_enum(RatingPoint))
    ratings: Mapped[dict[str, int]]
    rated_at: Mapped[datetime]


class PeerMentorTask(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "peer_mentor_tasks"

    peer_mentor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    launch_date: Mapped[datetime]
    deadline_date: Mapped[datetime]
    resource_link: Mapped[str | None] = mapped_column(String(2048))


class TaskSubmission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "task_submissions"
    __table_args__ = (UniqueConstraint("task_id", "mentee_id"),)

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("peer_mentor_tasks.id", ondelete="CASCADE"), index=True
    )
    mentee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    submission_status: Mapped[SubmissionStatus] = mapped_column(
        pg_enum(SubmissionStatus), default=SubmissionStatus.PENDING
    )
    submitted_at: Mapped[datetime | None]
    notes: Mapped[str | None] = mapped_column(Text)
