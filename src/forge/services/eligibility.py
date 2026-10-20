"""Which mentees a session counts for.

A session applies to a mentee enrolled in its cohort before the session started
(mid-cohort joiners are not penalised for earlier sessions), and track-specific
sessions only apply to mentees on that ICT track.
"""

import uuid

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.models import CohortEnrollment, ProgrammeSession, SessionStatus, UserRole

COUNTED_STATUSES = (SessionStatus.PUBLISHED, SessionStatus.COMPLETED)


def applies_to_enrollment() -> ColumnElement[bool]:
    """SQL condition joining ``ProgrammeSession`` to the mentee ``CohortEnrollment``s it applies to."""
    return and_(
        CohortEnrollment.cohort_id == ProgrammeSession.cohort_id,
        CohortEnrollment.role == UserRole.MENTEE,
        CohortEnrollment.enrolled_at <= ProgrammeSession.starts_at,
        or_(
            ProgrammeSession.track.is_(None),
            ProgrammeSession.track == CohortEnrollment.ict_track,
        ),
    )


def session_applies(session: ProgrammeSession, enrollment: CohortEnrollment) -> bool:
    return (
        enrollment.cohort_id == session.cohort_id
        and enrollment.role is UserRole.MENTEE
        and enrollment.enrolled_at <= session.starts_at
        and (session.track is None or session.track == enrollment.ict_track)
    )


async def eligible_mentee_ids(
    db: AsyncSession, session: ProgrammeSession
) -> list[uuid.UUID]:
    rows = await db.scalars(
        select(CohortEnrollment.user_id)
        .join(ProgrammeSession, ProgrammeSession.id == session.id)
        .where(applies_to_enrollment())
    )
    return list(rows)
