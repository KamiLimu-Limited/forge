"""Role dashboards."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from forge.api.deps import (
    ActiveUser,
    DbSession,
    IctPeerMentorUser,
    ManagerUser,
    OneOnOnePeerMentorUser,
    ParticipantUser,
    ProfessionalMentorUser,
    ProgramLeadUser,
    StaffUser,
)
from forge.api.routes.sessions import VisibleSession
from forge.models import Cohort, CohortEnrollment, OverrideRequestStatus, User
from forge.schemas.activity import ActivityFilters, ExtraActivityResponse
from forge.schemas.analytics import (
    AttendanceTrendResponse,
    CohortHealthResponse,
    SessionQualityResponse,
    TrackPerformanceResponse,
)
from forge.schemas.attendance import OverrideFilters, OverrideRequestResponse
from forge.schemas.common import Page, PageParams
from forge.schemas.dashboard import (
    GroupOverview,
    MenteeDrilldown,
    MenteeOverview,
    SessionAttendanceSummary,
    SessionFeedbackResponse,
    TrackOverview,
)
from forge.schemas.graduation import GraduationPanel
from forge.schemas.points import RateBucket, SessionPointsEntry
from forge.services import activities as activity_service
from forge.services import analytics as analytics_service
from forge.services import attendance as attendance_service
from forge.services import dashboard as dashboard_service
from forge.services import graduation as graduation_service
from forge.services import points as points_service
from forge.services.access import (
    ensure_cohort_staff,
    get_participant_enrollment_or_404,
)
from forge.services.cohorts import get_visible_cohort

router = APIRouter(prefix="/dashboard", tags=["Dashboards"])
feedback_router = APIRouter(tags=["Dashboards"])

CohortParam = Annotated[
    UUID | None, Query(description="Defaults to your most recent cohort")
]


async def participant_enrollment(
    user: ParticipantUser, db: DbSession, cohort_id: CohortParam = None
) -> CohortEnrollment:
    return await get_participant_enrollment_or_404(db, user.id, cohort_id)


OwnEnrollment = Annotated[CohortEnrollment, Depends(participant_enrollment)]


class OverrideQueueParams(PageParams):
    cohort_id: UUID | None = None


async def resolve_committee_cohort(
    db: AsyncSession, user: User, cohort_id: UUID
) -> Cohort:
    cohort = await get_visible_cohort(db, user, cohort_id)
    ensure_cohort_staff(user, cohort.id)
    return cohort


async def committee_cohort(
    user: StaffUser, db: DbSession, cohort_id: Annotated[UUID, Query()]
) -> Cohort:
    return await resolve_committee_cohort(db, user, cohort_id)


CommitteeCohort = Annotated[Cohort, Depends(committee_cohort)]


# Mentee (also used by peer mentors for their own participation)


@router.get("/mentee/overview")
async def mentee_overview(
    user: ParticipantUser, enrollment: OwnEnrollment, db: DbSession
) -> MenteeOverview:
    """Headline numbers: core and overall rate, points with the missed and
    remaining buckets, the next session, and anything needing action (open windows,
    pending extension requests, unread notifications). **Mentees and peer mentors.**"""
    return await dashboard_service.mentee_overview(db, user, enrollment)


@router.get("/mentee/attendance/monthly")
async def mentee_monthly(enrollment: OwnEnrollment, db: DbSession) -> list[RateBucket]:
    """Your attendance rate per KamiLimu month."""
    return points_service.rates(
        await points_service.mentee_stats(db, enrollment)
    ).by_month


@router.get("/mentee/attendance/track")
async def mentee_by_track(enrollment: OwnEnrollment, db: DbSession) -> list[RateBucket]:
    """Your attendance rate per track (core and ICT)."""
    return points_service.rates(
        await points_service.mentee_stats(db, enrollment)
    ).by_track


@router.get("/mentee/attendance/history")
async def mentee_history(
    enrollment: OwnEnrollment,
    db: DbSession,
    kami_limu_month: Annotated[int | None, Query(ge=1, le=24)] = None,
) -> list[SessionPointsEntry]:
    """Every session that applies to you with its outcome, most recent first,
    optionally for one KamiLimu month."""
    stats = await points_service.mentee_stats(db, enrollment)
    sessions = [
        s
        for s in stats.sessions
        if kami_limu_month is None or s.kami_limu_month == kami_limu_month
    ]
    return sorted(sessions, key=lambda s: s.starts_at, reverse=True)


@router.get("/mentee/extra-activities")
async def mentee_activities(
    filters: Annotated[ActivityFilters, Query()], user: ParticipantUser, db: DbSession
) -> Page[ExtraActivityResponse]:
    """Your extra-activity log across the five log types."""
    activities, total = await activity_service.list_activities(
        db, user, filters, mine=True
    )
    return Page[ExtraActivityResponse].build(activities, total, filters)


# 1:1 peer mentor


@router.get("/peer-mentor/group")
async def peer_mentor_group(
    mentor: OneOnOnePeerMentorUser, db: DbSession, cohort_id: CohortParam = None
) -> GroupOverview:
    """Your mentees' core rate, overall rate and points, lowest core rate first."""
    return await dashboard_service.group_overview(db, mentor, cohort_id)


@router.get("/peer-mentor/mentees/{mentee_id}")
async def peer_mentor_mentee(
    mentee_id: UUID,
    mentor: OneOnOnePeerMentorUser,
    db: DbSession,
    cohort_id: CohortParam = None,
) -> MenteeDrilldown:
    """Full read-only drill-down on one mentee in your group, including their
    objectives and their session ratings and feedback."""
    return await dashboard_service.mentee_drilldown(db, mentor, mentee_id, cohort_id)


# ICT peer mentor


@router.get("/ict-peer-mentor/track-overview")
async def ict_track_overview(
    mentor: IctPeerMentorUser, db: DbSession, cohort_id: CohortParam = None
) -> TrackOverview:
    """Mentees on your ICT track with their track attendance."""
    return await dashboard_service.track_overview(db, mentor, cohort_id)


@router.get("/ict-peer-mentor/sessions")
async def ict_track_sessions(
    mentor: IctPeerMentorUser, db: DbSession, cohort_id: CohortParam = None
) -> list[SessionAttendanceSummary]:
    """Your track's sessions with attendance and average quality."""
    return await dashboard_service.ict_sessions(db, mentor, cohort_id)


# Professional mentor


@router.get("/professional-mentor/sessions")
async def professional_mentor_sessions(
    mentor: ProfessionalMentorUser, db: DbSession
) -> list[SessionAttendanceSummary]:
    """Sessions you lead or co-mentor, with attendance and the average of each of
    the nine rating questions."""
    return await dashboard_service.professional_mentor_sessions(db, mentor)


@feedback_router.get("/sessions/{session_id}/feedback")
async def session_feedback(
    session: VisibleSession, user: ActiveUser, db: DbSession
) -> SessionFeedbackResponse:
    """Average of each of the nine rating questions, and each attendee's ratings
    and feedback. **Staff and the session's mentors**; respondents are anonymous
    for mentors."""
    return await dashboard_service.session_feedback(db, user, session)


# Committee


@router.get("/committee/cohort-health")
async def cohort_health(cohort: CommitteeCohort, db: DbSession) -> CohortHealthResponse:
    """Programme-wide summary: enrolment, average rates, points distributed,
    sessions completed and the pending extension requests."""
    return await analytics_service.cohort_health(db, cohort)


@router.get("/committee/analytics/attendance-trends")
async def committee_attendance_trends(
    cohort: CommitteeCohort, db: DbSession
) -> AttendanceTrendResponse:
    """Cohort-wide attendance rate per KamiLimu month."""
    return await analytics_service.attendance_trends(db, cohort)


@router.get("/committee/analytics/track-performance")
async def committee_track_performance(
    cohort: CommitteeCohort, db: DbSession
) -> TrackPerformanceResponse:
    """Attendance per track across the cohort."""
    return await analytics_service.track_performance(db, cohort)


@router.get("/committee/analytics/session-quality")
async def committee_session_quality(
    cohort: CommitteeCohort, db: DbSession
) -> SessionQualityResponse:
    """Average feedback ratings per session."""
    return await analytics_service.session_quality(db, cohort)


# System Admin


@router.get("/admin/override-queue")
async def override_queue(
    params: Annotated[OverrideQueueParams, Query()], user: ManagerUser, db: DbSession
) -> Page[OverrideRequestResponse]:
    """Pending window extension requests, optionally for one cohort.
    **System Admin or Program Lead.**"""
    filters = OverrideFilters(
        page=params.page,
        page_size=params.page_size,
        cohort_id=params.cohort_id,
        status=OverrideRequestStatus.PENDING,
    )
    requests, total = await attendance_service.list_override_requests(db, user, filters)
    return Page[OverrideRequestResponse].build(requests, total, filters)


# Program Lead


@router.get("/program-lead/graduation")
async def graduation_panel(
    user: ProgramLeadUser, db: DbSession, cohort_id: Annotated[UUID, Query()]
) -> GraduationPanel:
    """The graduation panel: the preview, whether the cohort has graduated and
    whether Graduate Cohort is available (with the reasons when it is not).
    **Program Lead.**"""
    cohort = await get_visible_cohort(db, user, cohort_id)
    return await graduation_service.panel(db, cohort)
