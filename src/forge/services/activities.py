"""Extra activity submission and committee validation."""

import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.config import settings
from forge.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from forge.models import (
    ActivityStatus,
    ActivityType,
    CohortEnrollment,
    ExtraActivity,
    NotificationType,
    User,
    UserRole,
)
from forge.schemas.activity import (
    DETAILS_MODELS,
    ActivityFilters,
    ActivityRequest,
    ActivityReviewRequest,
    ActivityUpdateRequest,
    ConsultationDetails,
)
from forge.services.access import get_enrollment, is_cohort_staff
from forge.services.audit import log_action
from forge.services.notifications import notify
from forge.services.pagination import paginate


async def _check_consultation_mentor(db: AsyncSession, details: object) -> None:
    if (
        isinstance(details, ConsultationDetails)
        and details.mentor_id
        and not await db.get(User, details.mentor_id)
    ):
        raise NotFound("Consultation mentor not found")


async def submit_activity(
    db: AsyncSession, mentee: User, activity_type: ActivityType, data: ActivityRequest
) -> ExtraActivity:
    enrollment = await get_enrollment(db, mentee.id, data.cohort_id)
    if enrollment is None:
        raise PermissionDenied("You must be enrolled as a mentee to log activities")
    await _check_consultation_mentor(db, data.details)

    activity = ExtraActivity(
        type=activity_type,
        mentee_id=mentee.id,
        cohort_id=enrollment.cohort_id,
        title=data.title,
        description=data.description,
        date=data.date,
        details=data.details.model_dump(mode="json"),
    )
    db.add(activity)
    await db.flush()
    log_action(
        db,
        "submit_extra_activity",
        user_id=mentee.id,
        resource_type="extra_activity",
        resource_id=activity.id,
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
        committee_scopes = {
            r.cohort_id for r in user.roles if r.role is UserRole.COMMITTEE
        }
        if None not in committee_scopes:
            group = select(CohortEnrollment.user_id).where(
                CohortEnrollment.peer_mentor_id == user.id
            )
            stmt = stmt.where(
                or_(
                    ExtraActivity.mentee_id == user.id,
                    ExtraActivity.mentee_id.in_(group),
                    ExtraActivity.cohort_id.in_(committee_scopes),
                )
            )
    for name in ("cohort_id", "type", "status", "mentee_id"):
        if (value := getattr(filters, name)) is not None:
            stmt = stmt.where(getattr(ExtraActivity, name) == value)
    return await paginate(db, stmt, filters)


async def update_activity(
    db: AsyncSession, user: User, activity: ExtraActivity, data: ActivityUpdateRequest
) -> ExtraActivity:
    if activity.mentee_id != user.id:
        raise PermissionDenied("You can only edit your own activities")
    if activity.status is not ActivityStatus.PENDING:
        raise BusinessRuleViolation("Only pending activities can be edited")

    values = data.model_dump(exclude_unset=True, exclude={"details"})
    if data.details is not None:
        try:
            details = DETAILS_MODELS[activity.type].model_validate(
                activity.details | data.details
            )
        except ValidationError as e:
            raise BusinessRuleViolation(
                f"Invalid details for a {activity.type.value} activity: {e.errors()[0]['msg']}"
            ) from e
        await _check_consultation_mentor(db, details)
        values["details"] = details.model_dump(mode="json")
    for key, value in values.items():
        setattr(activity, key, value)
    log_action(
        db,
        "update_extra_activity",
        user_id=user.id,
        resource_type="extra_activity",
        resource_id=activity.id,
    )
    await db.commit()
    await db.refresh(activity)
    return activity


async def review_activity(
    db: AsyncSession,
    reviewer: User,
    activity: ExtraActivity,
    data: ActivityReviewRequest,
    approve: bool,
) -> ExtraActivity:
    """Approve (awarding points, which immediately count towards graduation) or reject."""
    if not is_cohort_staff(reviewer, activity.cohort_id):
        raise PermissionDenied("Requires committee access to this cohort")
    if activity.status is not ActivityStatus.PENDING:
        raise BusinessRuleViolation(
            f"Activity has already been {activity.status.value}"
        )

    activity.status = ActivityStatus.APPROVED if approve else ActivityStatus.REJECTED
    if approve:
        default = settings.EXTRA_ACTIVITY_DEFAULT_POINTS.get(activity.type.value, 0)
        activity.points_awarded = (
            default if data.points_awarded is None else data.points_awarded
        )
    activity.reviewed_by = reviewer.id
    activity.reviewed_at = datetime.now(UTC)
    activity.review_reason = data.reason

    notify(
        db,
        [activity.mentee_id],
        NotificationType.ACTIVITY_APPROVED
        if approve
        else NotificationType.ACTIVITY_REJECTED,
        {
            "title": activity.title,
            "type": activity.type.value,
            "points": activity.points_awarded,
            "reason": data.reason or "",
        },
        resource_type="extra_activity",
        resource_id=activity.id,
    )
    log_action(
        db,
        "approve_extra_activity" if approve else "reject_extra_activity",
        user_id=reviewer.id,
        resource_type="extra_activity",
        resource_id=activity.id,
        points=activity.points_awarded,
    )
    await db.commit()
    await db.refresh(activity)
    return activity
