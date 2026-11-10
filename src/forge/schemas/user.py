"""User schemas."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import EmailStr, Field, HttpUrl, StringConstraints

from forge.models import AccountState, CohortStatus, DegreeLevel, Gender, UserRole
from forge.schemas.common import Name, PageParams, RequestSchema, Schema

Phone = Annotated[
    str, StringConstraints(min_length=7, max_length=30, pattern=r"^\+?[0-9 ()-]+$")
]


class UserRoleResponse(Schema):
    id: UUID
    role: UserRole
    cohort_id: UUID | None
    assigned_at: datetime


class UserSummary(Schema):
    id: UUID
    email: str
    first_name: str
    last_name: str


class SocialLinks(RequestSchema):
    linkedin: HttpUrl | None = None
    github: HttpUrl | None = None
    instagram: HttpUrl | None = None
    twitter: HttpUrl | None = None
    website: HttpUrl | None = None


class ProfileFields(RequestSchema):
    university: str | None = Field(None, max_length=200)
    programme_of_study: str | None = Field(None, max_length=200)
    degree_level: DegreeLevel | None = None
    gender: Gender | None = None
    phone: Phone | None = None
    birthday: date | None = None
    social_links: SocialLinks | None = None


class ProfileResponse(Schema):
    university: str | None
    programme_of_study: str | None
    degree_level: DegreeLevel | None
    gender: Gender | None
    phone: str | None
    birthday: date | None
    social_links: dict[str, str | None] | None
    alumni_since: date | None
    is_alumni: bool


class AdminUserListResponse(UserSummary, ProfileResponse):
    account_state: AccountState
    last_login_at: datetime | None
    created_at: datetime


class UserProfileResponse(AdminUserListResponse):
    roles: list[UserRoleResponse]
    active_cohort_id: UUID | None
    active_role: UserRole | None
    ict_track: str | None = Field(
        None, description="Your ICT track in the active (or latest) cohort, once chosen"
    )


class AdminUserDetailResponse(UserProfileResponse):
    updated_at: datetime


class UserProfileUpdateRequest(ProfileFields):
    """Your profile; the ICT track is set through track selection."""

    first_name: Name | None = None
    last_name: Name | None = None


class AdminUserUpdateRequest(UserProfileUpdateRequest):
    email: EmailStr | None = None


class RoleAssignmentRequest(RequestSchema):
    role: UserRole
    cohort_id: UUID | None = None


class UserFilters(PageParams):
    account_state: AccountState | None = None
    role: UserRole | None = None
    cohort_id: UUID | None = None
    search: str | None = None


class CohortBrief(Schema):
    id: UUID
    name: str
    status: CohortStatus


class MyCohort(Schema):
    cohort: CohortBrief
    roles: list[UserRole]
    is_active_context: bool


class ActiveCohortRequest(RequestSchema):
    cohort_id: UUID
    role: UserRole


class ActiveCohortResponse(Schema):
    active_cohort_id: UUID
    active_role: UserRole
