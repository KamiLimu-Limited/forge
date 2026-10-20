"""Role dashboards."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from forge.api.deps import (
    ActiveUser,
    CommitteeUser,
    DbSession,
    IctPeerMentorUser,
    MenteeUser,
    OneOnOnePeerMentorUser,
    ProfessionalMentorUser,
)
from forge.api.routes.sessions import VisibleSession
from forge.models import (
    ActivityStatus,
    Cohort,
    CohortEnrollment,
    OverrideRequestStatus,
    User,
)
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
    MenteeSummary,
    SessionAttendanceSummary,
    SessionFeedbackResponse,
    TrackOverview,
)
from forge.schemas.points import GraduationStatus, RateBucket, SessionPointsEntry
from forge.services import activities as activity_service
from forge.services import analytics as analytics_service
from forge.services import attendance as attendance_service
from forge.services import dashboard as dashboard_service
from forge.services import points as points_service
from forge.services.access import ensure_cohort_staff, get_mentee_enrollment_or_404
from forge.services.cohorts import get_visible_cohort

router = APIRouter(prefix="/dashboard", tags=["Dashboards"])
feedback_router = APIRouter(tags=["Dashboards"])

CohortParam = Annotated[
    UUID | None, Query(description="Defaults to your most recent cohort")
]


async def mentee_enrollment(
    mentee: MenteeUser, db: DbSession, cohort_id: CohortParam = None
) -> CohortEnrollment:
    return await get_mentee_enrollment_or_404(db, mentee.id, cohort_id)


OwnEnrollment = Annotated[CohortEnrollment, Depends(mentee_enrollment)]


class CohortQueueParams(PageParams):
    cohort_id: UUID


async def resolve_committee_cohort(
    db: AsyncSession, user: User, cohort_id: UUID
) -> Cohort:
    cohort = await get_visible_cohort(db, user, cohort_id)
    ensure_cohort_staff(user, cohort.id)
    return cohort


async def committee_cohort(
    user: CommitteeUser, db: DbSession, cohort_id: Annotated[UUID, Query()]
) -> Cohort:
    return await resolve_committee_cohort(db, user, cohort_id)


CommitteeCohort = Annotated[Cohort, Depends(committee_cohort)]


# Mentee


@router.get("/mentee/overview")
async def mentee_overview(
    mentee: MenteeUser, enrollment: OwnEnrollment, db: DbSession
) -> MenteeOverview:
    """Headline numbers: attendance and graduation status, points, next session and
    anything needing action (open windows, pending overrides, unread notifications)."""
    return await dashboard_service.mentee_overview(db, mentee, enrollment)


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
    enrollment: OwnEnrollment, db: DbSession
) -> list[SessionPointsEntry]:
    """Every counted session with its outcome, most recent first."""
    stats = await points_service.mentee_stats(db, enrollment)
    return sorted(stats.sessions, key=lambda s: s.starts_at, reverse=True)


@router.get("/mentee/extra-activities")
async def mentee_activities(
    filters: Annotated[ActivityFilters, Query()], mentee: MenteeUser, db: DbSession
) -> Page[ExtraActivityResponse]:
    """Your extra-activity log."""
    activities, total = await activity_service.list_activities(
        db, mentee, filters, mine=True
    )
    return Page[ExtraActivityResponse].build(activities, total, filters)


# 1:1 peer mentor


@router.get("/peer-mentor/group")
async def peer_mentor_group(
    mentor: OneOnOnePeerMentorUser, db: DbSession, cohort_id: CohortParam = None
) -> GroupOverview:
    """Your mentees' points, rates and graduation status, lowest rate first."""
    return await dashboard_service.group_overview(db, mentor, cohort_id)


@router.get("/peer-mentor/mentees/{mentee_id}")
async def peer_mentor_mentee(
    mentee_id: UUID,
    mentor: OneOnOnePeerMentorUser,
    db: DbSession,
    cohort_id: CohortParam = None,
) -> MenteeDrilldown:
    """Full drill-down on one mentee in your group."""
    return await dashboard_service.mentee_drilldown(db, mentor, mentee_id, cohort_id)


@router.get("/peer-mentor/at-risk")
async def peer_mentor_at_risk(
    mentor: OneOnOnePeerMentorUser, db: DbSession, cohort_id: CohortParam = None
) -> list[MenteeSummary]:
    """Mentees in your group with `warning` or `at_risk` status."""
    group = await dashboard_service.group_overview(db, mentor, cohort_id)
    return [
        m
        for m in group.mentees
        if m.status in (GraduationStatus.WARNING, GraduationStatus.AT_RISK)
    ]


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
    """Sessions you lead or co-mentor, with attendance and feedback summaries."""
    return await dashboard_service.professional_mentor_sessions(db, mentor)


@feedback_router.get("/sessions/{session_id}/feedback")
async def session_feedback(
    session: VisibleSession, user: ActiveUser, db: DbSession
) -> SessionFeedbackResponse:
    """Average ratings and feedback from attendees, with anonymous respondent ids.
    **Staff and the session's mentors.**"""
    return await dashboard_service.session_feedback(db, user, session)


# Committee


@router.get("/committee/cohort-health")
async def cohort_health(cohort: CommitteeCohort, db: DbSession) -> CohortHealthResponse:
    """Programme-wide summary: status counts, average rates and review queues."""
    return await analytics_service.cohort_health(db, cohort)


@router.get("/committee/override-queue")
async def override_queue(
    params: Annotated[CohortQueueParams, Query()], user: CommitteeUser, db: DbSession
) -> Page[OverrideRequestResponse]:
    """Pending attendance override requests for the cohort."""
    cohort = await resolve_committee_cohort(db, user, params.cohort_id)
    filters = OverrideFilters(
        page=params.page,
        page_size=params.page_size,
        cohort_id=cohort.id,
        status=OverrideRequestStatus.PENDING,
    )
    requests, total = await attendance_service.list_override_requests(db, user, filters)
    return Page[OverrideRequestResponse].build(requests, total, filters)


@router.get("/committee/activities-queue")
async def activities_queue(
    params: Annotated[CohortQueueParams, Query()], user: CommitteeUser, db: DbSession
) -> Page[ExtraActivityResponse]:
    """Extra activities awaiting validation in the cohort."""
    cohort = await resolve_committee_cohort(db, user, params.cohort_id)
    filters = ActivityFilters(
        page=params.page,
        page_size=params.page_size,
        cohort_id=cohort.id,
        status=ActivityStatus.PENDING,
    )
    activities, total = await activity_service.list_activities(db, user, filters)
    return Page[ExtraActivityResponse].build(activities, total, filters)


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
