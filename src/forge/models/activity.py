"""Extra activity and consultant models."""

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from forge.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum


class ActivityType(enum.StrEnum):
    ACADEMIC = "academic"
    EVENT = "event"
    OPPORTUNITY = "opportunity"
    SCHOLARSHIP = "scholarship"
    CONSULTATION = "consultation"


# Job and scholarship applications, whose points follow their stage.
APPLICATION_TYPES = (ActivityType.OPPORTUNITY, ActivityType.SCHOLARSHIP)


class ActivityStatus(enum.StrEnum):
    ACTIVE = "active"
    REVERSED = "reversed"


class OpportunityStage(enum.StrEnum):
    APPLIED = "applied"
    GENERAL_INTERVIEW = "general_interview"
    TECHNICAL_INTERVIEW = "technical_interview"
    FINAL_INTERVIEW = "final_interview"
    OFFER_MADE = "offer_made"


class FinalOutcome(enum.StrEnum):
    WAITING = "waiting_for_response"
    DID_NOT_PROCEED = "did_not_proceed"
    OFFER_ACCEPTED = "offer_made_and_accepted"
    OFFER_REJECTED = "offer_made_but_rejected"


class EventRole(enum.StrEnum):
    PARTICIPANT = "participant"
    SPEAKER = "speaker"
    ORGANIZER = "organizer"


class ConsultationStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"


class ExtraActivity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "extra_activities"

    type: Mapped[ActivityType] = mapped_column(pg_enum(ActivityType), index=True)
    mentee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    date: Mapped[date]
    status: Mapped[ActivityStatus] = mapped_column(
        pg_enum(ActivityStatus), default=ActivityStatus.ACTIVE, index=True
    )
    points_awarded: Mapped[int] = mapped_column(default=0)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    consultant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("consultants.id", ondelete="RESTRICT"), index=True
    )
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reversed_at: Mapped[datetime | None]
    reversal_reason: Mapped[str | None] = mapped_column(Text)


class Consultant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A mentor participants can log one-on-one consultations with."""

    __tablename__ = "consultants"

    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(255))
    organisation: Mapped[str | None] = mapped_column(String(200))
    expertise: Mapped[str | None] = mapped_column(Text)
    # Removed consultants stay referenced by past consultation logs.
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
