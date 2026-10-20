"""Current-user profile endpoints."""

from fastapi import APIRouter

from forge.api.deps import ActiveUser, DbSession
from forge.models import User
from forge.schemas.user import UserProfileResponse, UserProfileUpdateRequest
from forge.services import user as user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(user: ActiveUser) -> User:
    """The authenticated user's profile, including roles and cohort scopes."""
    return user


@router.patch("/me", response_model=UserProfileResponse)
async def update_my_profile(
    data: UserProfileUpdateRequest, user: ActiveUser, db: DbSession
) -> User:
    """Update your own name. Email and roles can only be changed by an admin."""
    return await user_service.update_profile(db, user, data)
