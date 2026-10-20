"""Notification and analytics snapshot models."""

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forge.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class NotificationType(enum.StrEnum):
    SESSION_PUBLISHED = "session_published"
    SESSION_RESCHEDULED = "session_rescheduled"
    SESSION_CANCELLED = "session_cancelled"
    WINDOW_OPENING = "attendance_window_opening"
    WINDOW_CLOSING_SOON = "attendance_window_closing_soon"
    GRADUATION_WARNING = "graduation_warning"
    GRADUATION_AT_RISK = "graduation_at_risk"
    OVERRIDE_SUBMITTED = "override_request_submitted"
    OVERRIDE_APPROVED = "override_request_approved"
    OVERRIDE_DENIED = "override_request_denied"
    ACTIVITY_APPROVED = "extra_activity_approved"
    ACTIVITY_REJECTED = "extra_activity_rejected"
    TASK_LAUNCHED = "peer_task_launched"
    TASK_DEADLINE_REMINDER = "peer_task_deadline_reminder"
    COHORT_INVITATION = "cohort_onboarding_invitation"
    BROADCAST = "broadcast"


class EmailStatus(enum.StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class Notification(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    notification_type: Mapped[NotificationType] = mapped_column(
        pg_enum(NotificationType), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    meta_data: Mapped[dict[str, Any] | None]
    related_resource_type: Mapped[str | None] = mapped_column(String(100))
    related_resource_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    read_at: Mapped[datetime | None]
    send_email: Mapped[bool] = mapped_column(default=True)
    email_status: Mapped[EmailStatus] = mapped_column(
        pg_enum(EmailStatus), default=EmailStatus.PENDING, index=True
    )
    email_attempts: Mapped[int] = mapped_column(default=0)
    email_last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None]


class CohortAnalyticsSnapshot(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "cohort_analytics_snapshots"
    __table_args__ = (UniqueConstraint("cohort_id", "snapshot_date"),)

    cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE"), index=True
    )
    snapshot_date: Mapped[date]
    metrics: Mapped[dict[str, Any]]
