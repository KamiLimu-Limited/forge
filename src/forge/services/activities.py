"""Extra activity logging, points and reversal.

Points are awarded when a log is submitted, using the cohort's points config, and
recalculated whenever a job or scholarship application changes stage or a
consultation is completed. A manager can reverse a log, which keeps the record
and the reason but removes its points.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from forge.models import (
    APPLICATION_TYPES,
    ActivityStatus,
    ActivityType,
    Cohort,
    CohortEnrollment,
    Consultant,
    ExtraActivity,
    User,
    UserRole,
)
from forge.models.activity import ConsultationStatus, OpportunityStage
from forge.schemas.activity import (
    DETAILS_MODELS,
    ActivityFilters,
    ActivityProgressResponse,
    ActivityRequest,
    ActivityUpdateRequest,
    ConsultationSessionRequest,
    TypeProgress,
)
from forge.schemas.cohort import PointsConfig
from forge.services.access import (
    ensure_cohort_manager,
    ensure_cohort_writable,
    get_cohort_or_404,
    get_enrollment,
    get_participant_enrollment,
    get_participant_enrollment_or_404,
    is_cohort_staff,
)
from forge.services.audit import log_action
from forge.services.cohort_config import points_config
from forge.services.pagination import paginate

STAFF_ROLES = (
    UserRole.PROGRAM_LEAD,
    UserRole.COMMITTEE,
    UserRole.PROGRAM_DELIVERY_LEAD,
)


def points_for(
    activity_type: ActivityType, details: dict[str, object], config: PointsConfig
) -> int:
    if activity_type in APPLICATION_TYPES:
        stages = getattr(config, activity_type.value)
        return int(getattr(stages, str(details.get("stage", OpportunityStage.APPLIED))))
    if activity_type is ActivityType.CONSULTATION:
        completed = details.get("status") == ConsultationStatus.COMPLETED
        return config.consultation if completed else 0
    return int(getattr(config, activity_type.value))


def _check_log_window(cohort: Cohort, when: date) -> None:
    today = date.today()
    if when > today:
        raise BusinessRuleViolation("Activities can only be logged once they happen")
    if today - when > timedelta(days=cohort.extra_log_window_days):
        raise BusinessRuleViolation(
            f"Activities must be logged within {cohort.extra_log_window_days} days"
        )


async def _check_consultant(db: AsyncSession, consultant_id: uuid.UUID) -> None:
    consultant = await db.get(Consultant, consultant_id)
    if consultant is None or not consultant.is_active:
        raise NotFound("Consultant not found on the roster")


async def submit_activity(
    db: AsyncSession, user: User, activity_type: ActivityType, data: ActivityRequest
) -> ExtraActivity:
    enrollment = await get_participant_enrollment(db, user.id, data.cohort_id)
    if enrollment is None:
        raise PermissionDenied("You must be enrolled as a mentee or peer mentor")
    cohort = await get_cohort_or_404(db, enrollment.cohort_id)
    ensure_cohort_writable(cohort)
    _check_log_window(cohort, data.date)
    consultant_id = None
    if isinstance(data, ConsultationSessionRequest):
        await _check_consultant(db, data.consultant_id)
        consultant_id = data.consultant_id

    details = data.details.model_dump(mode="json")
    activity = ExtraActivity(
        type=activity_type,
        mentee_id=user.id,
        cohort_id=cohort.id,
        title=data.title,
        description=data.description,
        date=data.date,
        details=details,
        consultant_id=consultant_id,
        points_awarded=points_for(activity_type, details, points_config(cohort)),
    )
    db.add(activity)
    await db.flush()
    log_action(
        db,
        "submit_extra_activity",
        user_id=user.id,
        resource_type="extra_activity",
        resource_id=activity.id,
        points=activity.points_awarded,
    )
    await db.commit()
    await db.refresh(activity)
    return activity


async def get_activity_or_404(
    db: AsyncSession, activity_id: uuid.UUID
) -> ExtraActivity:
    activity = await db.get(ExtraActivity, activity_id)
    if activity is None:
        raise NotFound("Activity not found")
    return activity


async def get_visible_activity(
    db: AsyncSession, user: User, activity_id: uuid.UUID
) -> ExtraActivity:
    activity = await get_activity_or_404(db, activity_id)
    if activity.mentee_id == user.id or is_cohort_staff(user, activity.cohort_id):
        return activity
    enrollment = await get_enrollment(db, activity.mentee_id, activity.cohort_id)
    if enrollment is not None and enrollment.peer_mentor_id == user.id:
        return activity
    raise NotFound("Activity not found")


async def list_activities(
    db: AsyncSession, user: User, filters: ActivityFilters, *, mine: bool = False
) -> tuple[list[ExtraActivity], int]:
    stmt = select(ExtraActivity).order_by(ExtraActivity.created_at.desc())
    if mine:
        stmt = stmt.where(ExtraActivity.mentee_id == user.id)
    elif not user.is_admin:
        staff_scopes = {r.cohort_id for r in user.roles if r.role in STAFF_ROLES}
        if None not in staff_scopes:
            group = select(CohortEnrollment.user_id).where(
                CohortEnrollment.peer_mentor_id == user.id
            )
            stmt = stmt.where(
                or_(
                    ExtraActivity.mentee_id == user.id,
                    ExtraActivity.mentee_id.in_(group),
                    ExtraActivity.cohort_id.in_(staff_scopes),
                )
            )
    for name in ("cohort_id", "type", "status", "mentee_id"):
        if (value := getattr(filters, name)) is not None:
            stmt = stmt.where(getattr(ExtraActivity, name) == value)
    return await paginate(db, stmt, filters)


async def update_activity(
    db: AsyncSession, user: User, activity: ExtraActivity, data: ActivityUpdateRequest
) -> ExtraActivity:
    """Edit your own active log; stage, outcome and status changes recalculate points."""
    if activity.mentee_id != user.id:
        raise PermissionDenied("You can only edit your own activities")
    if activity.status is ActivityStatus.REVERSED:
        raise BusinessRuleViolation("Reversed activities cannot be edited")
    cohort = await get_cohort_or_404(db, activity.cohort_id)
    ensure_cohort_writable(cohort)

    values = data.model_dump(exclude_unset=True, exclude={"details"})
    if "date" in values:
        _check_log_window(cohort, values["date"])
    if "consultant_id" in values:
        if activity.type is not ActivityType.CONSULTATION:
            raise BusinessRuleViolation("Only consultations have a consultant")
        await _check_consultant(db, values["consultant_id"])
    if data.details is not None:
        try:
            details = DETAILS_MODELS[activity.type].model_validate(
                activity.details | data.details
            )
        except ValidationError as e:
            raise BusinessRuleViolation(
                f"Invalid details for a {activity.type.value} activity: "
                f"{e.errors()[0]['msg']}"
            ) from e
        values["details"] = details.model_dump(mode="json")
    for key, value in values.items():
        setattr(activity, key, value)
    previous = activity.points_awarded
    activity.points_awarded = points_for(
        activity.type, activity.details, points_config(cohort)
    )
    log_action(
        db,
        "update_extra_activity",
        user_id=user.id,
        resource_type="extra_activity",
        resource_id=activity.id,
        fields=sorted(values),
        old_points=previous,
        new_points=activity.points_awarded,
    )
    await db.commit()
    await db.refresh(activity)
    return activity


async def reverse_activity(
    db: AsyncSession, actor: User, activity: ExtraActivity, reason: str
) -> ExtraActivity:
    """Take back an activity's points, keeping the record and the reason."""
    ensure_cohort_manager(actor, activity.cohort_id)
    if activity.status is ActivityStatus.REVERSED:
        raise BusinessRuleViolation("Activity has already been reversed")
    previous = activity.points_awarded
    activity.status = ActivityStatus.REVERSED
    activity.points_awarded = 0
    activity.reversed_by = actor.id
    activity.reversed_at = datetime.now(UTC)
    activity.reversal_reason = reason
    log_action(
        db,
        "reverse_extra_activity",
        user_id=actor.id,
        resource_type="extra_activity",
        resource_id=activity.id,
        points_removed=previous,
        reason=reason,
    )
    await db.commit()
    await db.refresh(activity)
    return activity


async def progress(
    db: AsyncSession, user: User, cohort_id: uuid.UUID | None
) -> ActivityProgressResponse:
    enrollment = await get_participant_enrollment_or_404(db, user.id, cohort_id)
    cohort = await get_cohort_or_404(db, enrollment.cohort_id)
    config = points_config(cohort)
    rows = await db.execute(
        select(
            ExtraActivity.type,
            func.count(),
            func.coalesce(func.sum(ExtraActivity.points_awarded), 0),
        )
        .where(
            ExtraActivity.cohort_id == cohort.id,
            ExtraActivity.mentee_id == user.id,
            ExtraActivity.status == ActivityStatus.ACTIVE,
        )
        .group_by(ExtraActivity.type)
    )
    logged = {t: (count, int(points)) for t, count, points in rows}
    return ActivityProgressResponse(
        cohort_id=cohort.id,
        types=[
            TypeProgress(
                type=t,
                logged=logged.get(t, (0, 0))[0],
                target=config.targets.get(t, 0),
                points=logged.get(t, (0, 0))[1],
            )
            for t in ActivityType
        ],
    )
