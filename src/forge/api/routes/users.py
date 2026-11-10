"""Current-user profile, cohort context, graduation card and alumni history."""

from fastapi import APIRouter

from forge.api.deps import ActiveUser, AlumniUser, DbSession
from forge.schemas.graduation import AlumniCohort, GraduationCard
from forge.schemas.user import (
    ActiveCohortRequest,
    ActiveCohortResponse,
    MyCohort,
    UserProfileResponse,
    UserProfileUpdateRequest,
)
from forge.services import graduation as graduation_service
from forge.services import user as user_service

router = APIRouter(prefix="/users", tags=["Users"])
alumni_router = APIRouter(prefix="/alumni", tags=["Users"])


@router.get("/me")
async def get_my_profile(user: ActiveUser, db: DbSession) -> UserProfileResponse:
    """Your profile, roles and cohort scopes, alumni status, active cohort context
    and your ICT track once selected."""
    return await user_service.profile(db, user)


@router.patch("/me")
async def update_my_profile(
    data: UserProfileUpdateRequest, user: ActiveUser, db: DbSession
) -> UserProfileResponse:
    """Update your name and profile. Email and roles are changed by an admin, and
    your ICT track through track selection."""
    return await user_service.profile(
        db, await user_service.update_profile(db, user, data)
    )


@router.get("/me/cohorts")
async def my_cohorts(user: ActiveUser, db: DbSession) -> list[MyCohort]:
    """Every cohort you hold a role in, with your roles there."""
    return await user_service.my_cohorts(db, user)


@router.put("/me/active-cohort")
async def set_active_cohort(
    data: ActiveCohortRequest, user: ActiveUser, db: DbSession
) -> ActiveCohortResponse:
    """Choose which cohort and role you are viewing, when you hold roles in
    several cohorts."""
    await user_service.set_active_cohort(db, user, data)
    return ActiveCohortResponse(active_cohort_id=data.cohort_id, active_role=data.role)


@router.get("/me/graduation-card")
async def my_graduation_card(user: ActiveUser, db: DbSession) -> GraduationCard:
    """Your graduation card: cohort, date, final rates and points. **Graduates.**"""
    return await graduation_service.graduation_card(db, user)


@alumni_router.get("/me/history")
async def my_history(user: AlumniUser, db: DbSession) -> list[AlumniCohort]:
    """Your finished cohorts with your roles and frozen results, read only.
    **Alumni.**"""
    return await graduation_service.alumni_history(db, user)
