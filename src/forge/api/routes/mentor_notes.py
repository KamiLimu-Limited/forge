"""Private peer mentor notes and ICT progress notes.

Phase 2: this router is not mounted until the PRD settles who may read the notes.
"""

from uuid import UUID

from fastapi import APIRouter, status

from forge.api.deps import DbSession, IctPeerMentorUser, OneOnOnePeerMentorUser
from forge.models import IctProgressNote, PeerMentorNote
from forge.schemas.mentorship import (
    IctProgressNoteResponse,
    NoteCreateRequest,
    PeerMentorNoteResponse,
    ProgressNoteCreateRequest,
)
from forge.services import mentorship as mentorship_service

router = APIRouter(tags=["Mentor Notes"])


@router.post(
    "/peer-mentor/notes",
    status_code=status.HTTP_201_CREATED,
    response_model=PeerMentorNoteResponse,
)
async def create_note(
    data: NoteCreateRequest, mentor: OneOnOnePeerMentorUser, db: DbSession
) -> PeerMentorNote:
    """Keep a private note on a mentee in your group. Notes are encrypted at rest
    and visible only to you (and admins)."""
    return await mentorship_service.create_note(db, mentor, data)


@router.get(
    "/peer-mentor/notes/{mentee_id}", response_model=list[PeerMentorNoteResponse]
)
async def list_notes(
    mentee_id: UUID, mentor: OneOnOnePeerMentorUser, db: DbSession
) -> list[PeerMentorNote]:
    """Your private notes on a mentee, newest first."""
    return await mentorship_service.list_notes(db, mentor, mentee_id)


@router.post(
    "/ict-peer-mentor/progress-notes",
    status_code=status.HTTP_201_CREATED,
    response_model=IctProgressNoteResponse,
)
async def create_progress_note(
    data: ProgressNoteCreateRequest, mentor: IctPeerMentorUser, db: DbSession
) -> IctProgressNote:
    """Record technical progress for a mentee on your ICT track."""
    return await mentorship_service.create_progress_note(db, mentor, data)


@router.get(
    "/ict-peer-mentor/progress-notes/{mentee_id}",
    response_model=list[IctProgressNoteResponse],
)
async def list_progress_notes(
    mentee_id: UUID, mentor: IctPeerMentorUser, db: DbSession
) -> list[IctProgressNote]:
    """Technical progress notes for a mentee on your ICT track."""
    return await mentorship_service.list_progress_notes(db, mentor, mentee_id)
