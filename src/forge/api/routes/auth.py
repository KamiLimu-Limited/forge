"""Authentication endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Body, File, Form, UploadFile, status

from forge.api.deps import (
    AccessToken,
    AdminUser,
    ClientIP,
    CurrentUser,
    DbSession,
    RateLimited,
)
from forge.models import Invitation
from forge.schemas.auth import (
    AccountActivationRequest,
    BulkInviteRequest,
    BulkInviteResponse,
    BulkInviteResultEntry,
    InvitationPreview,
    InvitationResponse,
    LoginRequest,
    LogoutRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    TokenRefreshRequest,
    TokenResponse,
    UserInviteRequest,
)
from forge.schemas.common import SuccessResponse
from forge.services import auth as auth_service
from forge.services.email import send_invitation_email, send_password_reset_email

router = APIRouter(prefix="/auth", tags=["Authentication"])


def queue_invitation_emails(
    background_tasks: BackgroundTasks, invitations: list[Invitation]
) -> None:
    for invitation in invitations:
        background_tasks.add_task(
            send_invitation_email,
            to=invitation.email,
            first_name=invitation.first_name or "there",
            invitation_token=invitation.token,
        )


def bulk_report(results: list[BulkInviteResultEntry]) -> BulkInviteResponse:
    successful = sum(r.success for r in results)
    return BulkInviteResponse(
        total=len(results),
        successful=successful,
        failed=len(results) - successful,
        results=results,
    )


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite_user(
    data: UserInviteRequest,
    background_tasks: BackgroundTasks,
    admin: AdminUser,
    db: DbSession,
) -> InvitationResponse:
    """Invite a user by email. **Admin only.**

    The invitation link expires after `INVITATION_TOKEN_EXPIRE_DAYS` (default 7).
    Roles are granted on activation, scoped to `cohort_id` when given, in which case
    the user is also enrolled in that cohort.
    """
    invitation = await auth_service.create_invitation(db, data, admin)
    queue_invitation_emails(background_tasks, [invitation])
    return InvitationResponse.model_validate(invitation)


@router.post("/bulk-invite", status_code=status.HTTP_201_CREATED)
async def bulk_invite_users(
    data: BulkInviteRequest,
    background_tasks: BackgroundTasks,
    admin: AdminUser,
    db: DbSession,
) -> BulkInviteResponse:
    """Invite many users at once (e.g. a whole cohort). **Admin only.**

    Each user is processed independently; the response reports success or the
    failure reason per email.
    """
    results, invitations = await auth_service.bulk_create_invitations(
        db, data.users, data.cohort_id, admin
    )
    queue_invitation_emails(background_tasks, invitations)
    return bulk_report(results)


@router.post("/bulk-invite/csv", status_code=status.HTTP_201_CREATED)
async def bulk_invite_csv(
    file: Annotated[
        UploadFile,
        File(description="CSV with columns email,first_name,last_name,roles"),
    ],
    background_tasks: BackgroundTasks,
    admin: AdminUser,
    db: DbSession,
    cohort_id: Annotated[UUID | None, Form()] = None,
) -> BulkInviteResponse:
    """Invite users from a CSV upload. **Admin only.**

    Columns: `email,first_name,last_name,roles`. Separate multiple roles with `;`,
    e.g. `peer_mentor_1:1;alumni`. Invalid rows are reported and skipped.
    """
    entries, row_errors = auth_service.parse_invite_csv(await file.read())
    results, invitations = await auth_service.bulk_create_invitations(
        db, entries, cohort_id, admin
    )
    queue_invitation_emails(background_tasks, invitations)
    return bulk_report(row_errors + results)


@router.get("/invitations/{token}")
async def preview_invitation(token: str, db: DbSession) -> InvitationPreview:
    """Validate an invitation token and return who it is for (used by the activation page)."""
    return await auth_service.preview_invitation(db, token)


@router.post("/activate", dependencies=[RateLimited])
async def activate_account(
    data: AccountActivationRequest, db: DbSession
) -> TokenResponse:
    """Activate an invited account by setting a password; returns a token pair.

    Password rules: at least 8 characters with an uppercase letter, a lowercase
    letter and a digit.
    """
    _, tokens = await auth_service.activate_account(db, data.token, data.password)
    return tokens


@router.post("/login", dependencies=[RateLimited])
async def login(data: LoginRequest, db: DbSession, ip: ClientIP) -> TokenResponse:
    """Exchange email and password for an access token (1h) and refresh token (7d).

    Send the access token as `Authorization: Bearer <access_token>`.
    """
    _, tokens = await auth_service.authenticate_user(db, data.email, data.password, ip)
    return tokens


@router.post("/refresh")
async def refresh_token(data: TokenRefreshRequest, db: DbSession) -> TokenResponse:
    """Rotate tokens: the submitted refresh token is revoked and a new pair issued."""
    return await auth_service.refresh_tokens(db, data.refresh_token)


@router.post("/logout")
async def logout(
    user: CurrentUser,
    token: AccessToken,
    db: DbSession,
    ip: ClientIP,
    data: Annotated[LogoutRequest | None, Body()] = None,
) -> SuccessResponse:
    """Revoke the current access token, and the refresh token if supplied."""
    await auth_service.logout_user(
        db, user, token, data.refresh_token if data else None, ip
    )
    return SuccessResponse(message="Successfully logged out")


@router.post("/request-reset", dependencies=[RateLimited])
async def request_password_reset(
    data: PasswordResetRequest, background_tasks: BackgroundTasks, db: DbSession
) -> SuccessResponse:
    """Email a password reset link (valid 24h).

    Always succeeds, so the response never reveals whether an account exists.
    """
    if created := await auth_service.create_password_reset_token(db, data.email):
        user, reset_token = created
        background_tasks.add_task(
            send_password_reset_email,
            to=user.email,
            first_name=user.first_name,
            reset_token=reset_token.token,
        )
    return SuccessResponse(
        message="If an account exists with this email, a password reset link has been sent"
    )


@router.post("/reset-password")
async def complete_password_reset(
    data: PasswordResetConfirmRequest, db: DbSession
) -> SuccessResponse:
    """Set a new password using the token from the reset email."""
    await auth_service.reset_password(db, data.token, data.new_password)
    return SuccessResponse(message="Password has been reset successfully")
