"""Attendance window rules.

Windows open when a session starts. Thursday sessions close 24h after the end,
Saturday sessions 48h after, and peer mentorship sessions at their explicit
deadline (or the cohort/default allowance). All durations are configurable.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.config import settings
from forge.models import (
    AttendanceWindow,
    AttendanceWindowOverride,
    Cohort,
    ProgrammeSession,
    SessionCategory,
)


def compute_window(
    session: ProgrammeSession, cohort: Cohort
) -> tuple[datetime, datetime]:
    opens_at = session.starts_at
    match session.category:
        case SessionCategory.THURSDAY:
            closes_at = session.ends_at + timedelta(
                hours=settings.THURSDAY_WINDOW_HOURS
            )
        case SessionCategory.SATURDAY:
            closes_at = session.ends_at + timedelta(
                hours=settings.SATURDAY_WINDOW_HOURS
            )
        case SessionCategory.PEER_MENTORSHIP:
            hours = (
                cohort.peer_mentorship_deadline_hours
                or settings.PEER_MENTORSHIP_WINDOW_HOURS
            )
            closes_at = session.attendance_deadline or session.ends_at + timedelta(
                hours=hours
            )
    return opens_at, closes_at


async def get_window(
    db: AsyncSession, session_id: uuid.UUID
) -> AttendanceWindow | None:
    return await db.scalar(
        select(AttendanceWindow).where(AttendanceWindow.session_id == session_id)
    )


async def sync_window(
    db: AsyncSession,
    session: ProgrammeSession,
    cohort: Cohort,
    *,
    reset_overrides: bool = False,
) -> AttendanceWindow:
    """Create or recompute the session's window (re-opening it if it was closed)."""
    opens_at, closes_at = compute_window(session, cohort)
    window = await get_window(db, session.id)
    if window is None:
        window = AttendanceWindow(
            session_id=session.id, opens_at=opens_at, closes_at=closes_at, overrides=[]
        )
        db.add(window)
    else:
        window.opens_at, window.closes_at = opens_at, closes_at
        window.is_active, window.closed_at = True, None
        if reset_overrides:
            window.overrides.clear()
    await db.flush()
    return window


def override_for(
    window: AttendanceWindow, mentee_id: uuid.UUID
) -> AttendanceWindowOverride | None:
    return next((o for o in window.overrides if o.mentee_id == mentee_id), None)


def effective_closes_at(
    window: AttendanceWindow, mentee_id: uuid.UUID | None = None
) -> datetime:
    # An early manual close (closed_at) cuts the window short; overrides extend it.
    base = min(t for t in (window.closes_at, window.closed_at) if t is not None)
    override = override_for(window, mentee_id) if mentee_id else None
    return max(base, override.new_closes_at) if override else base


def is_open(
    window: AttendanceWindow,
    mentee_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    return window.opens_at <= now < effective_closes_at(window, mentee_id)
