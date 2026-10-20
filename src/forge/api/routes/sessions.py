"""Programme session endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status

from forge.api.deps import ActiveUser, DbSession
from forge.models import ProgrammeSession
from forge.schemas.common import Page
from forge.schemas.session import (
    MentorsUpdateRequest,
    ResourcesUpdateRequest,
    SessionCancelRequest,
    SessionCreateRequest,
    SessionDetailResponse,
    SessionFilters,
    SessionRescheduleRequest,
    SessionResponse,
    SessionUpdateRequest,
)
from forge.services import sessions as session_service

router = APIRouter(prefix="/sessions", tags=["Sessions"])


async def visible_session(
    session_id: UUID, user: ActiveUser, db: DbSession
) -> ProgrammeSession:
    return await session_service.get_visible_session(db, user, session_id)


VisibleSession = Annotated[ProgrammeSession, Depends(visible_session)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SessionResponse)
async def create_session(
    data: SessionCreateRequest, user: ActiveUser, db: DbSession
) -> ProgrammeSession:
    """Schedule a session. **Committee of the cohort or admin.**

    Publishing (`status: published`) opens an attendance window based on the
    category (Thursday: 24h after the end, Saturday: 48h, peer mentorship: the
    explicit deadline) and notifies the cohort.
    """
    return await session_service.create_session(db, data, user)


@router.get("")
async def list_sessions(
    filters: Annotated[SessionFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[SessionResponse]:
    """Sessions in the caller's cohorts, filterable by cohort, track, month, status and date.
    Drafts are only listed for committee and admins."""
    sessions, total = await session_service.list_sessions(db, user, filters)
    return Page[SessionResponse].build(sessions, total, filters)


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session: VisibleSession) -> ProgrammeSession:
    """Session details including mentors, resources, reschedule history and its
    attendance window."""
    return session


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    data: SessionUpdateRequest, session: VisibleSession, user: ActiveUser, db: DbSession
) -> ProgrammeSession:
    """Edit session details, publish a draft or mark it completed. Use
    `/reschedule` to change its time."""
    return await session_service.update_session(db, session, data, user)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_session(
    session: VisibleSession,
    user: ActiveUser,
    db: DbSession,
    data: Annotated[SessionCancelRequest | None, Body()] = None,
) -> None:
    """Cancel a session. Its window closes and it no longer counts towards points."""
    await session_service.cancel_session(
        db, session, user, data.reason if data else None
    )


@router.post("/{session_id}/reschedule", response_model=SessionResponse)
async def reschedule_session(
    data: SessionRescheduleRequest,
    session: VisibleSession,
    user: ActiveUser,
    db: DbSession,
) -> ProgrammeSession:
    """Move a session. The original time and every change are kept in
    `reschedule_history`, the attendance window is recomputed (dropping
    per-mentee overrides) and attendees are notified."""
    return await session_service.reschedule_session(db, session, data, user)


@router.put("/{session_id}/mentors", response_model=SessionResponse)
async def set_session_mentors(
    data: MentorsUpdateRequest, session: VisibleSession, user: ActiveUser, db: DbSession
) -> ProgrammeSession:
    """Replace the lead and co-mentors assigned to a session."""
    return await session_service.replace_mentors(db, session, data.mentors, user)


@router.patch("/{session_id}/resources", response_model=SessionResponse)
async def set_session_resources(
    data: ResourcesUpdateRequest,
    session: VisibleSession,
    user: ActiveUser,
    db: DbSession,
) -> ProgrammeSession:
    """Replace the session's material links (slides, recordings, Drive folders).
    Allowed for staff and the session's mentors."""
    return await session_service.replace_resources(db, session, data.resources, user)
