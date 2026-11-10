"""Cohort leaderboard endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import Response

from forge.api.deps import ActiveUser, DbSession
from forge.api.routes.cohorts import MemberCohort, StaffedCohort, WritableCohort
from forge.core.exceptions import PermissionDenied
from forge.models import PEER_MENTOR_ROLES, LeaderboardKind, LeaderboardSnapshot
from forge.schemas.leaderboard import (
    DimensionRankingResponse,
    LeaderboardDimension,
    LeaderboardResponse,
    LeaderboardSnapshotResponse,
    PeerMentorDimension,
    PeerMentorLeaderboardResponse,
)
from forge.services import leaderboard as leaderboard_service
from forge.services.access import is_cohort_staff
from forge.services.exports import csv_response

router = APIRouter(prefix="/cohorts/{cohort_id}/leaderboard", tags=["Leaderboard"])


@router.get("")
async def get_leaderboard(
    cohort: MemberCohort, user: ActiveUser, db: DbSession
) -> LeaderboardResponse:
    """Mentees ranked by total points, with the five dimensions: core attendance,
    academic, events, applications (jobs and scholarships) and consultations.
    Names are always shown."""
    return await leaderboard_service.leaderboard(db, cohort, user)


@router.get(
    "/export",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "Leaderboard as CSV"}},
)
async def export_leaderboard(cohort: StaffedCohort, db: DbSession) -> Response:
    """Download the mentee leaderboard as CSV. **Staff of the cohort.**"""
    content = await leaderboard_service.leaderboard_csv(db, cohort)
    return csv_response(content, f"leaderboard-{cohort.name}")


@router.get("/peer-mentors")
async def get_peer_mentor_leaderboard(
    cohort: MemberCohort,
    user: ActiveUser,
    db: DbSession,
    ranked_by: PeerMentorDimension = PeerMentorDimension.OVERALL_RATE,
) -> PeerMentorLeaderboardResponse:
    """Peer mentors ranked by sessions attended, extra sessions logged, core rate
    or overall rate. **Peer mentors and staff.**"""
    if not (
        is_cohort_staff(user, cohort.id)
        or user.has_role(*PEER_MENTOR_ROLES, cohort_id=cohort.id)
    ):
        raise PermissionDenied("Peer mentors and staff only")
    return await leaderboard_service.peer_mentor_leaderboard(
        db, cohort, user, ranked_by
    )


@router.post(
    "/snapshots",
    status_code=status.HTTP_201_CREATED,
    response_model=list[LeaderboardSnapshotResponse],
)
async def take_snapshot(
    cohort: WritableCohort, user: ActiveUser, db: DbSession
) -> list[LeaderboardSnapshot]:
    """Save a point-in-time snapshot of both leaderboards. **System Admin or
    Program Lead.**"""
    return await leaderboard_service.take_snapshot(db, cohort, user)


@router.get("/snapshots", response_model=list[LeaderboardSnapshotResponse])
async def list_snapshots(
    cohort: StaffedCohort,
    db: DbSession,
    kind: Annotated[LeaderboardKind | None, Query()] = None,
) -> list[LeaderboardSnapshot]:
    """Saved leaderboard snapshots, newest first. **Staff of the cohort.**"""
    return await leaderboard_service.list_snapshots(db, cohort, kind)


@router.get("/{dimension}")
async def get_dimension_ranking(
    dimension: LeaderboardDimension,
    cohort: MemberCohort,
    user: ActiveUser,
    db: DbSession,
) -> DimensionRankingResponse:
    """Ranking on a single dimension (ties share a rank)."""
    return await leaderboard_service.dimension_ranking(db, cohort, user, dimension)
