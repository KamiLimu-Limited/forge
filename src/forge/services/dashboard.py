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
    Cohort,
    CohortEnrollment,
    CohortStatus,
    ExtraActivity,
    OverrideRequest,
    OverrideRequestStatus,
    PeerMentorNote,
    PeerMentorTask,
    ProgrammeSession,
    SessionMentor,
    SessionStatus,
    SubmissionStatus,
    TaskSubmission,
    User,
    UserRole,
)
from forge.schemas.activity import activity_adapter
from forge.schemas.attendance import SessionBrief
from forge.schemas.dashboard import (
    FeedbackEntry,
    GroupOverview,
    MenteeDrilldown,
    MenteeOverview,
    MenteeSummary,
    SessionAttendanceSummary,
    SessionFeedbackResponse,
    TaskCompletion,
    TrackMenteeSummary,
    TrackOverview,
)
from forge.schemas.points import GraduationStatus
from forge.schemas.user import UserSummary
from forge.services.access import get_cohort_or_404, get_enrollment, is_cohort_staff
from forge.services.eligibility import COUNTED_STATUSES, applies_to_enrollment
from forge.services.notifications import unread_count
from forge.services.points import (
    MenteeStats,
    breakdown,
    compute_stats,
    detailed_breakdown,
    graduation,
    rates,
)
from forge.services.sessions import is_session_mentor
from forge.services.windows import is_open

RATING_FIELDS = ("quality_rating", "usefulness_rating", "understanding_score")


def summarize(
    enrollment: CohortEnrollment, stats: MenteeStats, cohort: Cohort
) -> MenteeSummary:
    return MenteeSummary(
        mentee=UserSummary.model_validate(enrollment.user),
        ict_track=enrollment.ict_track,
        total_points=stats.total_points,
        core_rate=stats.core_rate,
        combined_rate=stats.combined_rate,
        status=stats.graduation_status(
            cohort.graduation_threshold, cohort.status is CohortStatus.COMPLETED
        ),
        sessions_attended=stats.total.attended,
        sessions_due=stats.total.due,
    )


async def mentee_overview(
    db: AsyncSession, mentee: User, enrollment: CohortEnrollment
) -> MenteeOverview:
    cohort = await get_cohort_or_404(db, enrollment.cohort_id)
    stats = (await compute_stats(db, cohort.id, [mentee.id]))[mentee.id]
    now = datetime.now(UTC)

    upcoming = await db.scalars(
        select(ProgrammeSession)
        .join(CohortEnrollment, applies_to_enrollment())
        .where(
            CohortEnrollment.id == enrollment.id,
            ProgrammeSession.status == SessionStatus.PUBLISHED,
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
                    AttendanceRecord.mentee_id == mentee.id,
                    AttendanceRecord.status != AttendanceStatus.MISSED,
                )
            ),
        )
    )
    pending_overrides = await db.scalar(
        select(func.count()).where(
            OverrideRequest.mentee_id == mentee.id,
            OverrideRequest.status == OverrideRequestStatus.PENDING,
        )
    )
    next_session = upcoming.first()
    return MenteeOverview(
        cohort_id=cohort.id,
        points=breakdown(stats),
        graduation=graduation(stats, cohort),
        next_session=SessionBrief.model_validate(next_session)
        if next_session
        else None,
        open_attendance_windows=sum(is_open(w, mentee.id, now) for w in windows),
        pending_override_requests=pending_overrides or 0,
        unread_notifications=await unread_count(db, mentee),
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
        (summarize(e, stats[e.user_id], cohort) for e in group),
        key=lambda s: s.combined_rate,
    )
    return GroupOverview(
        cohort_id=cohort.id,
        mentees=summaries,
        average_combined_rate=round(fmean(s.combined_rate for s in summaries), 2)
        if summaries
        else 0.0,
        at_risk=sum(s.status is GraduationStatus.AT_RISK for s in summaries),
        warning=sum(s.status is GraduationStatus.WARNING for s in summaries),
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
    notes = await db.scalar(
        select(func.count()).where(
            PeerMentorNote.peer_mentor_id == mentor.id,
            PeerMentorNote.mentee_id == mentee_id,
        )
    )
    tasks = await db.scalar(
        select(func.count()).where(
            PeerMentorTask.peer_mentor_id == mentor.id,
            PeerMentorTask.cohort_id == cohort.id,
        )
    )
    completed = await db.scalar(
        select(func.count())
        .select_from(TaskSubmission)
        .join(PeerMentorTask, PeerMentorTask.id == TaskSubmission.task_id)
        .where(
            PeerMentorTask.peer_mentor_id == mentor.id,
            TaskSubmission.mentee_id == mentee_id,
            TaskSubmission.submission_status == SubmissionStatus.COMPLETED,
        )
    )
    return MenteeDrilldown(
        summary=summarize(enrollment, stats, cohort),
        points=await detailed_breakdown(db, stats),
        rates=rates(stats),
        graduation=graduation(stats, cohort),
        recent_activities=[
            activity_adapter.validate_python(a, from_attributes=True)
            for a in activities
        ],
        notes=notes or 0,
        tasks=TaskCompletion(completed=completed or 0, total=tasks or 0),
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
    final = cohort.status is CohortStatus.COMPLETED
    return TrackOverview(
        cohort_id=cohort.id,
        track=own.ict_track,
        mentees=[
            TrackMenteeSummary(
                mentee=UserSummary.model_validate(e.user),
                track=stats[e.user_id].by_track[own.ict_track].bucket(own.ict_track),
                combined_rate=stats[e.user_id].combined_rate,
                status=stats[e.user_id].graduation_status(
                    cohort.graduation_threshold, final
                ),
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
    attendance = {
        sid: (attended, responses, avg)
        for sid, attended, responses, avg in await db.execute(
            select(
                AttendanceRecord.session_id,
                func.count().filter(
                    AttendanceRecord.status == AttendanceStatus.ATTENDED
                ),
                func.count(AttendanceRecord.quality_rating),
                func.avg(AttendanceRecord.quality_rating),
            )
            .where(AttendanceRecord.session_id.in_(ids))
            .group_by(AttendanceRecord.session_id)
        )
    }
    result = []
    for s in sessions:
        attended, responses, avg = attendance.get(s.id, (0, 0, None))
        result.append(
            SessionAttendanceSummary(
                session=SessionBrief.model_validate(s),
                eligible=eligible.get(s.id, 0),
                attended=attended,
                responses=responses,
                average_quality=round(float(avg), 2) if avg is not None else None,
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
    return f"Mentee-{digest}"


async def session_feedback(
    db: AsyncSession, user: User, session: ProgrammeSession
) -> SessionFeedbackResponse:
    if not (
        is_cohort_staff(user, session.cohort_id) or is_session_mentor(user, session)
    ):
        raise PermissionDenied(
            "Only staff and this session's mentors can view its feedback"
        )
    records = list(
        await db.scalars(
            select(AttendanceRecord).where(
                AttendanceRecord.session_id == session.id,
                AttendanceRecord.status == AttendanceStatus.ATTENDED,
            )
        )
    )
    averages: dict[str, float | None] = {}
    for f in RATING_FIELDS:
        values = [v for r in records if (v := getattr(r, f)) is not None]
        averages[f] = round(fmean(values), 2) if values else None
    return SessionFeedbackResponse(
        session_id=session.id,
        responses=len(records),
        averages=averages,
        entries=[
            FeedbackEntry(
                respondent=anonymous_id(session.id, r.mentee_id),
                quality_rating=r.quality_rating,
                usefulness_rating=r.usefulness_rating,
                understanding_score=r.understanding_score,
                feedback=r.feedback,
            )
            for r in records
        ],
    )
