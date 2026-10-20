"""User profile and administrative user management."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.config import settings
from forge.core.exceptions import BadRequest, Conflict, NotFound
from forge.core.security import generate_secure_token
from forge.models import AccountState, Invitation, User, UserRoleAssignment
from forge.schemas.auth import InvitationFilters
from forge.schemas.user import (
    AdminUserUpdateRequest,
    RoleAssignmentRequest,
    UserFilters,
    UserProfileUpdateRequest,
)
from forge.services.audit import log_action
from forge.services.pagination import paginate


async def get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFound("User not found")
    return user


async def update_profile(
    db: AsyncSession, user: User, data: UserProfileUpdateRequest
) -> User:
    for key, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user


async def admin_update_user(
    db: AsyncSession, user: User, data: AdminUserUpdateRequest, admin: User
) -> User:
    changes: dict[str, dict[str, str]] = {}
    for key, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        if key == "email":
            value = value.lower()
            if value != user.email and await db.scalar(
                select(User.id).where(User.email == value)
            ):
                raise Conflict("A user with this email already exists")
        if getattr(user, key) != value:
            changes[key] = {"old": getattr(user, key), "new": value}
            setattr(user, key, value)

    if changes:
        log_action(
            db,
            "admin_update_user",
            user_id=admin.id,
            resource_type="user",
            resource_id=user.id,
            changes=changes,
        )
    await db.commit()
    await db.refresh(user)
    return user


async def set_account_state(
    db: AsyncSession,
    user: User,
    state: AccountState,
    admin: User,
    ip_address: str | None,
) -> User:
    if state is AccountState.SUSPENDED and user.id == admin.id:
        raise BadRequest("Cannot suspend your own account")
    if state is AccountState.ACTIVE and not user.password_hash:
        raise BadRequest("User has not activated their account yet")

    old_state = user.account_state
    user.account_state = state
    action = "suspend_user" if state is AccountState.SUSPENDED else "reactivate_user"
    log_action(
        db,
        action,
        user_id=admin.id,
        resource_type="user",
        resource_id=user.id,
        ip_address=ip_address,
        old_state=old_state.value,
    )
    await db.commit()
    return user


async def list_users(db: AsyncSession, filters: UserFilters) -> tuple[list[User], int]:
    stmt = select(User).order_by(User.created_at.desc())
    if filters.account_state:
        stmt = stmt.where(User.account_state == filters.account_state)
    if filters.role or filters.cohort_id:
        role_stmt = select(UserRoleAssignment.user_id)
        if filters.role:
            role_stmt = role_stmt.where(UserRoleAssignment.role == filters.role)
        if filters.cohort_id:
            role_stmt = role_stmt.where(
                UserRoleAssignment.cohort_id == filters.cohort_id
            )
        stmt = stmt.where(User.id.in_(role_stmt))
    if filters.search:
        pattern = f"%{filters.search}%"
        stmt = stmt.where(
            or_(
                User.email.ilike(pattern),
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
            )
        )
    return await paginate(db, stmt, filters)


async def assign_role(
    db: AsyncSession, user: User, data: RoleAssignmentRequest, admin: User
) -> UserRoleAssignment:
    if any(r.role == data.role and r.cohort_id == data.cohort_id for r in user.roles):
        raise Conflict("User already has this role")
    assignment = UserRoleAssignment(
        user_id=user.id, role=data.role, cohort_id=data.cohort_id, assigned_by=admin.id
    )
    user.roles.append(assignment)
    log_action(
        db,
        "assign_role",
        user_id=admin.id,
        resource_type="user",
        resource_id=user.id,
        role=data.role.value,
        cohort_id=str(data.cohort_id) if data.cohort_id else None,
    )
    await db.commit()
    return assignment


async def remove_role(
    db: AsyncSession, user: User, assignment_id: uuid.UUID, admin: User
) -> None:
    assignment = next((r for r in user.roles if r.id == assignment_id), None)
    if assignment is None:
        raise NotFound("Role assignment not found")
    if assignment.user_id == admin.id and assignment.role.value == "admin":
        raise BadRequest("Cannot remove your own admin role")
    user.roles.remove(assignment)
    log_action(
        db,
        "remove_role",
        user_id=admin.id,
        resource_type="user",
        resource_id=user.id,
        role=assignment.role.value,
    )
    await db.commit()


async def list_invitations(
    db: AsyncSession, filters: InvitationFilters
) -> tuple[list[Invitation], int]:
    stmt = select(Invitation).order_by(Invitation.created_at.desc())
    if filters.pending_only:
        stmt = stmt.where(
            Invitation.used_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > datetime.now(UTC),
        )
    return await paginate(db, stmt, filters)


async def get_pending_invitation(
    db: AsyncSession, invitation_id: uuid.UUID
) -> Invitation:
    invitation = await db.get(Invitation, invitation_id)
    if invitation is None:
        raise NotFound("Invitation not found")
    if not invitation.is_pending:
        raise BadRequest("Invitation has already been used or revoked")
    return invitation


async def revoke_invitation(
    db: AsyncSession, invitation_id: uuid.UUID, admin: User
) -> None:
    invitation = await get_pending_invitation(db, invitation_id)
    invitation.revoked_at = datetime.now(UTC)
    log_action(
        db,
        "revoke_invitation",
        user_id=admin.id,
        resource_type="invitation",
        resource_id=invitation.id,
    )
    await db.commit()


async def renew_invitation(
    db: AsyncSession, invitation_id: uuid.UUID, admin: User
) -> Invitation:
    """Rotate the token and extend expiry so the invitation can be re-sent."""
    invitation = await get_pending_invitation(db, invitation_id)
    invitation.token = generate_secure_token()
    invitation.expires_at = datetime.now(UTC) + timedelta(
        days=settings.INVITATION_TOKEN_EXPIRE_DAYS
    )
    log_action(
        db,
        "resend_invitation",
        user_id=admin.id,
        resource_type="invitation",
        resource_id=invitation.id,
    )
    await db.commit()
    return invitation
