"""Authentication, invitation and password reset flows."""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.config import settings
from forge.core.exceptions import (
    BadRequest,
    Conflict,
    NotFound,
    PermissionDenied,
    Unauthorized,
)
from forge.core.jwt import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_token_payload,
)
from forge.core.security import generate_secure_token, hash_password, verify_password
from forge.models import (
    AccountState,
    Cohort,
    Invitation,
    PasswordResetToken,
    TokenBlacklist,
    User,
    UserRole,
)
from forge.schemas.auth import (
    BulkInviteResultEntry,
    BulkInviteUserEntry,
    InvitationPreview,
    TokenResponse,
    UserInviteRequest,
)
from forge.schemas.cohort import EnrollmentRequest
from forge.services.audit import log_action
from forge.services.cohorts import add_enrollment, ensure_role_assignment


def issue_tokens(user_id: uuid.UUID) -> TokenResponse:
    access_token, _, _ = create_access_token(user_id)
    refresh_token, _, _ = create_refresh_token(user_id)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


def _now() -> datetime:
    return datetime.now(UTC)


async def _ensure_invitable(db: AsyncSession, email: str) -> None:
    if await db.scalar(select(User.id).where(User.email == email)):
        raise Conflict("A user with this email already exists")
    pending = await db.scalar(
        select(Invitation.id).where(
            Invitation.email == email,
            Invitation.used_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > _now(),
        )
    )
    if pending:
        raise Conflict("A pending invitation already exists for this email")


async def _stage_invitation(
    db: AsyncSession,
    entry: UserInviteRequest | BulkInviteUserEntry,
    cohort_id: uuid.UUID | None,
    invited_by: uuid.UUID,
) -> Invitation:
    email = entry.email.lower()
    await _ensure_invitable(db, email)
    invitation = Invitation(
        email=email,
        token=generate_secure_token(),
        expires_at=_now() + timedelta(days=settings.INVITATION_TOKEN_EXPIRE_DAYS),
        invited_by=invited_by,
        first_name=entry.first_name,
        last_name=entry.last_name,
        intended_roles=[r.value for r in entry.roles],
        intended_cohort_id=cohort_id,
    )
    db.add(invitation)
    await db.flush()
    log_action(
        db,
        "invite_user",
        user_id=invited_by,
        resource_type="invitation",
        resource_id=invitation.id,
        email=email,
    )
    return invitation


async def _ensure_cohort(db: AsyncSession, cohort_id: uuid.UUID | None) -> None:
    if cohort_id is not None:
        cohort = await db.get(Cohort, cohort_id)
        if cohort is None or cohort.deleted_at is not None:
            raise NotFound("Cohort not found")


async def create_invitation(
    db: AsyncSession, data: UserInviteRequest, invited_by: User
) -> Invitation:
    await _ensure_cohort(db, data.cohort_id)
    invitation = await _stage_invitation(db, data, data.cohort_id, invited_by.id)
    await db.commit()
    return invitation


async def bulk_create_invitations(
    db: AsyncSession,
    entries: list[BulkInviteUserEntry],
    cohort_id: uuid.UUID | None,
    invited_by: User,
) -> tuple[list[BulkInviteResultEntry], list[Invitation]]:
    await _ensure_cohort(db, cohort_id)
    results: list[BulkInviteResultEntry] = []
    invitations: list[Invitation] = []
    for entry in entries:
        try:
            async with db.begin_nested():
                invitation = await _stage_invitation(
                    db, entry, cohort_id, invited_by.id
                )
        except Conflict as e:
            results.append(
                BulkInviteResultEntry(
                    email=entry.email, success=False, message=e.detail
                )
            )
        else:
            invitations.append(invitation)
            results.append(
                BulkInviteResultEntry(
                    email=entry.email, success=True, message="Invitation sent"
                )
            )
    await db.commit()
    return results, invitations


def parse_invite_csv(
    content: bytes,
) -> tuple[list[BulkInviteUserEntry], list[BulkInviteResultEntry]]:
    """Parse ``email,first_name,last_name,roles`` rows; roles are ``;``-separated."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise BadRequest("CSV must be UTF-8 encoded") from e

    reader = csv.DictReader(io.StringIO(text))
    required = {"email", "first_name", "last_name", "roles"}
    if not reader.fieldnames or not required <= {f.strip() for f in reader.fieldnames}:
        raise BadRequest(f"CSV must have columns: {', '.join(sorted(required))}")

    entries: list[BulkInviteUserEntry] = []
    errors: list[BulkInviteResultEntry] = []
    for line, row in enumerate(reader, start=2):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        try:
            entries.append(
                BulkInviteUserEntry(
                    email=row["email"],
                    first_name=row["first_name"],
                    last_name=row["last_name"],
                    roles=[r.strip() for r in row["roles"].split(";") if r.strip()],
                )
            )
        except ValidationError as e:
            reason = "; ".join(
                f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()
            )
            errors.append(
                BulkInviteResultEntry(
                    email=row.get("email", ""),
                    success=False,
                    message=f"Row {line}: {reason}",
                )
            )
    if not entries and not errors:
        raise BadRequest("CSV contains no rows")
    return entries, errors


async def get_valid_invitation(db: AsyncSession, token: str) -> Invitation:
    invitation = await db.scalar(select(Invitation).where(Invitation.token == token))
    if invitation is None or invitation.revoked_at is not None:
        raise BadRequest("Invalid invitation token")
    if invitation.used_at is not None:
        raise BadRequest("Invitation has already been used")
    if invitation.expires_at < _now():
        raise BadRequest("Invitation has expired")
    return invitation


async def preview_invitation(db: AsyncSession, token: str) -> InvitationPreview:
    return InvitationPreview.model_validate(await get_valid_invitation(db, token))


async def activate_account(
    db: AsyncSession, token: str, password: str
) -> tuple[User, TokenResponse]:
    invitation = await get_valid_invitation(db, token)
    user = await db.scalar(select(User).where(User.email == invitation.email))

    if user is not None and user.account_state is not AccountState.PENDING:
        raise BadRequest("An account with this email already exists")
    if user is None:
        user = User(
            email=invitation.email,
            first_name=invitation.first_name or "",
            last_name=invitation.last_name or "",
        )
        db.add(user)

    user.password_hash = hash_password(password)
    user.account_state = AccountState.ACTIVE
    user.last_login_at = _now()
    invitation.used_at = _now()
    await db.flush()

    cohort = (
        await db.get(Cohort, invitation.intended_cohort_id)
        if invitation.intended_cohort_id
        else None
    )
    for role_value in invitation.intended_roles or []:
        role = UserRole(role_value)
        if cohort is not None and role is not UserRole.ADMIN:
            await add_enrollment(
                db,
                cohort,
                EnrollmentRequest(user_id=user.id, role=role),
                invitation.invited_by,
            )
        else:
            await ensure_role_assignment(db, user.id, role, None, invitation.invited_by)

    log_action(
        db,
        "account_activated",
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        invitation_id=str(invitation.id),
    )
    await db.commit()
    await db.refresh(user)
    return user, issue_tokens(user.id)


async def authenticate_user(
    db: AsyncSession, email: str, password: str, ip_address: str | None = None
) -> tuple[User, TokenResponse]:
    user = await db.scalar(select(User).where(User.email == email.lower()))
    if (
        user is None
        or not user.password_hash
        or not verify_password(password, user.password_hash)
    ):
        raise Unauthorized("Invalid email or password")
    if user.account_state is AccountState.SUSPENDED:
        raise PermissionDenied(
            "Account is suspended. Please contact the administrator."
        )
    if user.account_state is AccountState.PENDING:
        raise PermissionDenied(
            "Account is not activated. Please check your email for activation link."
        )

    user.last_login_at = _now()
    log_action(
        db,
        "login",
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        ip_address=ip_address,
    )
    await db.commit()
    return user, issue_tokens(user.id)


async def _is_revoked(db: AsyncSession, jti: str) -> bool:
    return (
        await db.scalar(
            select(TokenBlacklist.id).where(TokenBlacklist.token_jti == jti)
        )
        is not None
    )


def _blacklist(db: AsyncSession, payload: dict[str, object]) -> None:
    db.add(
        TokenBlacklist(
            token_jti=str(payload["jti"]),
            expires_at=datetime.fromtimestamp(float(str(payload["exp"])), tz=UTC),
        )
    )


async def refresh_tokens(db: AsyncSession, refresh_token: str) -> TokenResponse:
    """Exchange a refresh token for a new pair, revoking the old refresh token."""
    try:
        payload = get_token_payload(refresh_token, TokenType.REFRESH)
    except TokenError as e:
        raise Unauthorized(str(e)) from e

    if await _is_revoked(db, payload["jti"]):
        raise Unauthorized("Token has been revoked")

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise Unauthorized("User not found")
    if user.account_state is not AccountState.ACTIVE:
        raise Unauthorized("Account is not active")

    _blacklist(db, payload)
    await db.commit()
    return issue_tokens(user.id)


async def logout_user(
    db: AsyncSession,
    user: User,
    access_token: str,
    refresh_token: str | None = None,
    ip_address: str | None = None,
) -> None:
    _blacklist(db, decode_token(access_token))
    if refresh_token:
        try:
            payload = decode_token(refresh_token)
        except TokenError:
            pass  # An expired or malformed refresh token is already unusable.
        else:
            if payload["sub"] == str(user.id) and not await _is_revoked(
                db, payload["jti"]
            ):
                _blacklist(db, payload)

    log_action(
        db,
        "logout",
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        ip_address=ip_address,
    )
    await db.commit()


async def create_password_reset_token(
    db: AsyncSession, email: str
) -> tuple[User, PasswordResetToken] | None:
    """Create a reset token; ``None`` for unknown or suspended accounts (no enumeration)."""
    user = await db.scalar(select(User).where(User.email == email.lower()))
    if user is None or user.account_state is AccountState.SUSPENDED:
        return None

    reset_token = PasswordResetToken(
        user_id=user.id,
        token=generate_secure_token(),
        expires_at=_now() + timedelta(hours=settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS),
    )
    db.add(reset_token)
    await db.commit()
    return user, reset_token


async def reset_password(db: AsyncSession, token: str, new_password: str) -> User:
    reset_token = await db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token == token)
    )
    if reset_token is None:
        raise BadRequest("Invalid reset token")
    if reset_token.used_at is not None:
        raise BadRequest("Reset token has already been used")
    if reset_token.expires_at < _now():
        raise BadRequest("Reset token has expired")

    user = await db.get(User, reset_token.user_id)
    if user is None:
        raise BadRequest("Invalid reset token")

    user.password_hash = hash_password(new_password)
    reset_token.used_at = _now()
    log_action(
        db, "password_reset", user_id=user.id, resource_type="user", resource_id=user.id
    )
    await db.commit()
    return user


async def purge_expired_tokens(db: AsyncSession) -> int:
    result = await db.execute(
        delete(TokenBlacklist).where(TokenBlacklist.expires_at < _now())
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)
