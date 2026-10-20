"""Administrative user, role and invitation management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from forge.api.deps import AdminUser, ClientIP, DbSession, RequireRoles
from forge.api.routes.auth import queue_invitation_emails
from forge.models import AccountState, User, UserRole, UserRoleAssignment
from forge.schemas.audit import AuditLogFilters, AuditLogResponse
from forge.schemas.auth import InvitationFilters, InvitationResponse
from forge.schemas.common import Page, SuccessResponse
from forge.schemas.user import (
    AdminUserDetailResponse,
    AdminUserListResponse,
    AdminUserUpdateRequest,
    RoleAssignmentRequest,
    UserFilters,
    UserRoleResponse,
)
from forge.services import user as user_service
from forge.services.audit import list_audit_logs

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(RequireRoles(UserRole.ADMIN))],
)


async def target_user(user_id: UUID, db: DbSession) -> User:
    return await user_service.get_user_or_404(db, user_id)


TargetUser = Annotated[User, Depends(target_user)]


@router.get("/users")
async def list_users(
    filters: Annotated[UserFilters, Query()], db: DbSession
) -> Page[AdminUserListResponse]:
    """List users, filterable by account state, role, cohort and a name/email search."""
    users, total = await user_service.list_users(db, filters)
    return Page[AdminUserListResponse].build(users, total, filters)


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
async def get_user(user: TargetUser) -> User:
    """A user's account details and role assignments."""
    return user


@router.patch("/users/{user_id}", response_model=AdminUserDetailResponse)
async def update_user(
    data: AdminUserUpdateRequest, user: TargetUser, admin: AdminUser, db: DbSession
) -> User:
    """Update a user's name or email. Changes are recorded in the audit log."""
    return await user_service.admin_update_user(db, user, data, admin)


@router.post("/users/{user_id}/suspend")
async def suspend_user(
    user: TargetUser, admin: AdminUser, db: DbSession, ip: ClientIP
) -> SuccessResponse:
    """Suspend an account. Suspended users cannot log in or use existing tokens."""
    await user_service.set_account_state(db, user, AccountState.SUSPENDED, admin, ip)
    return SuccessResponse(message="User account has been suspended")


@router.post("/users/{user_id}/activate")
async def reactivate_user(
    user: TargetUser, admin: AdminUser, db: DbSession, ip: ClientIP
) -> SuccessResponse:
    """Reactivate a suspended account."""
    await user_service.set_account_state(db, user, AccountState.ACTIVE, admin, ip)
    return SuccessResponse(message="User account has been reactivated")


@router.post(
    "/users/{user_id}/roles",
    status_code=status.HTTP_201_CREATED,
    response_model=UserRoleResponse,
)
async def assign_role(
    data: RoleAssignmentRequest, user: TargetUser, admin: AdminUser, db: DbSession
) -> UserRoleAssignment:
    """Grant a role, globally or scoped to a cohort."""
    return await user_service.assign_role(db, user, data, admin)


@router.delete(
    "/users/{user_id}/roles/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_role(
    assignment_id: UUID, user: TargetUser, admin: AdminUser, db: DbSession
) -> None:
    """Revoke one of a user's role assignments."""
    await user_service.remove_role(db, user, assignment_id, admin)


@router.get("/invitations")
async def list_invitations(
    filters: Annotated[InvitationFilters, Query()], db: DbSession
) -> Page[InvitationResponse]:
    """All invitations, newest first; `pending_only` hides used, revoked and expired ones."""
    invitations, total = await user_service.list_invitations(db, filters)
    return Page[InvitationResponse].build(invitations, total, filters)


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: UUID, admin: AdminUser, db: DbSession
) -> None:
    """Revoke a pending invitation so its link no longer works."""
    await user_service.revoke_invitation(db, invitation_id, admin)


@router.post("/invitations/{invitation_id}/resend", response_model=InvitationResponse)
async def resend_invitation(
    invitation_id: UUID,
    background_tasks: BackgroundTasks,
    admin: AdminUser,
    db: DbSession,
) -> InvitationResponse:
    """Issue a fresh link (new token, renewed expiry) and email it again."""
    invitation = await user_service.renew_invitation(db, invitation_id, admin)
    queue_invitation_emails(background_tasks, [invitation])
    return InvitationResponse.model_validate(invitation)


@router.get("/audit-logs")
async def list_all_audit_logs(
    filters: Annotated[AuditLogFilters, Query()], db: DbSession
) -> Page[AuditLogResponse]:
    """Audit trail across all users."""
    logs, total = await list_audit_logs(db, filters)
    return Page[AuditLogResponse].build(logs, total, filters)
