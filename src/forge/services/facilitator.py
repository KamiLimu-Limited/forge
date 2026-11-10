"""Facilitator ratings for peer mentors.

A peer mentor is rated on the sessions they mentor. On peer mentorship sessions,
where every 1:1 peer mentor guides their own group, only their group's ratings
count; on other sessions every attendee's ratings count.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.exceptions import NotFound
from forge.models import (
    PEER_MENTOR_ROLES,
    AttendanceRecord,
    CohortEnrollment,
    ProgrammeSession,
    SessionCategory,
    SessionMentor,
    SessionStatus,
    User,
)
from forge.schemas.attendance import SessionBrief
from forge.schemas.dashboard import FeedbackEntry
from forge.schemas.facilitator import (
    FacilitatedSession,
    FacilitatorSummary,
    PeerMentorAverage,
    RatingTrendPoint,
    SessionRatings,
)
from forge.services import ratings
from forge.services.access import get_cohort_or_404, group_mentee_ids
from forge.services.dashboard import anonymous_id
from forge.services.eligibility import COUNTED_STATUSES
from forge.services.sessions import SCHEDULED_STATUSES


async def peer_mentor_cohort(
    db: AsyncSession, user: User, cohort_id: uuid.UUID | None
) -> uuid.UUID:
    stmt = select(CohortEnrollment.cohort_id).where(
        CohortEnrollment.user_id == user.id,
        CohortEnrollment.role.in_(PEER_MENTOR_ROLES),
    )
    if cohort_id is not None:
        stmt = stmt.where(CohortEnrollment.cohort_id == cohort_id)
    found = await db.scalar(stmt.order_by(CohortEnrollment.enrolled_at.desc()).limit(1))
    if found is None:
        raise NotFound("You are not enrolled as a peer mentor")
    return found


async def mentored_sessions(
    db: AsyncSession, mentor_id: uuid.UUID, cohort_id: uuid.UUID
) -> list[ProgrammeSession]:
    return list(
        await db.scalars(
            select(ProgrammeSession)
            .join(SessionMentor, SessionMentor.session_id == ProgrammeSession.id)
            .where(
                SessionMentor.user_id == mentor_id,
                ProgrammeSession.cohort_id == cohort_id,
                ProgrammeSession.status.in_(COUNTED_STATUSES),
            )
            .order_by(ProgrammeSession.starts_at)
        )
    )


async def _scope(
    db: AsyncSession, mentor_id: uuid.UUID, session: ProgrammeSession
) -> list[ColumnElement[bool]]:
    conditions = [AttendanceRecord.session_id == session.id]
    if session.category is SessionCategory.PEER_MENTORSHIP:
        group = await group_mentee_ids(db, mentor_id, session.cohort_id)
        conditions.append(AttendanceRecord.mentee_id.in_(group))
    return conditions


async def _rated(
    db: AsyncSession, mentor_id: uuid.UUID, session: ProgrammeSession
) -> tuple[int, ratings.Averages]:
    return await ratings.averages(db, *await _scope(db, mentor_id, session))


async def facilitated(
    db: AsyncSession, mentor_id: uuid.UUID, cohort_id: uuid.UUID
) -> list[FacilitatedSession]:
    result = []
    for session in await mentored_sessions(db, mentor_id, cohort_id):
        responses, values = await _rated(db, mentor_id, session)
        result.append(
            FacilitatedSession(
                session=SessionBrief.model_validate(session),
                responses=responses,
                average=ratings.overall(values),
            )
        )
    return result


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


async def summary(
    db: AsyncSession, user: User, cohort_id: uuid.UUID | None
) -> FacilitatorSummary:
    cohort_id = await peer_mentor_cohort(db, user, cohort_id)
    sessions = await facilitated(db, user.id, cohort_id)
    rated = [s for s in sessions if s.average is not None]
    now = datetime.now(UTC)
    return FacilitatorSummary(
        cohort_id=cohort_id,
        sessions_completed=sum(
            s.session.status is SessionStatus.COMPLETED for s in sessions
        ),
        sessions_in_progress=sum(
            s.session.status in SCHEDULED_STATUSES and s.session.starts_at <= now
            for s in sessions
        ),
        average=_mean([s.average for s in rated if s.average is not None]),
        best_rated_session=max(rated, key=lambda s: s.average or 0, default=None),
    )


async def session_ratings(
    db: AsyncSession, user: User, session_id: uuid.UUID
) -> SessionRatings:
    session = await db.get(ProgrammeSession, session_id)
    if session is None or user.id not in {m.user_id for m in session.mentors}:
        raise NotFound("You did not mentor this session")
    conditions = await _scope(db, user.id, session)
    responses, values = await ratings.averages(db, *conditions)
    records = await db.scalars(
        select(AttendanceRecord).where(ratings.rated(), *conditions)
    )
    return SessionRatings(
        session=SessionBrief.model_validate(session),
        responses=responses,
        average=ratings.overall(values),
        questions=ratings.describe(
            values, await get_cohort_or_404(db, session.cohort_id)
        ),
        feedback=[
            FeedbackEntry(
                respondent=anonymous_id(session.id, r.mentee_id),
                ratings=r.ratings,
                feedback=r.feedback,
            )
            for r in records
        ],
    )


async def ratings_over_time(
    db: AsyncSession, user: User, cohort_id: uuid.UUID | None
) -> list[RatingTrendPoint]:
    cohort_id = await peer_mentor_cohort(db, user, cohort_id)
    return [
        RatingTrendPoint(
            session_id=s.session.id,
            title=s.session.title,
            starts_at=s.session.starts_at,
            average=s.average,
        )
        for s in await facilitated(db, user.id, cohort_id)
    ]


async def peer_mentor_average(
    db: AsyncSession, user: User, cohort_id: uuid.UUID | None
) -> PeerMentorAverage:
    """The mean of every peer mentor's own facilitator average in the cohort."""
    cohort_id = await peer_mentor_cohort(db, user, cohort_id)
    mentor_ids = set(
        await db.scalars(
            select(CohortEnrollment.user_id).where(
                CohortEnrollment.cohort_id == cohort_id,
                CohortEnrollment.role.in_(PEER_MENTOR_ROLES),
            )
        )
    )
    averages = []
    for mentor_id in mentor_ids:
        rated = [
            s.average
            for s in await facilitated(db, mentor_id, cohort_id)
            if s.average is not None
        ]
        if (mean := _mean(rated)) is not None:
            averages.append(mean)
    return PeerMentorAverage(
        cohort_id=cohort_id, peer_mentors=len(averages), average=_mean(averages)
    )


async def peer_mentorship_feedback(
    db: AsyncSession, user: User, cohort_id: uuid.UUID | None
) -> list[SessionRatings]:
    """What the caller's own mentees said about each peer mentorship session."""
    cohort_id = await peer_mentor_cohort(db, user, cohort_id)
    group = await group_mentee_ids(db, user.id, cohort_id)
    cohort = await get_cohort_or_404(db, cohort_id)
    sessions = await db.scalars(
        select(ProgrammeSession)
        .where(
            ProgrammeSession.cohort_id == cohort_id,
            ProgrammeSession.category == SessionCategory.PEER_MENTORSHIP,
            ProgrammeSession.status.in_(COUNTED_STATUSES),
        )
        .order_by(ProgrammeSession.starts_at)
    )
    result = []
    for session in sessions:
        conditions = [
            AttendanceRecord.session_id == session.id,
            AttendanceRecord.mentee_id.in_(group),
        ]
        responses, values = await ratings.averages(db, *conditions)
        records = await db.scalars(
            select(AttendanceRecord).where(ratings.rated(), *conditions)
        )
        result.append(
            SessionRatings(
                session=SessionBrief.model_validate(session),
                responses=responses,
                average=ratings.overall(values),
                questions=ratings.describe(values, cohort),
                feedback=[
                    FeedbackEntry(
                        respondent=anonymous_id(session.id, r.mentee_id),
                        ratings=r.ratings,
                        feedback=r.feedback,
                    )
                    for r in records
                ],
            )
        )
    return result
