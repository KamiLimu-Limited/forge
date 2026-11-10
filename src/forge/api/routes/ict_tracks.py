"""ICT tracks offered in a cohort and mentees' track selection."""

from uuid import UUID

from fastapi import APIRouter

from forge.api.deps import ActiveUser, DbSession, MenteeUser
from forge.api.routes.cohorts import ManagedCohort, MemberCohort, WritableCohort
from forge.models import CohortIctTrack
from forge.schemas.cohort import (
    IctTrackResponse,
    IctTracksRequest,
    TrackChoiceRequest,
    TrackOverrideRequest,
    TrackSelectionResponse,
    TrackSelectionSummary,
    TrackSelectionWindow,
    TrackSelectionWindowRequest,
)
from forge.services import ict_tracks as track_service

router = APIRouter(prefix="/cohorts/{cohort_id}", tags=["ICT Tracks"])


@router.get("/ict-tracks", response_model=list[IctTrackResponse])
async def list_tracks(cohort: MemberCohort) -> list[CohortIctTrack]:
    """The ICT tracks offered in the cohort, each with its lead mentor."""
    return cohort.ict_tracks


@router.put("/ict-tracks", response_model=list[IctTrackResponse])
async def set_tracks(
    data: IctTracksRequest, cohort: WritableCohort, user: ActiveUser, db: DbSession
) -> list[CohortIctTrack]:
    """Replace the tracks offered and their lead mentors, who must be ICT peer
    mentors in the cohort. A track mentees have chosen cannot be removed.
    **System Admin or Program Lead.**"""
    return await track_service.set_tracks(db, cohort, data, user)


@router.get("/ict-track-selection")
async def get_selection(
    cohort: MemberCohort, user: MenteeUser, db: DbSession
) -> TrackSelectionResponse:
    """The selection window and the caller's current choice."""
    return await track_service.selection(db, cohort, user)


@router.put("/ict-track-selection/window")
async def set_window(
    data: TrackSelectionWindowRequest,
    cohort: WritableCohort,
    user: ActiveUser,
    db: DbSession,
) -> TrackSelectionWindow:
    """Open, move or close (both dates null) the track selection window.
    **System Admin or Program Lead.**"""
    return await track_service.set_window(db, cohort, data, user)


@router.put("/ict-track-selection/me")
async def choose_track(
    data: TrackChoiceRequest, cohort: MemberCohort, user: MenteeUser, db: DbSession
) -> TrackSelectionResponse:
    """Submit or change the caller's track while the window is open."""
    return await track_service.choose(db, cohort, user, data.ict_track)


@router.get("/ict-track-selection/summary")
async def selection_summary(
    cohort: ManagedCohort, db: DbSession
) -> TrackSelectionSummary:
    """Mentees per track, and the mentees who have not selected yet.
    **System Admin or Program Lead.**"""
    return await track_service.summary(db, cohort)


@router.put("/ict-track-selection/{mentee_id}")
async def override_track(
    mentee_id: UUID,
    data: TrackOverrideRequest,
    cohort: WritableCohort,
    user: ActiveUser,
    db: DbSession,
) -> TrackSelectionResponse:
    """Set a mentee's track on their behalf, including after the window closes.
    Writes an audit entry. **System Admin or Program Lead.**"""
    return await track_service.override(
        db, cohort, mentee_id, data.ict_track, data.reason, user
    )
