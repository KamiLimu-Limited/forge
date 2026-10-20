"""Leaderboard and competition endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response

from forge.api.deps import ActiveUser, CommitteeUser, DbSession
from forge.api.routes.cohorts import MemberCohort, StaffedCohort
from forge.api.routes.mentees import MenteeEnrollment
from forge.models import Cohort, Competition, CompetitionEntry, CompetitionRound
from forge.schemas.cohort import CohortResponse
from forge.schemas.common import Page
from forge.schemas.competition import (
    CompetitionCreateRequest,
    CompetitionFilters,
    CompetitionResponse,
    CompetitionStatusEntry,
    CompetitionUpdateRequest,
    DimensionRankingResponse,
    EntriesCreateRequest,
    EntryResponse,
    EntryUpdateRequest,
    LeaderboardDimension,
    LeaderboardResponse,
    LeaderboardSettings,
    RoundCreateRequest,
    RoundResponse,
    RoundUpdateRequest,
)
from forge.services import competitions as competition_service
from forge.services import leaderboard as leaderboard_service
from forge.services.exports import csv_response

router = APIRouter(tags=["Leaderboard & Competitions"])


async def visible_competition(
    competition_id: UUID, user: ActiveUser, db: DbSession
) -> Competition:
    return await competition_service.get_visible_competition(db, user, competition_id)


VisibleCompetition = Annotated[Competition, Depends(visible_competition)]


@router.get("/cohorts/{cohort_id}/leaderboard")
async def get_leaderboard(
    cohort: MemberCohort, user: ActiveUser, db: DbSession
) -> LeaderboardResponse:
    """Mentees ranked by total points, with all six dimensions: core attendance,
    graduation rate, academic, events, opportunities and consultations. When the
    cohort's leaderboard is anonymous, other mentees' names are hidden from non-staff."""
    return await leaderboard_service.leaderboard(db, cohort, user)


@router.get(
    "/cohorts/{cohort_id}/leaderboard/export",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "Leaderboard as CSV"}},
)
async def export_leaderboard(
    cohort: StaffedCohort, user: ActiveUser, db: DbSession
) -> Response:
    """Download the leaderboard as CSV. **Committee of the cohort.**"""
    content = await leaderboard_service.leaderboard_csv(db, cohort, user)
    return csv_response(content, f"leaderboard-{cohort.name}")


@router.patch(
    "/cohorts/{cohort_id}/leaderboard/settings", response_model=CohortResponse
)
async def update_leaderboard_settings(
    data: LeaderboardSettings, cohort: StaffedCohort, db: DbSession
) -> Cohort:
    """Toggle leaderboard anonymity. **Committee of the cohort.**"""
    cohort.leaderboard_anonymous = data.leaderboard_anonymous
    await db.commit()
    await db.refresh(cohort)
    return cohort


@router.get("/cohorts/{cohort_id}/leaderboard/{dimension}")
async def get_dimension_ranking(
    dimension: LeaderboardDimension,
    cohort: MemberCohort,
    user: ActiveUser,
    db: DbSession,
) -> DimensionRankingResponse:
    """Ranking on a single dimension (ties share a rank)."""
    return await leaderboard_service.dimension_ranking(db, cohort, user, dimension)


@router.post(
    "/competitions",
    status_code=status.HTTP_201_CREATED,
    response_model=CompetitionResponse,
)
async def create_competition(
    data: CompetitionCreateRequest, user: CommitteeUser, db: DbSession
) -> Competition:
    """Create a competition (innovation, public speaking, scholarship, professional). **Committee.**"""
    return await competition_service.create_competition(db, user, data)


@router.get("/competitions")
async def list_competitions(
    filters: Annotated[CompetitionFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[CompetitionResponse]:
    """Competitions in cohorts you belong to."""
    competitions, total = await competition_service.list_competitions(db, user, filters)
    return Page[CompetitionResponse].build(competitions, total, filters)


@router.get("/competitions/{competition_id}", response_model=CompetitionResponse)
async def get_competition(competition: VisibleCompetition) -> Competition:
    """A competition with its rounds."""
    return competition


@router.patch("/competitions/{competition_id}", response_model=CompetitionResponse)
async def update_competition(
    data: CompetitionUpdateRequest,
    competition: VisibleCompetition,
    user: CommitteeUser,
    db: DbSession,
) -> Competition:
    """Update a competition's details or status. **Committee.**"""
    return await competition_service.update_competition(db, user, competition, data)


@router.post(
    "/competitions/{competition_id}/rounds",
    status_code=status.HTTP_201_CREATED,
    response_model=RoundResponse,
)
async def create_round(
    data: RoundCreateRequest,
    competition: VisibleCompetition,
    user: CommitteeUser,
    db: DbSession,
) -> CompetitionRound:
    """Add a numbered round to a competition. **Committee.**"""
    return await competition_service.add_round(db, user, competition, data)


@router.patch("/rounds/{round_id}", response_model=RoundResponse)
async def update_round(
    round_id: UUID, data: RoundUpdateRequest, user: CommitteeUser, db: DbSession
) -> CompetitionRound:
    """Rename, reschedule or change a round's status. **Committee.**"""
    return await competition_service.update_round(db, user, round_id, data)


@router.post(
    "/competitions/{competition_id}/entries",
    status_code=status.HTTP_201_CREATED,
    response_model=list[EntryResponse],
)
async def create_entries(
    data: EntriesCreateRequest,
    competition: VisibleCompetition,
    user: CommitteeUser,
    db: DbSession,
) -> list[CompetitionEntry]:
    """Register individual or team entries. All members must be mentees of the cohort."""
    return await competition_service.add_entries(db, user, competition, data.entries)


@router.get(
    "/competitions/{competition_id}/entries", response_model=list[EntryResponse]
)
async def list_entries(
    competition: VisibleCompetition, user: ActiveUser, db: DbSession
) -> list[CompetitionEntry]:
    """Committee sees every entry; mentees their own; peer mentors their group's."""
    return await competition_service.list_entries(db, user, competition)


@router.patch("/entries/{entry_id}", response_model=EntryResponse)
async def update_entry(
    entry_id: UUID, data: EntryUpdateRequest, user: CommitteeUser, db: DbSession
) -> CompetitionEntry:
    """Advance, eliminate or record a result for an entry. **Committee.**"""
    return await competition_service.update_entry(db, user, entry_id, data)


@router.get("/mentees/{mentee_id}/competition-status", tags=["Mentee Progress"])
async def mentee_competition_status(
    enrollment: MenteeEnrollment, db: DbSession
) -> list[CompetitionStatusEntry]:
    """Every competition the mentee entered (individually or in a team) and where they stand."""
    return await competition_service.mentee_competition_status(
        db, enrollment.user_id, enrollment.cohort_id
    )
