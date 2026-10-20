"""Peer mentor notes and tasks, ICT progress notes and skill ratings."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.config import settings
from forge.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from forge.models import (
    Cohort,
    CohortEnrollment,
    IctProgressNote,
    Notification,
    NotificationType,
    PeerMentorNote,
    PeerMentorTask,
    RatingPoint,
    SkillRating,
    SubmissionStatus,
    TaskSubmission,
    User,
    UserRole,
)
from forge.schemas.mentorship import (
    NoteCreateRequest,
    PeerMentorTaskRequest,
    PeerMentorTaskUpdateRequest,
    ProgressNoteCreateRequest,
    SkillProgressResponse,
    SkillRatingRequest,
    SkillRatingResponse,
    SkillRatingWindowStatus,
    TaskFilters,
    TaskSubmissionRequest,
    TaskSubmissionStatusEntry,
)
from forge.schemas.user import UserSummary
from forge.services.access import (
    get_cohort_or_404,
    get_enrollment,
    group_mentee_ids,
    is_cohort_staff,
)
from forge.services.audit import log_action
from forge.services.notifications import notify
from forge.services.pagination import paginate


def _now() -> datetime:
    return datetime.now(UTC)


# Private notes


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


# Tasks


async def _notify_launch(db: AsyncSession, task: PeerMentorTask) -> None:
    notify(
        db,
        await group_mentee_ids(db, task.peer_mentor_id, task.cohort_id),
        NotificationType.TASK_LAUNCHED,
        {"title": task.title, "deadline": task.deadline_date},
        resource_type="peer_mentor_task",
        resource_id=task.id,
    )


async def create_task(
    db: AsyncSession, mentor: User, data: PeerMentorTaskRequest
) -> PeerMentorTask:
    enrollment = await get_enrollment(
        db, mentor.id, data.cohort_id, UserRole.PEER_MENTOR_1_1
    )
    if enrollment is None:
        raise PermissionDenied(
            "You must be enrolled as a 1:1 peer mentor in this cohort"
        )
    task = PeerMentorTask(
        peer_mentor_id=mentor.id,
        cohort_id=enrollment.cohort_id,
        title=data.title,
        description=data.description,
        launch_date=data.launch_date,
        deadline_date=data.deadline_date,
        resource_link=str(data.resource_link) if data.resource_link else None,
    )
    db.add(task)
    await db.flush()
    if task.launch_date <= _now():
        await _notify_launch(db, task)
    log_action(
        db,
        "create_peer_task",
        user_id=mentor.id,
        resource_type="peer_mentor_task",
        resource_id=task.id,
    )
    await db.commit()
    await db.refresh(task)
    return task


async def get_task_or_404(db: AsyncSession, task_id: uuid.UUID) -> PeerMentorTask:
    task = await db.get(PeerMentorTask, task_id)
    if task is None:
        raise NotFound("Task not found")
    return task


async def _is_task_mentee(db: AsyncSession, user: User, task: PeerMentorTask) -> bool:
    return user.id in await group_mentee_ids(db, task.peer_mentor_id, task.cohort_id)


async def get_visible_task(
    db: AsyncSession, user: User, task_id: uuid.UUID
) -> PeerMentorTask:
    task = await get_task_or_404(db, task_id)
    if task.peer_mentor_id == user.id or is_cohort_staff(user, task.cohort_id):
        return task
    if task.launch_date <= _now() and await _is_task_mentee(db, user, task):
        return task
    raise NotFound("Task not found")


async def list_tasks(
    db: AsyncSession, user: User, filters: TaskFilters
) -> tuple[list[PeerMentorTask], int]:
    """Peer mentors see their tasks, mentees their mentor's launched tasks, committee their cohorts'."""
    stmt = select(PeerMentorTask).order_by(PeerMentorTask.deadline_date)
    if not user.is_admin:
        committee_scopes = {
            r.cohort_id for r in user.roles if r.role is UserRole.COMMITTEE
        }
        my_mentors = select(CohortEnrollment.peer_mentor_id).where(
            CohortEnrollment.user_id == user.id,
            CohortEnrollment.peer_mentor_id.is_not(None),
        )
        visible = (PeerMentorTask.peer_mentor_id == user.id) | (
            PeerMentorTask.peer_mentor_id.in_(my_mentors)
            & (PeerMentorTask.launch_date <= _now())
        )
        if None not in committee_scopes:
            stmt = stmt.where(visible | PeerMentorTask.cohort_id.in_(committee_scopes))
    if filters.cohort_id:
        stmt = stmt.where(PeerMentorTask.cohort_id == filters.cohort_id)
    if filters.peer_mentor_id:
        stmt = stmt.where(PeerMentorTask.peer_mentor_id == filters.peer_mentor_id)
    return await paginate(db, stmt, filters)


async def update_task(
    db: AsyncSession,
    user: User,
    task: PeerMentorTask,
    data: PeerMentorTaskUpdateRequest,
) -> PeerMentorTask:
    if task.peer_mentor_id != user.id and not user.is_admin:
        raise PermissionDenied("Only the task's peer mentor can edit it")
    values = data.model_dump(exclude_unset=True)
    if "resource_link" in values and values["resource_link"] is not None:
        values["resource_link"] = str(values["resource_link"])
    for key, value in values.items():
        setattr(task, key, value)
    if task.deadline_date <= task.launch_date:
        raise BusinessRuleViolation("deadline_date must be after launch_date")
    await db.commit()
    await db.refresh(task)
    return task


async def submit_task(
    db: AsyncSession, mentee: User, task: PeerMentorTask, data: TaskSubmissionRequest
) -> TaskSubmission:
    if not await _is_task_mentee(db, mentee, task):
        raise PermissionDenied("This task is not assigned to you")
    if task.launch_date > _now():
        raise BusinessRuleViolation("This task has not launched yet")
    submission = await db.scalar(
        select(TaskSubmission).where(
            TaskSubmission.task_id == task.id, TaskSubmission.mentee_id == mentee.id
        )
    )
    if submission is None:
        submission = TaskSubmission(task_id=task.id, mentee_id=mentee.id)
        db.add(submission)
    submission.submission_status = SubmissionStatus.COMPLETED
    submission.submitted_at = _now()
    submission.notes = data.notes
    await db.commit()
    await db.refresh(submission)
    return submission


async def task_submissions(
    db: AsyncSession, user: User, task: PeerMentorTask
) -> list[TaskSubmissionStatusEntry]:
    if task.peer_mentor_id != user.id and not is_cohort_staff(user, task.cohort_id):
        raise PermissionDenied(
            "Only the task's peer mentor or committee can view submissions"
        )
    mentee_ids = await group_mentee_ids(db, task.peer_mentor_id, task.cohort_id)
    submissions = {
        s.mentee_id: s
        for s in await db.scalars(
            select(TaskSubmission).where(TaskSubmission.task_id == task.id)
        )
    }
    mentees = await db.scalars(
        select(User).where(User.id.in_(mentee_ids)).order_by(User.first_name)
    )
    return [
        TaskSubmissionStatusEntry(
            mentee=UserSummary.model_validate(m),
            submission_status=s.submission_status
            if (s := submissions.get(m.id))
            else SubmissionStatus.PENDING,
            submitted_at=s.submitted_at if s else None,
            notes=s.notes if s else None,
        )
        for m in mentees
    ]


async def send_task_deadline_reminders(db: AsyncSession) -> int:
    """Announce tasks whose launch time has passed and remind mentees of near deadlines."""
    now = _now()
    sent = 0

    def not_yet(kind: NotificationType, task_id: object) -> ColumnElement[bool]:
        return ~exists().where(
            Notification.notification_type == kind,
            Notification.related_resource_id == task_id,
        )

    launched = await db.scalars(
        select(PeerMentorTask).where(
            PeerMentorTask.launch_date <= now,
            PeerMentorTask.deadline_date > now,
            not_yet(NotificationType.TASK_LAUNCHED, PeerMentorTask.id),
        )
    )
    for task in launched:
        await _notify_launch(db, task)
        sent += 1

    due_soon = await db.scalars(
        select(PeerMentorTask).where(
            PeerMentorTask.launch_date <= now,
            PeerMentorTask.deadline_date > now,
            PeerMentorTask.deadline_date
            <= now + timedelta(hours=settings.TASK_DEADLINE_REMINDER_HOURS),
            not_yet(NotificationType.TASK_DEADLINE_REMINDER, PeerMentorTask.id),
        )
    )
    for task in due_soon:
        done = set(
            await db.scalars(
                select(TaskSubmission.mentee_id).where(
                    TaskSubmission.task_id == task.id,
                    TaskSubmission.submission_status == SubmissionStatus.COMPLETED,
                )
            )
        )
        pending = [
            m
            for m in await group_mentee_ids(db, task.peer_mentor_id, task.cohort_id)
            if m not in done
        ]
        notify(
            db,
            pending,
            NotificationType.TASK_DEADLINE_REMINDER,
            {"title": task.title, "deadline": task.deadline_date},
            resource_type="peer_mentor_task",
            resource_id=task.id,
        )
        sent += 1
    await db.commit()
    return sent


# Skill ratings


def window_bounds(
    cohort: Cohort, point: RatingPoint
) -> tuple[datetime | None, datetime | None]:
    window = (cohort.skill_rating_windows or {}).get(point.value)
    if not window:
        return None, None
    return datetime.fromisoformat(window["opens_at"]), datetime.fromisoformat(
        window["closes_at"]
    )


def window_open(
    cohort: Cohort, point: RatingPoint, now: datetime | None = None
) -> bool:
    opens_at, closes_at = window_bounds(cohort, point)
    now = now or _now()
    return (
        opens_at is not None and closes_at is not None and opens_at <= now < closes_at
    )


async def submit_skill_rating(
    db: AsyncSession, mentee: User, data: SkillRatingRequest
) -> tuple[SkillRating, bool]:
    """Create or (while the window is open) replace a rating. Returns ``(rating, created)``."""
    enrollment = await get_enrollment(db, mentee.id, data.cohort_id)
    if enrollment is None:
        raise PermissionDenied("You must be enrolled as a mentee to rate your skills")
    cohort = await get_cohort_or_404(db, enrollment.cohort_id)
    if not window_open(cohort, data.rating_point):
        raise BusinessRuleViolation(
            f"The {data.rating_point.value} skill rating window is not open"
        )
    expected = set(cohort.skill_names or settings.DEFAULT_SKILL_NAMES)
    if set(data.ratings) != expected:
        raise BusinessRuleViolation(
            f"Ratings must cover exactly these skills: {', '.join(sorted(expected))}"
        )

    rating = await db.scalar(
        select(SkillRating).where(
            SkillRating.mentee_id == mentee.id,
            SkillRating.cohort_id == cohort.id,
            SkillRating.rating_point == data.rating_point,
        )
    )
    created = rating is None
    if rating is None:
        rating = SkillRating(
            mentee_id=mentee.id, cohort_id=cohort.id, rating_point=data.rating_point
        )
        db.add(rating)
    rating.ratings = dict(data.ratings)
    rating.rated_at = _now()
    await db.commit()
    await db.refresh(rating)
    return rating, created


async def rating_windows(
    db: AsyncSession, mentee: User, cohort_id: uuid.UUID | None
) -> list[SkillRatingWindowStatus]:
    enrollment = await get_enrollment(db, mentee.id, cohort_id)
    if enrollment is None:
        raise NotFound("Mentee enrollment not found")
    cohort = await get_cohort_or_404(db, enrollment.cohort_id)
    submitted = set(
        await db.scalars(
            select(SkillRating.rating_point).where(
                SkillRating.mentee_id == mentee.id, SkillRating.cohort_id == cohort.id
            )
        )
    )
    return [
        SkillRatingWindowStatus(
            rating_point=point,
            opens_at=(bounds := window_bounds(cohort, point))[0],
            closes_at=bounds[1],
            is_open=window_open(cohort, point),
            submitted=point in submitted,
        )
        for point in RatingPoint
    ]


async def skill_progress(
    db: AsyncSession, enrollment: CohortEnrollment
) -> SkillProgressResponse:
    cohort = await get_cohort_or_404(db, enrollment.cohort_id)
    order = list(RatingPoint)
    ratings = sorted(
        await db.scalars(
            select(SkillRating).where(
                SkillRating.mentee_id == enrollment.user_id,
                SkillRating.cohort_id == cohort.id,
            )
        ),
        key=lambda r: order.index(r.rating_point),
    )
    change: dict[str, int] = {}
    if len(ratings) >= 2:
        first, last = ratings[0].ratings, ratings[-1].ratings
        change = {skill: last[skill] - first[skill] for skill in last if skill in first}
    return SkillProgressResponse(
        mentee_id=enrollment.user_id,
        cohort_id=cohort.id,
        skill_names=cohort.skill_names or settings.DEFAULT_SKILL_NAMES,
        ratings=[SkillRatingResponse.model_validate(r) for r in ratings],
        change=change,
    )
