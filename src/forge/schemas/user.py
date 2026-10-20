"""User schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr

from forge.models import AccountState, UserRole
from forge.schemas.common import Name, PageParams, RequestSchema, Schema


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


class AdminUserListResponse(UserSummary):
    account_state: AccountState
    last_login_at: datetime | None
    created_at: datetime


class UserProfileResponse(AdminUserListResponse):
    roles: list[UserRoleResponse]


class AdminUserDetailResponse(UserProfileResponse):
    updated_at: datetime


class UserProfileUpdateRequest(RequestSchema):
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
