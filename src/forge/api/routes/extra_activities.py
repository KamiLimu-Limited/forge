"""Extra activity endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from forge.api.deps import ActiveUser, DbSession, ManagerUser, ParticipantUser
from forge.models import ActivityType, ExtraActivity
from forge.schemas.activity import (
    AcademicActivityRequest,
    ActivityFilters,
    ActivityProgressResponse,
    ActivityReversalRequest,
    ActivityUpdateRequest,
    ConsultationSessionRequest,
    ExternalEventRequest,
    ExtraActivityResponse,
    OpportunityApplicationRequest,
    ScholarshipApplicationRequest,
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
    response_model=ExtraActivityResponse,
)
async def submit_academic_activity(
    data: AcademicActivityRequest, user: ParticipantUser, db: DbSession
) -> ExtraActivity:
    """Log a course or academic activity where you applied what you learnt in
    sessions. Points are awarded on submission."""
    return await activity_service.submit_activity(db, user, ActivityType.ACADEMIC, data)


@router.post(
    "/events", status_code=status.HTTP_201_CREATED, response_model=ExtraActivityResponse
)
async def submit_external_event(
    data: ExternalEventRequest, user: ParticipantUser, db: DbSession
) -> ExtraActivity:
    """Log an external event you took part in as participant, speaker or
    organizer. Points are awarded on submission."""
    return await activity_service.submit_activity(db, user, ActivityType.EVENT, data)


@router.post(
    "/opportunities",
    status_code=status.HTTP_201_CREATED,
    response_model=ExtraActivityResponse,
)
async def submit_opportunity(
    data: OpportunityApplicationRequest, user: ParticipantUser, db: DbSession
) -> ExtraActivity:
    """Log a job application. Points follow its `stage`; update the stage and
    `final_outcome` as they change."""
    return await activity_service.submit_activity(
        db, user, ActivityType.OPPORTUNITY, data
    )


@router.post(
    "/scholarships",
    status_code=status.HTTP_201_CREATED,
    response_model=ExtraActivityResponse,
)
async def submit_scholarship(
    data: ScholarshipApplicationRequest, user: ParticipantUser, db: DbSession
) -> ExtraActivity:
    """Log a scholarship or fellowship application. Points follow its `stage`;
    update the stage and `final_outcome` as they change."""
    return await activity_service.submit_activity(
        db, user, ActivityType.SCHOLARSHIP, data
    )


@router.post(
    "/consultations",
    status_code=status.HTTP_201_CREATED,
    response_model=ExtraActivityResponse,
)
async def submit_consultation(
    data: ConsultationSessionRequest, user: ParticipantUser, db: DbSession
) -> ExtraActivity:
    """Log a one-on-one consultation with a consultant from the roster. Points
    are awarded once its status is `completed`."""
    return await activity_service.submit_activity(
        db, user, ActivityType.CONSULTATION, data
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


@router.get("/me/progress")
async def my_progress(
    user: ParticipantUser, db: DbSession, cohort_id: UUID | None = None
) -> ActivityProgressResponse:
    """Your count of active logs per type against the cohort's target for each."""
    return await activity_service.progress(db, user, cohort_id)


@router.get("")
async def list_activities(
    filters: Annotated[ActivityFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[ExtraActivityResponse]:
    """Activities visible to the caller: your own, your peer-mentor group's, or
    your cohorts' (staff)."""
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
    """Edit your activity unless it was reversed. Stage, outcome and consultation
    status updates recalculate its points."""
    return await activity_service.update_activity(db, user, activity, data)


@router.post("/{activity_id}/reverse", response_model=ExtraActivityResponse)
async def reverse_activity(
    data: ActivityReversalRequest,
    activity: VisibleActivity,
    user: ManagerUser,
    db: DbSession,
) -> ExtraActivity:
    """Reverse a log: its points are removed and the reason is kept on the
    record. **System Admin or Program Lead.**"""
    return await activity_service.reverse_activity(db, user, activity, data.reason)
