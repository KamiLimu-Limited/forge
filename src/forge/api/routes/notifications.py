"""Notification endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from forge.api.deps import ActiveUser, AdminUser, DbSession
from forge.models import Notification
from forge.schemas.common import Page
from forge.schemas.notification import (
    AdminNotificationResponse,
    BroadcastRequest,
    BroadcastResponse,
    MarkAllReadResponse,
    NotificationFilters,
    NotificationResponse,
)
from forge.services import notifications as notification_service

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/me")
async def my_notifications(
    filters: Annotated[NotificationFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[NotificationResponse]:
    """Your notifications, newest first. Filter with `unread_only` or `notification_type`."""
    notifications, total = await notification_service.list_for_user(db, user, filters)
    return Page[NotificationResponse].build(notifications, total, filters)


@router.get("/me/unread-count")
async def my_unread_count(user: ActiveUser, db: DbSession) -> dict[str, int]:
    """Number of unread notifications, for badge counters."""
    return {"unread": await notification_service.unread_count(db, user)}


@router.patch("/read-all")
async def mark_all_read(user: ActiveUser, db: DbSession) -> MarkAllReadResponse:
    """Mark every unread notification as read."""
    return MarkAllReadResponse(
        updated=await notification_service.mark_all_read(db, user)
    )


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(
    notification_id: UUID, user: ActiveUser, db: DbSession
) -> Notification:
    """Mark one of your notifications as read."""
    return await notification_service.mark_read(db, user, notification_id)


@router.post("/broadcast", status_code=status.HTTP_201_CREATED)
async def broadcast(
    data: BroadcastRequest, admin: AdminUser, db: DbSession
) -> BroadcastResponse:
    """Message everyone, a cohort, or holders of given roles. **Admin only.**
    Emails are queued and sent by the background dispatcher."""
    return BroadcastResponse(recipients=await notification_service.broadcast(db, data))


@router.get("/failed")
async def failed_notifications(
    filters: Annotated[NotificationFilters, Query()], admin: AdminUser, db: DbSession
) -> Page[AdminNotificationResponse]:
    """Notifications whose email delivery failed, with the last error. **Admin only.**"""
    notifications, total = await notification_service.list_failed(db, filters)
    return Page[AdminNotificationResponse].build(notifications, total, filters)
