"""Aggregated data for role dashboards."""

import hashlib
import uuid
from datetime import UTC, datetime
from statistics import fmean

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.exceptions import NotFound, PermissionDenied
from forge.models import (
    AttendanceRecord,
    AttendanceStatus,
    AttendanceWindow,
    CohortEnrollment,
    ExtraActivity,
    OverrideRequest,
    OverrideRequestStatus,
    ProgrammeSession,
    SessionMentor,
    SessionStatus,
    User,
    UserRole,
)
from forge.schemas.activity import ExtraActivityResponse
from forge.schemas.attendance import SessionBrief
from forge.schemas.dashboard import (
    FeedbackEntry,
    GroupOverview,
    MenteeDrilldown,
    MenteeOverview,
    MenteeSessionFeedback,
    MenteeSummary,
    SessionAttendanceSummary,
    SessionFeedbackResponse,
    TrackMenteeSummary,
    TrackOverview,
)
from forge.schemas.objective import ObjectiveResponse
from forge.schemas.user import UserSummary
from forge.services import ratings
from forge.services.access import get_cohort_or_404, get_enrollment, is_cohort_staff
from forge.services.eligibility import COUNTED_STATUSES, applies_to_enrollment
from forge.services.notifications import unread_count
from forge.services.objectives import list_objectives
from forge.services.points import (
    MenteeStats,
    breakdown,
    compute_stats,
    detailed_breakdown,
    graduation,
    rates,
)
from forge.services.sessions import SCHEDULED_STATUSES, is_session_mentor
from forge.services.windows import is_open


def summarize(enrollment: CohortEnrollment, stats: MenteeStats) -> MenteeSummary:
    return MenteeSummary(
        mentee=UserSummary.model_validate(enrollment.user),
        ict_track=enrollment.ict_track,
        total_points=stats.total_points,
        core_rate=stats.core_rate,
        overall_rate=stats.overall_rate,
        sessions_attended=stats.total.attended,
        sessions_due=stats.total.due,
    )


async def mentee_overview(
    db: AsyncSession, user: User, enrollment: CohortEnrollment
) -> MenteeOverview:
    cohort = await get_cohort_or_404(db, enrollment.cohort_id)
    stats = (await compute_stats(db, cohort.id, [user.id]))[user.id]
    now = datetime.now(UTC)

    upcoming = await db.scalars(
        select(ProgrammeSession)
        .join(CohortEnrollment, applies_to_enrollment())
        .where(
            CohortEnrollment.id == enrollment.id,
            ProgrammeSession.status.in_(SCHEDULED_STATUSES),
            ProgrammeSession.starts_at > now,
        )
        .order_by(ProgrammeSession.starts_at)
        .limit(1)
    )
    windows = await db.scalars(
        select(AttendanceWindow)
        .join(ProgrammeSession, ProgrammeSession.id == AttendanceWindow.session_id)
        .join(CohortEnrollment, applies_to_enrollment())
        .where(
            CohortEnrollment.id == enrollment.id,
            ProgrammeSession.status.in_(COUNTED_STATUSES),
            ~AttendanceWindow.session_id.in_(
                select(AttendanceRecord.session_id).where(
                    AttendanceRecord.mentee_id == user.id,
                    AttendanceRecord.status != AttendanceStatus.MISSED,
                )
            ),
        )
    )
    pending_overrides = await db.scalar(
        select(func.count()).where(
            OverrideRequest.mentee_id == user.id,
            OverrideRequest.status == OverrideRequestStatus.PENDING,
        )
    )
    next_session = upcoming.first()
    return MenteeOverview(
        cohort_id=cohort.id,
        points=breakdown(stats),
        core_rate=stats.core_rate,
        overall_rate=stats.overall_rate,
        graduation_threshold=cohort.graduation_threshold,
        next_session=SessionBrief.model_validate(next_session)
        if next_session
        else None,
        open_attendance_windows=sum(is_open(w, user.id, now) for w in windows),
        pending_override_requests=pending_overrides or 0,
        unread_notifications=await unread_count(db, user),
    )


async def peer_mentor_enrollment(
    db: AsyncSession, mentor: User, cohort_id: uuid.UUID | None
) -> CohortEnrollment:
    enrollment = await get_enrollment(
        db, mentor.id, cohort_id, UserRole.PEER_MENTOR_1_1
    )
    if enrollment is None:
        raise PermissionDenied("You are not enrolled as a 1:1 peer mentor")
    return enrollment


async def _group(
    db: AsyncSession, mentor_id: uuid.UUID, cohort_id: uuid.UUID
) -> list[CohortEnrollment]:
    return list(
        await db.scalars(
            select(CohortEnrollment).where(
                CohortEnrollment.cohort_id == cohort_id,
                CohortEnrollment.peer_mentor_id == mentor_id,
                CohortEnrollment.role == UserRole.MENTEE,
            )
        )
    )


async def group_overview(
    db: AsyncSession, mentor: User, cohort_id: uuid.UUID | None
) -> GroupOverview:
    own = await peer_mentor_enrollment(db, mentor, cohort_id)
    cohort = await get_cohort_or_404(db, own.cohort_id)
    group = await _group(db, mentor.id, cohort.id)
    stats = await compute_stats(db, cohort.id, [e.user_id for e in group])
    summaries = sorted(
        (summarize(e, stats[e.user_id]) for e in group), key=lambda s: s.core_rate
    )

    def average(values: list[float]) -> float:
        return round(fmean(values), 2) if values else 0.0

    return GroupOverview(
        cohort_id=cohort.id,
        mentees=summaries,
        average_core_rate=average([s.core_rate for s in summaries]),
        average_overall_rate=average([s.overall_rate for s in summaries]),
    )


async def mentee_drilldown(
    db: AsyncSession, mentor: User, mentee_id: uuid.UUID, cohort_id: uuid.UUID | None
) -> MenteeDrilldown:
    own = await peer_mentor_enrollment(db, mentor, cohort_id)
    enrollment = await get_enrollment(db, mentee_id, own.cohort_id)
    if enrollment is None or enrollment.peer_mentor_id != mentor.id:
        raise NotFound("Mentee is not in your group")
    cohort = await get_cohort_or_404(db, own.cohort_id)
    stats = (await compute_stats(db, cohort.id, [mentee_id]))[mentee_id]

    activities = await db.scalars(
        select(ExtraActivity)
        .where(
            ExtraActivity.mentee_id == mentee_id, ExtraActivity.cohort_id == cohort.id
        )
        .order_by(ExtraActivity.created_at.desc())
        .limit(5)
    )
    submissions = await db.scalars(
        select(AttendanceRecord)
        .join(ProgrammeSession, ProgrammeSession.id == AttendanceRecord.session_id)
        .where(
            AttendanceRecord.mentee_id == mentee_id,
            ProgrammeSession.cohort_id == cohort.id,
            AttendanceRecord.submitted_at.is_not(None),
        )
        .order_by(ProgrammeSession.starts_at.desc())
    )
    return MenteeDrilldown(
        summary=summarize(enrollment, stats),
        points=await detailed_breakdown(db, stats),
        rates=rates(stats),
        graduation=graduation(stats, cohort),
        objectives=[
            ObjectiveResponse.model_validate(o)
            for o in await list_objectives(db, mentee_id, cohort.id)
        ],
        session_feedback=[
            MenteeSessionFeedback(
                session=SessionBrief.model_validate(r.session),
                ratings=r.ratings,
                feedback=r.feedback,
                submitted_at=r.submitted_at,
            )
            for r in submissions
        ],
        recent_activities=[ExtraActivityResponse.model_validate(a) for a in activities],
    )


async def ict_enrollment(
    db: AsyncSession, mentor: User, cohort_id: uuid.UUID | None
) -> CohortEnrollment:
    enrollment = await get_enrollment(
        db, mentor.id, cohort_id, UserRole.PEER_MENTOR_ICT
    )
    if enrollment is None or not enrollment.ict_track:
        raise PermissionDenied(
            "You are not enrolled as an ICT peer mentor with a track"
        )
    return enrollment


async def track_overview(
    db: AsyncSession, mentor: User, cohort_id: uuid.UUID | None
) -> TrackOverview:
    own = await ict_enrollment(db, mentor, cohort_id)
    assert own.ict_track is not None
    cohort = await get_cohort_or_404(db, own.cohort_id)
    mentees = list(
        await db.scalars(
            select(CohortEnrollment).where(
                CohortEnrollment.cohort_id == cohort.id,
                CohortEnrollment.role == UserRole.MENTEE,
                CohortEnrollment.ict_track == own.ict_track,
            )
        )
    )
    stats = await compute_stats(db, cohort.id, [e.user_id for e in mentees])
    return TrackOverview(
        cohort_id=cohort.id,
        track=own.ict_track,
        mentees=[
            TrackMenteeSummary(
                mentee=UserSummary.model_validate(e.user),
                track=stats[e.user_id].by_track[own.ict_track].bucket(own.ict_track),
                core_rate=stats[e.user_id].core_rate,
                overall_rate=stats[e.user_id].overall_rate,
            )
            for e in mentees
        ],
    )


async def _session_summaries(
    db: AsyncSession, sessions: list[ProgrammeSession]
) -> list[SessionAttendanceSummary]:
    if not sessions:
        return []
    ids = [s.id for s in sessions]
    eligible = dict(
        (
            await db.execute(
                select(ProgrammeSession.id, func.count(CohortEnrollment.id))
                .join(CohortEnrollment, applies_to_enrollment())
                .where(ProgrammeSession.id.in_(ids))
                .group_by(ProgrammeSession.id)
            )
        ).all()
    )
    attended = dict(
        (
            await db.execute(
                select(AttendanceRecord.session_id, func.count())
                .where(
                    AttendanceRecord.session_id.in_(ids),
                    AttendanceRecord.status == AttendanceStatus.PRESENT,
                )
                .group_by(AttendanceRecord.session_id)
            )
        ).all()
    )
    averages = await ratings.averages_by_session(db, ids)
    cohorts = {s.cohort_id: await get_cohort_or_404(db, s.cohort_id) for s in sessions}
    result = []
    for s in sessions:
        responses, values = averages.get(
            s.id, (0, [None] * len(ratings.QUESTION_NUMBERS))
        )
        result.append(
            SessionAttendanceSummary(
                session=SessionBrief.model_validate(s),
                eligible=eligible.get(s.id, 0),
                attended=attended.get(s.id, 0),
                responses=responses,
                average_quality=values[0],
                question_averages=ratings.describe(values, cohorts[s.cohort_id]),
            )
        )
    return result


async def ict_sessions(
    db: AsyncSession, mentor: User, cohort_id: uuid.UUID | None
) -> list[SessionAttendanceSummary]:
    own = await ict_enrollment(db, mentor, cohort_id)
    sessions = await db.scalars(
        select(ProgrammeSession)
        .where(
            ProgrammeSession.cohort_id == own.cohort_id,
            ProgrammeSession.track == own.ict_track,
            ProgrammeSession.status != SessionStatus.DRAFT,
        )
        .order_by(ProgrammeSession.starts_at)
    )
    return await _session_summaries(db, list(sessions))


async def professional_mentor_sessions(
    db: AsyncSession, mentor: User
) -> list[SessionAttendanceSummary]:
    sessions = await db.scalars(
        select(ProgrammeSession)
        .join(SessionMentor, SessionMentor.session_id == ProgrammeSession.id)
        .where(SessionMentor.user_id == mentor.id)
        .order_by(ProgrammeSession.starts_at)
    )
    return await _session_summaries(db, list(sessions))


def anonymous_id(session_id: uuid.UUID, mentee_id: uuid.UUID) -> str:
    """Stable per-session pseudonym, so responses can't be linked across sessions."""
    digest = hashlib.sha256(f"{session_id}:{mentee_id}".encode()).hexdigest()[:8]
    return f"Participant-{digest}"


async def session_feedback(
    db: AsyncSession, user: User, session: ProgrammeSession
) -> SessionFeedbackResponse:
    """Staff see who responded; the session's mentors see anonymous respondents."""
    staff = is_cohort_staff(user, session.cohort_id)
    if not (staff or is_session_mentor(user, session)):
        raise PermissionDenied(
            "Only staff and this session's mentors can view its feedback"
        )
    records = list(
        await db.scalars(
            select(AttendanceRecord).where(
                AttendanceRecord.session_id == session.id, ratings.rated()
            )
        )
    )
    names: dict[uuid.UUID, str] = {}
    if staff and records:
        names = {
            u.id: u.full_name
            for u in await db.scalars(
                select(User).where(User.id.in_([r.mentee_id for r in records]))
            )
        }
    _, values = await ratings.averages(db, AttendanceRecord.session_id == session.id)
    cohort = await get_cohort_or_404(db, session.cohort_id)
    return SessionFeedbackResponse(
        session_id=session.id,
        responses=len(records),
        anonymous=not staff,
        questions=ratings.describe(values, cohort),
        entries=[
            FeedbackEntry(
                respondent=names[r.mentee_id]
                if staff
                else anonymous_id(session.id, r.mentee_id),
                mentee_id=r.mentee_id if staff else None,
                ratings=r.ratings,
                feedback=r.feedback,
            )
            for r in records
        ],
    )
