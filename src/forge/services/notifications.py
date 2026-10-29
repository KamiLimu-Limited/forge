"""In-app notifications with queued email delivery and retries."""

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from string import Template
from typing import Any

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.config import settings
from forge.core.exceptions import NotFound
from forge.models import (
    AttendanceRecord,
    AttendanceWindow,
    CohortEnrollment,
    EmailStatus,
    Notification,
    NotificationType,
    ProgrammeSession,
    SessionStatus,
    User,
    UserRole,
    UserRoleAssignment,
)
from forge.schemas.notification import BroadcastRequest, NotificationFilters
from forge.services.eligibility import eligible_mentee_ids
from forge.services.email import send_email
from forge.services.email_templates import notification_email
from forge.services.pagination import paginate

logger = logging.getLogger(__name__)

T = NotificationType

# type -> (title, message) templates using ``$placeholders``.
TEMPLATES: dict[NotificationType, tuple[str, str]] = {
    T.SESSION_PUBLISHED: (
        "New session: $title",
        'A new session "$title" has been scheduled for $starts_at.',
    ),
    T.SESSION_RESCHEDULED: (
        "Session rescheduled: $title",
        '"$title" has moved to $starts_at. $reason',
    ),
    T.SESSION_CANCELLED: (
        "Session cancelled: $title",
        '"$title" scheduled for $starts_at has been cancelled. $reason',
    ),
    T.WINDOW_OPENING: (
        "Attendance open: $title",
        'You can now record your attendance for "$title" until $closes_at.',
    ),
    T.WINDOW_CLOSING_SOON: (
        "Attendance closing soon: $title",
        'The attendance window for "$title" closes at $closes_at. Submit before then.',
    ),
    T.GRADUATION_WARNING: (
        "Your attendance needs attention",
        "Your combined attendance is $rate%, close to the $threshold% graduation threshold.",
    ),
    T.GRADUATION_AT_RISK: (
        "You are at risk of not graduating",
        "Your combined attendance is $rate%, below the $threshold% graduation threshold.",
    ),
    T.OVERRIDE_SUBMITTED: (
        "Override request submitted",
        '$mentee requested an attendance override for "$title": $reason',
    ),
    T.OVERRIDE_APPROVED: (
        "Override request approved",
        'Your override request for "$title" was approved. You can submit until $closes_at.',
    ),
    T.OVERRIDE_DENIED: (
        "Override request denied",
        'Your override request for "$title" was denied. $reason',
    ),
    T.ACTIVITY_APPROVED: (
        "Activity approved: $title",
        'Your $type activity "$title" was approved and earned $points points.',
    ),
    T.ACTIVITY_REJECTED: (
        "Activity rejected: $title",
        'Your $type activity "$title" was not approved. $reason',
    ),
    T.TASK_LAUNCHED: (
        "New task: $title",
        'Your peer mentor launched "$title". Deadline: $deadline.',
    ),
    T.TASK_DEADLINE_REMINDER: (
        "Task due soon: $title",
        '"$title" is due at $deadline. Mark it complete once you\'re done.',
    ),
    T.COHORT_INVITATION: (
        "Welcome to $cohort",
        "You have been added to $cohort. Check your calendar for upcoming sessions.",
    ),
    T.BROADCAST: ("$title", "$message"),
}


def render(
    notification_type: NotificationType, context: dict[str, Any]
) -> tuple[str, str]:
    title, message = TEMPLATES[notification_type]
    values = {
        k: v.strftime("%a %d %b %Y, %H:%M UTC") if isinstance(v, datetime) else v
        for k, v in context.items()
    }
    return (
        Template(title).safe_substitute(values).strip(),
        Template(message).safe_substitute(values).strip(),
    )


def notify(
    db: AsyncSession,
    user_ids: Iterable[uuid.UUID],
    notification_type: NotificationType,
    context: dict[str, Any] | None = None,
    *,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    send_email: bool = True,
) -> list[Notification]:
    """Stage notifications for users; emails are delivered by the scheduler."""
    title, message = render(notification_type, context or {})
    notifications = [
        Notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            meta_data={k: str(v) for k, v in (context or {}).items()} or None,
            related_resource_type=resource_type,
            related_resource_id=resource_id,
            send_email=send_email,
            email_status=EmailStatus.PENDING if send_email else EmailStatus.SKIPPED,
        )
        for user_id in dict.fromkeys(user_ids)
    ]
    db.add_all(notifications)
    return notifications


async def cohort_member_ids(
    db: AsyncSession, cohort_id: uuid.UUID, roles: Iterable[UserRole] | None = None
) -> list[uuid.UUID]:
    stmt = (
        select(CohortEnrollment.user_id)
        .where(CohortEnrollment.cohort_id == cohort_id)
        .distinct()
    )
    if roles is not None:
        stmt = stmt.where(CohortEnrollment.role.in_(list(roles)))
    return list(await db.scalars(stmt))


async def list_for_user(
    db: AsyncSession, user: User, filters: NotificationFilters
) -> tuple[list[Notification], int]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
    )
    if filters.unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if filters.notification_type:
        stmt = stmt.where(Notification.notification_type == filters.notification_type)
    return await paginate(db, stmt, filters)


async def unread_count(db: AsyncSession, user: User) -> int:
    return (
        await db.scalar(
            select(func.count()).where(
                Notification.user_id == user.id, Notification.read_at.is_(None)
            )
        )
        or 0
    )


async def mark_read(
    db: AsyncSession, user: User, notification_id: uuid.UUID
) -> Notification:
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise NotFound("Notification not found")
    notification.read_at = notification.read_at or datetime.now(UTC)
    await db.commit()
    return notification


async def mark_all_read(db: AsyncSession, user: User) -> int:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def broadcast(db: AsyncSession, data: BroadcastRequest) -> int:
    stmt = select(User.id)
    if data.cohort_id:
        stmt = select(CohortEnrollment.user_id).where(
            CohortEnrollment.cohort_id == data.cohort_id
        )
        if data.roles:
            stmt = stmt.where(CohortEnrollment.role.in_(data.roles))
    elif data.roles:
        stmt = select(UserRoleAssignment.user_id).where(
            UserRoleAssignment.role.in_(data.roles)
        )
    recipients = list(await db.scalars(stmt.distinct()))
    notify(
        db,
        recipients,
        NotificationType.BROADCAST,
        {"title": data.title, "message": data.message},
        send_email=data.send_email,
    )
    await db.commit()
    return len(recipients)


async def list_failed(
    db: AsyncSession, filters: NotificationFilters
) -> tuple[list[Notification], int]:
    stmt = (
        select(Notification)
        .where(Notification.email_status == EmailStatus.FAILED)
        .order_by(Notification.created_at.desc())
    )
    return await paginate(db, stmt, filters)


async def dispatch_pending_emails(db: AsyncSession, batch_size: int = 100) -> int:
    """Send queued notification emails, retrying failures up to the configured limit."""
    rows = await db.execute(
        select(Notification, User)
        .join(User, User.id == Notification.user_id)
        .where(
            Notification.email_status.in_([EmailStatus.PENDING, EmailStatus.FAILED]),
            Notification.email_attempts < settings.NOTIFICATION_MAX_ATTEMPTS,
        )
        .order_by(Notification.created_at)
        .limit(batch_size)
    )
    sent = 0
    for notification, user in rows:
        notification.email_attempts += 1
        content = notification_email(
            notification.notification_type,
            notification.meta_data,
            first_name=user.first_name,
            title=notification.title,
            message=notification.message,
        )
        try:
            result = await send_email(user.email, content)
        except Exception as e:  # provider errors are recorded and retried
            notification.email_status = EmailStatus.FAILED
            notification.email_last_error = str(e)[:1000]
            logger.warning("Email for notification %s failed: %s", notification.id, e)
        else:
            notification.email_status = (
                EmailStatus.SENT if result is not None else EmailStatus.SKIPPED
            )
            notification.sent_at = datetime.now(UTC)
            sent += 1
    await db.commit()
    return sent


async def send_window_closing_reminders(db: AsyncSession) -> int:
    """Remind mentees without a submission that a window closes soon (once per session)."""
    now = datetime.now(UTC)
    soon = now + timedelta(hours=settings.WINDOW_CLOSING_REMINDER_HOURS)
    windows = await db.scalars(
        select(AttendanceWindow)
        .join(ProgrammeSession, ProgrammeSession.id == AttendanceWindow.session_id)
        .where(
            AttendanceWindow.is_active.is_(True),
            AttendanceWindow.closes_at > now,
            AttendanceWindow.closes_at <= soon,
            ProgrammeSession.status == SessionStatus.PUBLISHED,
        )
    )
    total = 0
    for window in windows:
        already_reminded = exists().where(
            Notification.user_id == CohortEnrollment.user_id,
            Notification.notification_type == NotificationType.WINDOW_CLOSING_SOON,
            Notification.related_resource_id == window.session_id,
        )
        submitted = exists().where(
            AttendanceRecord.mentee_id == CohortEnrollment.user_id,
            AttendanceRecord.session_id == window.session_id,
        )
        candidates = set(await eligible_mentee_ids(db, window.session))
        pending = set(
            await db.scalars(
                select(CohortEnrollment.user_id).where(
                    CohortEnrollment.cohort_id == window.session.cohort_id,
                    CohortEnrollment.role == UserRole.MENTEE,
                    ~already_reminded,
                    ~submitted,
                )
            )
        )
        recipients = candidates & pending
        notify(
            db,
            recipients,
            NotificationType.WINDOW_CLOSING_SOON,
            {
                "title": window.session.title,
                "starts_at": window.session.starts_at,
                "ends_at": window.session.ends_at,
                "closes_at": window.closes_at,
            },
            resource_type="session",
            resource_id=window.session_id,
        )
        total += len(recipients)
    await db.commit()
    return total
