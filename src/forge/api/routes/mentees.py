"""Per-mentee progress: points, attendance rates and graduation status."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from forge.api.deps import ActiveUser, DbSession
from forge.models import CohortEnrollment
from forge.schemas.mentorship import SkillProgressResponse
from forge.schemas.points import (
    AttendanceRateResponse,
    GraduationStatusResponse,
    PointsBreakdownResponse,
    PointsDetailResponse,
    RateBucket,
)
from forge.services import mentorship as mentorship_service
from forge.services import points as points_service
from forge.services.access import ensure_can_view_mentee, get_cohort_or_404
from forge.services.points import MenteeStats

router = APIRouter(prefix="/mentees/{mentee_id}", tags=["Mentee Progress"])


async def mentee_enrollment(
    mentee_id: UUID,
    user: ActiveUser,
    db: DbSession,
    cohort_id: Annotated[
        UUID | None, Query(description="Defaults to the mentee's most recent cohort")
    ] = None,
) -> CohortEnrollment:
    """The mentee's enrollment, if the caller is the mentee, their peer mentor, or cohort staff."""
    return await ensure_can_view_mentee(db, user, mentee_id, cohort_id)


MenteeEnrollment = Annotated[CohortEnrollment, Depends(mentee_enrollment)]


async def mentee_stats(enrollment: MenteeEnrollment, db: DbSession) -> MenteeStats:
    return await points_service.mentee_stats(db, enrollment)


Stats = Annotated[MenteeStats, Depends(mentee_stats)]


@router.get("/points")
async def get_points(stats: Stats) -> PointsBreakdownResponse:
    """Core points earned against points available so far, plus approved extra-activity points."""
    return points_service.breakdown(stats)


@router.get("/points/breakdown")
async def get_points_breakdown(stats: Stats, db: DbSession) -> PointsDetailResponse:
    """Per-session outcomes and the approved activities behind the totals."""
    return await points_service.detailed_breakdown(db, stats)


@router.get("/attendance-rates")
async def get_attendance_rates(stats: Stats) -> AttendanceRateResponse:
    """Core and combined rates, broken down by KamiLimu month, track and session type."""
    return points_service.rates(stats)


@router.get("/attendance-rates/monthly")
async def get_monthly_rates(stats: Stats) -> list[RateBucket]:
    """Attendance rate per KamiLimu month."""
    return points_service.rates(stats).by_month


@router.get("/attendance-rates/track")
async def get_track_rates(stats: Stats) -> list[RateBucket]:
    """Attendance rate per track (core and ICT)."""
    return points_service.rates(stats).by_track


@router.get("/graduation-status")
async def get_graduation_status(
    stats: Stats, enrollment: MenteeEnrollment, db: DbSession
) -> GraduationStatusResponse:
    """`on_track`, `warning` (within the warning margin above the threshold) or
    `at_risk`. Final once the cohort is completed: `graduated` or `not_graduated`."""
    cohort = await get_cohort_or_404(db, enrollment.cohort_id)
    return points_service.graduation(stats, cohort)


@router.get("/skill-progress")
async def get_skill_progress(
    enrollment: MenteeEnrollment, db: DbSession
) -> SkillProgressResponse:
    """The mentee's early, mid and late self-ratings and the change per skill."""
    return await mentorship_service.skill_progress(db, enrollment)
