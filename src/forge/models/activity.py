"""Extra activity models."""

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
    CONSULTATION = "consultation"


class ActivityStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


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
        pg_enum(ActivityStatus), default=ActivityStatus.PENDING, index=True
    )
    points_awarded: Mapped[int] = mapped_column(default=0)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None]
    review_reason: Mapped[str | None] = mapped_column(Text)
