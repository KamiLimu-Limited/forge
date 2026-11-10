"""Private mentor note schemas (Phase 2)."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from forge.schemas.common import RequestSchema, Schema


class NoteCreateRequest(RequestSchema):
    mentee_id: UUID
    note_text: str = Field(min_length=1, max_length=10000)


class PeerMentorNoteResponse(Schema):
    id: UUID
    peer_mentor_id: UUID
    mentee_id: UUID
    note_text: str
    created_at: datetime
    updated_at: datetime


class ProgressNoteCreateRequest(RequestSchema):
    mentee_id: UUID
    session_id: UUID | None = None
    progress_note: str = Field(min_length=1, max_length=10000)


class IctProgressNoteResponse(Schema):
    id: UUID
    ict_peer_mentor_id: UUID
    mentee_id: UUID
    session_id: UUID | None
    progress_note: str
    created_at: datetime
