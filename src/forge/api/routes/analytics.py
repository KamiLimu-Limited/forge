"""Analytics and CSV export endpoints."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import Response
from sqlalchemy import select

from forge.api.deps import DbSession, StaffUser
from forge.api.routes.cohorts import ManagedCohort, StaffedCohort
from forge.core.exceptions import NotFound
from forge.models import Cohort, CohortAnalyticsSnapshot, LeaderboardKind
from forge.schemas.analytics import (
    ActivityEngagementResponse,
    AttendanceTrendResponse,
    CrossCohortResponse,
    HealthTrajectoryResponse,
    SessionQualityResponse,
    SnapshotResponse,
    TrackPerformanceResponse,
)
from forge.services import analytics as analytics_service
from forge.services import exports as export_service
from forge.services import leaderboard as leaderboard_service
from forge.services.access import ensure_cohort_staff

router = APIRouter(prefix="/analytics/cohorts/{cohort_id}", tags=["Analytics"])
cross_router = APIRouter(prefix="/analytics", tags=["Analytics"])
exports_router = APIRouter(prefix="/exports", tags=["Exports"])

CSV_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {"content": {"text/csv": {}}, "description": "CSV file download"}
}


@router.get("/attendance-trends")
async def attendance_trends(
    cohort: StaffedCohort, db: DbSession
) -> AttendanceTrendResponse:
    """Cohort-wide attendance rate per KamiLimu month."""
    return await analytics_service.attendance_trends(db, cohort)


@router.get("/track-performance")
async def track_performance(
    cohort: StaffedCohort, db: DbSession
) -> TrackPerformanceResponse:
    """Attendance per track (core and each ICT track)."""
    return await analytics_service.track_performance(db, cohort)


@router.get("/session-quality")
async def session_quality(
    cohort: StaffedCohort, db: DbSession
) -> SessionQualityResponse:
    """Average of each of the nine rating questions, per session and cohort-wide."""
    return await analytics_service.session_quality(db, cohort)


@router.get("/health-trajectory")
async def health_trajectory(
    cohort: StaffedCohort, db: DbSession
) -> HealthTrajectoryResponse:
    """Average core and overall rates, and how many mentees met the graduation
    threshold on their core rate, at the end of each KamiLimu month."""
    return await analytics_service.health_trajectory(db, cohort)


@router.get("/extra-activities")
async def activity_engagement(
    cohort: StaffedCohort, db: DbSession
) -> ActivityEngagementResponse:
    """Extra-activity volume (active and reversed), points and participation for
    each of the five log types."""
    return await analytics_service.activity_engagement(db, cohort)


@router.post(
    "/snapshots", status_code=status.HTTP_201_CREATED, response_model=SnapshotResponse
)
async def take_snapshot(
    cohort: ManagedCohort, db: DbSession
) -> CohortAnalyticsSnapshot:
    """Store today's metrics now (a daily snapshot is also taken automatically).
    **System Admin or Program Lead.**"""
    return await analytics_service.take_snapshot(db, cohort)


@router.get("/snapshots", response_model=list[SnapshotResponse])
async def list_snapshots(
    cohort: StaffedCohort, db: DbSession
) -> list[CohortAnalyticsSnapshot]:
    """Stored daily metric snapshots for the cohort, oldest first."""
    return await analytics_service.list_snapshots(db, cohort)


@cross_router.get("/cross-cohort")
async def cross_cohort(
    user: StaffUser,
    db: DbSession,
    cohort_ids: Annotated[list[UUID], Query(min_length=1, max_length=20)],
) -> CrossCohortResponse:
    """Compare health and engagement across cohorts you can manage."""
    cohorts = list(await db.scalars(select(Cohort).where(Cohort.id.in_(cohort_ids))))
    if len(cohorts) != len(set(cohort_ids)):
        raise NotFound("One or more cohorts not found")
    for cohort in cohorts:
        ensure_cohort_staff(user, cohort.id)
    return await analytics_service.cross_cohort(
        db, sorted(cohorts, key=lambda c: c.start_date)
    )


@exports_router.post(
    "/leaderboard/{cohort_id}", response_class=Response, responses=CSV_RESPONSE
)
async def export_leaderboard(
    cohort: StaffedCohort,
    db: DbSession,
    board: LeaderboardKind = LeaderboardKind.MENTEE,
) -> Response:
    """The cohort's mentee or peer mentor leaderboard as CSV."""
    return export_service.csv_response(
        await leaderboard_service.leaderboard_csv(db, cohort, board),
        f"leaderboard-{board.value}-{cohort.name}",
    )


@exports_router.post(
    "/attendance/{cohort_id}", response_class=Response, responses=CSV_RESPONSE
)
async def export_attendance(cohort: StaffedCohort, db: DbSession) -> Response:
    """Every mentee × session outcome with the nine ratings."""
    return export_service.csv_response(
        await export_service.attendance_csv(db, cohort), f"attendance-{cohort.name}"
    )


@exports_router.post(
    "/full-report/{cohort_id}", response_class=Response, responses=CSV_RESPONSE
)
async def export_full_report(cohort: StaffedCohort, db: DbSession) -> Response:
    """One row per mentee: points, core and overall rates, graduation status and
    active activities."""
    return export_service.csv_response(
        await export_service.full_report_csv(db, cohort), f"report-{cohort.name}"
    )
