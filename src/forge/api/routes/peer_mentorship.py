"""Peer mentorship: private notes, ICT progress notes and group tasks."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from forge.api.deps import (
    ActiveUser,
    DbSession,
    IctPeerMentorUser,
    MenteeUser,
    OneOnOnePeerMentorUser,
)
from forge.models import IctProgressNote, PeerMentorNote, PeerMentorTask, TaskSubmission
from forge.schemas.common import Page
from forge.schemas.mentorship import (
    IctProgressNoteResponse,
    NoteCreateRequest,
    PeerMentorNoteResponse,
    PeerMentorTaskRequest,
    PeerMentorTaskResponse,
    PeerMentorTaskUpdateRequest,
    ProgressNoteCreateRequest,
    TaskFilters,
    TaskSubmissionRequest,
    TaskSubmissionResponse,
    TaskSubmissionStatusEntry,
)
from forge.services import mentorship as mentorship_service

router = APIRouter(tags=["Peer Mentorship"])


async def visible_task(
    task_id: UUID, user: ActiveUser, db: DbSession
) -> PeerMentorTask:
    return await mentorship_service.get_visible_task(db, user, task_id)


VisibleTask = Annotated[PeerMentorTask, Depends(visible_task)]


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


@router.post(
    "/peer-mentor-tasks",
    status_code=status.HTTP_201_CREATED,
    response_model=PeerMentorTaskResponse,
)
async def create_task(
    data: PeerMentorTaskRequest, mentor: OneOnOnePeerMentorUser, db: DbSession
) -> PeerMentorTask:
    """Create a task for your group. Mentees are notified at `launch_date` and
    reminded before `deadline_date`."""
    return await mentorship_service.create_task(db, mentor, data)


@router.get("/peer-mentor-tasks")
async def list_tasks(
    filters: Annotated[TaskFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[PeerMentorTaskResponse]:
    """Your own tasks (peer mentors), your mentor's launched tasks (mentees), or
    your cohorts' tasks (committee)."""
    tasks, total = await mentorship_service.list_tasks(db, user, filters)
    return Page[PeerMentorTaskResponse].build(tasks, total, filters)


@router.get("/peer-mentor-tasks/{task_id}", response_model=PeerMentorTaskResponse)
async def get_task(task: VisibleTask) -> PeerMentorTask:
    """A peer mentor task. Mentees can only see it once it has launched."""
    return task


@router.patch("/peer-mentor-tasks/{task_id}", response_model=PeerMentorTaskResponse)
async def update_task(
    data: PeerMentorTaskUpdateRequest,
    task: VisibleTask,
    user: ActiveUser,
    db: DbSession,
) -> PeerMentorTask:
    """Edit a task you created."""
    return await mentorship_service.update_task(db, user, task, data)


@router.post(
    "/peer-mentor-tasks/{task_id}/submit", response_model=TaskSubmissionResponse
)
async def submit_task(
    task: VisibleTask,
    mentee: MenteeUser,
    db: DbSession,
    data: TaskSubmissionRequest | None = None,
) -> TaskSubmission:
    """Mark a task as completed, with optional notes. Resubmitting updates it."""
    return await mentorship_service.submit_task(
        db, mentee, task, data or TaskSubmissionRequest()
    )


@router.get("/peer-mentor-tasks/{task_id}/submissions")
async def task_submissions(
    task: VisibleTask, user: ActiveUser, db: DbSession
) -> list[TaskSubmissionStatusEntry]:
    """Completion status for every mentee in the group, including those yet to submit."""
    return await mentorship_service.task_submissions(db, user, task)
