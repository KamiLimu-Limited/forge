"""Authentication schemas."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, EmailStr, Field

from forge.core.config import settings
from forge.core.security import validate_password
from forge.models import UserRole
from forge.schemas.common import Name, PageParams, RequestSchema, Schema


def _strong_password(value: str) -> str:
    result = validate_password(value)
    if not result.is_valid:
        raise ValueError("; ".join(result.errors))
    return value


StrongPassword = Annotated[
    str, Field(examples=["Sup3rSecret"]), AfterValidator(_strong_password)
]


class UserInviteRequest(RequestSchema):
    email: EmailStr = Field(examples=["mentee@example.com"])
    first_name: Name
    last_name: Name
    roles: list[UserRole] = Field(min_length=1, examples=[["mentee"]])
    cohort_id: UUID | None = None


class BulkInviteUserEntry(RequestSchema):
    email: EmailStr
    first_name: Name
    last_name: Name
    roles: list[UserRole] = Field(min_length=1)


class BulkInviteRequest(RequestSchema):
    users: list[BulkInviteUserEntry] = Field(min_length=1, max_length=1000)
    cohort_id: UUID | None = None


class BulkInviteResultEntry(Schema):
    email: str
    success: bool
    message: str | None = None


class BulkInviteResponse(Schema):
    total: int
    successful: int
    failed: int
    results: list[BulkInviteResultEntry]


class AccountActivationRequest(RequestSchema):
    token: str = Field(min_length=1)
    password: StrongPassword


class LoginRequest(RequestSchema):
    email: EmailStr = Field(examples=["admin@kamilimu.org"])
    password: str = Field(min_length=1, examples=["Sup3rSecret"])


class TokenResponse(Schema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(
        default=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        description="Seconds until the access token expires",
    )


class TokenRefreshRequest(RequestSchema):
    refresh_token: str


class LogoutRequest(RequestSchema):
    refresh_token: str | None = Field(
        None, description="Also revoke this refresh token"
    )


class PasswordResetRequest(RequestSchema):
    email: EmailStr


class PasswordResetConfirmRequest(RequestSchema):
    token: str = Field(min_length=1)
    new_password: StrongPassword


class InvitationResponse(Schema):
    id: UUID
    email: str
    first_name: str | None
    last_name: str | None
    intended_roles: list[UserRole] | None
    intended_cohort_id: UUID | None
    invited_by: UUID
    expires_at: datetime
    created_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None


class InvitationPreview(Schema):
    email: str
    first_name: str | None
    last_name: str | None
    intended_roles: list[UserRole] | None
    expires_at: datetime


class InvitationFilters(PageParams):
    pending_only: bool = False
