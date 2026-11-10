"""Private mentor notes (hidden until Phase 2)."""

import uuid

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from forge.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from forge.db.types import EncryptedText


class PeerMentorNote(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "peer_mentor_notes"

    peer_mentor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mentee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    note_text: Mapped[str] = mapped_column(EncryptedText)


class IctProgressNote(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "ict_progress_notes"

    ict_peer_mentor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mentee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    progress_note: Mapped[str] = mapped_column(Text)
