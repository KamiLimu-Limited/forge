"""Which participants a session counts for.

Participants are mentees and peer mentors. A session applies to a participant
enrolled in its cohort before the session started (mid-cohort joiners are not
penalised for earlier sessions), and ICT sessions only apply to participants on
that track.
"""

import uuid

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.models import (
    PARTICIPANT_ROLES,
    CohortEnrollment,
    ProgrammeSession,
    SessionStatus,
)

COUNTED_STATUSES = (
    SessionStatus.PUBLISHED,
    SessionStatus.LIVE,
    SessionStatus.COMPLETED,
    SessionStatus.RESCHEDULED,
)


def applies_to_enrollment() -> ColumnElement[bool]:
    """SQL condition joining ``ProgrammeSession`` to the participant
    ``CohortEnrollment``s it applies to."""
    return and_(
        CohortEnrollment.cohort_id == ProgrammeSession.cohort_id,
        CohortEnrollment.role.in_(PARTICIPANT_ROLES),
        CohortEnrollment.archived_at.is_(None),
        CohortEnrollment.enrolled_at <= ProgrammeSession.starts_at,
        or_(
            ProgrammeSession.track.is_(None),
            ProgrammeSession.track == CohortEnrollment.ict_track,
        ),
    )


def session_applies(session: ProgrammeSession, enrollment: CohortEnrollment) -> bool:
    return (
        enrollment.cohort_id == session.cohort_id
        and enrollment.role in PARTICIPANT_ROLES
        and enrollment.archived_at is None
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
        .distinct()
    )
    return list(rows)
