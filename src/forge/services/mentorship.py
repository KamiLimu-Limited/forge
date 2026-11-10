"""Private peer mentor notes and ICT progress notes (Phase 2)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.exceptions import NotFound, PermissionDenied
from forge.models import (
    CohortEnrollment,
    IctProgressNote,
    PeerMentorNote,
    User,
    UserRole,
)
from forge.schemas.mentorship import NoteCreateRequest, ProgressNoteCreateRequest
from forge.services.access import get_enrollment


async def create_note(
    db: AsyncSession, mentor: User, data: NoteCreateRequest
) -> PeerMentorNote:
    enrollment = await get_enrollment(db, data.mentee_id)
    if enrollment is None or enrollment.peer_mentor_id != mentor.id:
        raise PermissionDenied("You can only keep notes on mentees in your group")
    note = PeerMentorNote(
        peer_mentor_id=mentor.id, mentee_id=data.mentee_id, note_text=data.note_text
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


async def list_notes(
    db: AsyncSession, viewer: User, mentee_id: uuid.UUID
) -> list[PeerMentorNote]:
    """Notes are private to their author; admins may read them for safeguarding."""
    stmt = select(PeerMentorNote).where(PeerMentorNote.mentee_id == mentee_id)
    if not viewer.is_admin:
        stmt = stmt.where(PeerMentorNote.peer_mentor_id == viewer.id)
    return list(await db.scalars(stmt.order_by(PeerMentorNote.created_at.desc())))


async def _ict_track(
    db: AsyncSession, mentor: User, mentee_id: uuid.UUID
) -> CohortEnrollment:
    mentee = await get_enrollment(db, mentee_id)
    if mentee is None:
        raise NotFound("Mentee enrollment not found")
    own = await get_enrollment(
        db, mentor.id, mentee.cohort_id, UserRole.PEER_MENTOR_ICT
    )
    if not mentor.is_admin and (
        own is None or not own.ict_track or own.ict_track != mentee.ict_track
    ):
        raise PermissionDenied("Mentee is not on the ICT track you mentor")
    return mentee


async def create_progress_note(
    db: AsyncSession, mentor: User, data: ProgressNoteCreateRequest
) -> IctProgressNote:
    await _ict_track(db, mentor, data.mentee_id)
    note = IctProgressNote(
        ict_peer_mentor_id=mentor.id,
        mentee_id=data.mentee_id,
        session_id=data.session_id,
        progress_note=data.progress_note,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


async def list_progress_notes(
    db: AsyncSession, viewer: User, mentee_id: uuid.UUID
) -> list[IctProgressNote]:
    await _ict_track(db, viewer, mentee_id)
    stmt = select(IctProgressNote).where(IctProgressNote.mentee_id == mentee_id)
    return list(await db.scalars(stmt.order_by(IctProgressNote.created_at.desc())))
