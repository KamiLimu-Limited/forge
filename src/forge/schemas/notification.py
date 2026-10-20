"""Notification schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from forge.models import EmailStatus, NotificationType, UserRole
from forge.schemas.common import PageParams, RequestSchema, Schema


class NotificationFilters(PageParams):
    unread_only: bool = False
    notification_type: NotificationType | None = None


class NotificationResponse(Schema):
    id: UUID
    notification_type: NotificationType
    title: str
    message: str
    meta_data: dict[str, Any] | None
    related_resource_type: str | None
    related_resource_id: UUID | None
    read_at: datetime | None
    created_at: datetime


class AdminNotificationResponse(NotificationResponse):
    user_id: UUID
    email_status: EmailStatus
    email_attempts: int
    email_last_error: str | None
    sent_at: datetime | None


class BroadcastRequest(RequestSchema):
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=5000)
    cohort_id: UUID | None = Field(None, description="Limit to members of this cohort")
    roles: list[UserRole] | None = Field(
        None, description="Limit to holders of these roles"
    )
    send_email: bool = True


class BroadcastResponse(Schema):
    recipients: int


class MarkAllReadResponse(Schema):
    updated: int
