"""Shared FastAPI dependencies: database session, authentication and authorization."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.exceptions import PermissionDenied, Unauthorized
from forge.core.jwt import TokenError, TokenType, get_token_payload
from forge.core.rate_limit import auth_rate_limiter, client_ip
from forge.db.session import get_db
from forge.models import (
    PARTICIPANT_ROLES,
    PEER_MENTOR_ROLES,
    AccountState,
    TokenBlacklist,
    User,
    UserRole,
)

bearer_scheme = HTTPBearer(
    auto_error=False, description="JWT access token from `/auth/login`"
)

DbSession = Annotated[AsyncSession, Depends(get_db)]
BearerToken = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def get_client_ip(request: Request) -> str | None:
    return client_ip(request)


ClientIP = Annotated[str | None, Depends(get_client_ip)]
RateLimited = Depends(auth_rate_limiter)


async def get_access_token(credentials: BearerToken) -> str:
    if credentials is None:
        raise Unauthorized()
    return credentials.credentials


AccessToken = Annotated[str, Depends(get_access_token)]


async def get_current_user(token: AccessToken, db: DbSession) -> User:
    try:
        payload = get_token_payload(token, TokenType.ACCESS)
    except TokenError as e:
        raise Unauthorized(str(e)) from e

    revoked = await db.scalar(
        select(exists().where(TokenBlacklist.token_jti == payload["jti"]))
    )
    if revoked:
        raise Unauthorized("Token has been revoked")

    user = await db.get(User, UUID(payload["sub"]))
    if user is None:
        raise Unauthorized("User not found")
    if user.account_state is AccountState.SUSPENDED:
        raise PermissionDenied(
            "Account is suspended. Please contact the administrator."
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_active_user(user: CurrentUser) -> User:
    if user.account_state is not AccountState.ACTIVE:
        raise PermissionDenied("Account is not active")
    return user


ActiveUser = Annotated[User, Depends(get_active_user)]


class RequireRoles:
    """Allow users holding any of ``roles`` (in any cohort).

    Admins pass too unless ``allow_admin`` is false.
    """

    def __init__(self, *roles: UserRole, allow_admin: bool = True) -> None:
        self.roles = frozenset(roles)
        self.allow_admin = allow_admin

    async def __call__(self, user: ActiveUser) -> User:
        if (self.allow_admin and user.is_admin) or self.roles & user.role_set:
            return user
        raise PermissionDenied()


AdminUser = Annotated[User, Depends(RequireRoles(UserRole.ADMIN))]
ManagerUser = Annotated[User, Depends(RequireRoles(UserRole.PROGRAM_LEAD))]
ProgramLeadUser = Annotated[
    User, Depends(RequireRoles(UserRole.PROGRAM_LEAD, allow_admin=False))
]
StaffUser = Annotated[
    User,
    Depends(
        RequireRoles(
            UserRole.PROGRAM_LEAD,
            UserRole.COMMITTEE,
            UserRole.PROGRAM_DELIVERY_LEAD,
        )
    ),
]
MenteeUser = Annotated[User, Depends(RequireRoles(UserRole.MENTEE))]
ParticipantUser = Annotated[User, Depends(RequireRoles(*PARTICIPANT_ROLES))]
PeerMentorUser = Annotated[User, Depends(RequireRoles(*PEER_MENTOR_ROLES))]
AlumniUser = Annotated[User, Depends(RequireRoles(UserRole.ALUMNI))]
OneOnOnePeerMentorUser = Annotated[
    User, Depends(RequireRoles(UserRole.PEER_MENTOR_1_1))
]
IctPeerMentorUser = Annotated[User, Depends(RequireRoles(UserRole.PEER_MENTOR_ICT))]
ProfessionalMentorUser = Annotated[
    User, Depends(RequireRoles(UserRole.PROFESSIONAL_MENTOR))
]


async def get_confirmed_user(
    user: ProgramLeadUser,
    confirmation_token: Annotated[str, Header(alias="X-Confirmation-Token")],
) -> User:
    """A Program Lead who re-entered their password via `/auth/confirm-password`."""
    try:
        payload = get_token_payload(confirmation_token, TokenType.CONFIRMATION)
    except TokenError as e:
        raise PermissionDenied(f"Password confirmation required: {e}") from e
    if payload["sub"] != str(user.id):
        raise PermissionDenied("Password confirmation belongs to another user")
    return user


ConfirmedProgramLead = Annotated[User, Depends(get_confirmed_user)]
