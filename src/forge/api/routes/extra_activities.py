"""Extra activity endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from forge.api.deps import ActiveUser, CommitteeUser, DbSession, MenteeUser
from forge.models import ActivityStatus, ActivityType, ExtraActivity
from forge.schemas.activity import (
    AcademicActivityRequest,
    AcademicActivityResponse,
    ActivityFilters,
    ActivityReviewRequest,
    ActivityUpdateRequest,
    ConsultationSessionRequest,
    ConsultationSessionResponse,
    ExternalEventRequest,
    ExternalEventResponse,
    ExtraActivityResponse,
    OpportunityApplicationRequest,
    OpportunityApplicationResponse,
)
from forge.schemas.common import Page
from forge.services import activities as activity_service

router = APIRouter(prefix="/extra-activities", tags=["Extra Activities"])


async def visible_activity(
    activity_id: UUID, user: ActiveUser, db: DbSession
) -> ExtraActivity:
    return await activity_service.get_visible_activity(db, user, activity_id)


VisibleActivity = Annotated[ExtraActivity, Depends(visible_activity)]


@router.post(
    "/academic",
    status_code=status.HTTP_201_CREATED,
    response_model=AcademicActivityResponse,
)
async def submit_academic_activity(
    data: AcademicActivityRequest, mentee: MenteeUser, db: DbSession
) -> ExtraActivity:
    """Log coursework that applies what you learnt in sessions."""
    return await activity_service.submit_activity(
        db, mentee, ActivityType.ACADEMIC, data
    )


@router.post(
    "/events", status_code=status.HTTP_201_CREATED, response_model=ExternalEventResponse
)
async def submit_external_event(
    data: ExternalEventRequest, mentee: MenteeUser, db: DbSession
) -> ExtraActivity:
    """Log an external event you attended, spoke at or helped organise."""
    return await activity_service.submit_activity(db, mentee, ActivityType.EVENT, data)


@router.post(
    "/opportunities",
    status_code=status.HTTP_201_CREATED,
    response_model=OpportunityApplicationResponse,
)
async def submit_opportunity(
    data: OpportunityApplicationRequest, mentee: MenteeUser, db: DbSession
) -> ExtraActivity:
    """Log an internship, scholarship or job application."""
    return await activity_service.submit_activity(
        db, mentee, ActivityType.OPPORTUNITY, data
    )


@router.post(
    "/consultations",
    status_code=status.HTTP_201_CREATED,
    response_model=ConsultationSessionResponse,
)
async def submit_consultation(
    data: ConsultationSessionRequest, mentee: MenteeUser, db: DbSession
) -> ExtraActivity:
    """Log a one-on-one consultation with a mentor."""
    return await activity_service.submit_activity(
        db, mentee, ActivityType.CONSULTATION, data
    )


@router.get("/me")
async def my_activities(
    filters: Annotated[ActivityFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[ExtraActivityResponse]:
    """Your extra activities, newest first."""
    activities, total = await activity_service.list_activities(
        db, user, filters, mine=True
    )
    return Page[ExtraActivityResponse].build(activities, total, filters)


@router.get("/pending")
async def validation_queue(
    filters: Annotated[ActivityFilters, Query()], reviewer: CommitteeUser, db: DbSession
) -> Page[ExtraActivityResponse]:
    """Activities awaiting validation in the committee member's cohorts. **Committee.**"""
    filters = filters.model_copy(update={"status": ActivityStatus.PENDING})
    activities, total = await activity_service.list_activities(db, reviewer, filters)
    return Page[ExtraActivityResponse].build(activities, total, filters)


@router.get("")
async def list_activities(
    filters: Annotated[ActivityFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[ExtraActivityResponse]:
    """Activities visible to the caller: your own, your peer-mentor group's, or your cohorts' (committee)."""
    activities, total = await activity_service.list_activities(db, user, filters)
    return Page[ExtraActivityResponse].build(activities, total, filters)


@router.get("/{activity_id}", response_model=ExtraActivityResponse)
async def get_activity(activity: VisibleActivity) -> ExtraActivity:
    """A single extra activity with its type-specific details."""
    return activity


@router.patch("/{activity_id}", response_model=ExtraActivityResponse)
async def update_activity(
    data: ActivityUpdateRequest,
    activity: VisibleActivity,
    user: ActiveUser,
    db: DbSession,
) -> ExtraActivity:
    """Edit your activity while it is still pending review."""
    return await activity_service.update_activity(db, user, activity, data)


@router.patch("/{activity_id}/approve", response_model=ExtraActivityResponse)
async def approve_activity(
    data: ActivityReviewRequest,
    activity: VisibleActivity,
    reviewer: CommitteeUser,
    db: DbSession,
) -> ExtraActivity:
    """Approve and award points (default per type, see `EXTRA_ACTIVITY_DEFAULT_POINTS`).
    The mentee's points and graduation status update immediately. **Committee.**"""
    return await activity_service.review_activity(
        db, reviewer, activity, data, approve=True
    )


@router.patch("/{activity_id}/reject", response_model=ExtraActivityResponse)
async def reject_activity(
    data: ActivityReviewRequest,
    activity: VisibleActivity,
    reviewer: CommitteeUser,
    db: DbSession,
) -> ExtraActivity:
    """Reject an activity, optionally with a reason. **Committee.**"""
    return await activity_service.review_activity(
        db, reviewer, activity, data, approve=False
    )
