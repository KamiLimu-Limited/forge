"""In-process periodic job runner.

Started from the app lifespan when ``SCHEDULER_ENABLED`` is set. A Postgres
advisory lock ensures only one worker process runs jobs at a time.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.config import settings
from forge.db.session import async_session_factory
from forge.services import (
    analytics,
    attendance,
    auth,
    mentorship,
    notifications,
    points,
)

logger = logging.getLogger(__name__)

Job = Callable[[AsyncSession], Awaitable[object]]

ADVISORY_LOCK_ID = 0x464F524745  # "FORGE"


def default_jobs() -> list[Job]:
    return [
        attendance.close_expired_windows,
        notifications.send_window_closing_reminders,
        mentorship.send_task_deadline_reminders,
        points.send_graduation_warnings,
        notifications.dispatch_pending_emails,
        auth.purge_expired_tokens,
        analytics.snapshot_active_cohorts,
    ]


async def run_jobs(jobs: list[Job] | None = None) -> None:
    async with async_session_factory() as lock_session:
        acquired = await lock_session.scalar(
            text("SELECT pg_try_advisory_lock(:id)"), {"id": ADVISORY_LOCK_ID}
        )
        if not acquired:
            return
        try:
            for job in jobs or default_jobs():
                async with async_session_factory() as db:
                    try:
                        result = await job(db)
                        logger.debug("job %s -> %s", job.__qualname__, result)
                    except Exception:
                        logger.exception("Scheduled job %s failed", job.__qualname__)
                        await db.rollback()
        finally:
            await lock_session.execute(
                text("SELECT pg_advisory_unlock(:id)"), {"id": ADVISORY_LOCK_ID}
            )


class Scheduler:
    def __init__(self, interval: int = settings.SCHEDULER_INTERVAL_SECONDS) -> None:
        self.interval = interval
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="forge-scheduler")

    async def _loop(self) -> None:
        while True:
            try:
                await run_jobs()
            except Exception:
                logger.exception("Scheduler tick failed")
            await asyncio.sleep(self.interval)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
