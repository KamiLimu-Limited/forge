"""User, role and authentication models."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from forge.db.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    pg_enum,
)


class AccountState(enum.StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserRole(enum.StrEnum):
    MENTEE = "mentee"
    PEER_MENTOR_1_1 = "peer_mentor_1:1"
    PEER_MENTOR_ICT = "peer_mentor_ict"
    PROFESSIONAL_MENTOR = "professional_mentor"
    COMMITTEE = "committee"
    PARTNER = "partner"
    ALUMNI = "alumni"
    ADMIN = "admin"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    account_state: Mapped[AccountState] = mapped_column(
        pg_enum(AccountState), default=AccountState.PENDING
    )
    last_login_at: Mapped[datetime | None]

    roles: Mapped[list["UserRoleAssignment"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserRoleAssignment.user_id",
        lazy="selectin",
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def role_set(self) -> set[UserRole]:
        return {r.role for r in self.roles}

    def has_role(self, *roles: UserRole, cohort_id: uuid.UUID | None = None) -> bool:
        """True when the user holds any of ``roles`` globally or within ``cohort_id``."""
        return any(
            r.role in roles and (r.cohort_id is None or r.cohort_id == cohort_id)
            for r in self.roles
        )

    @property
    def is_admin(self) -> bool:
        return UserRole.ADMIN in self.role_set

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class UserRoleAssignment(Base, UUIDPrimaryKeyMixin):
    """Role held by a user, optionally scoped to a cohort."""

    __tablename__ = "user_roles"
    __table_args__ = (Index("ix_user_roles_user_id_cohort_id", "user_id", "cohort_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole))
    cohort_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE")
    )
    assigned_at: Mapped[datetime] = mapped_column(server_default=func.now())
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    user: Mapped[User] = relationship(back_populates="roles", foreign_keys=[user_id])


class Invitation(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(String(255), index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    invited_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    intended_roles: Mapped[list[str] | None]
    intended_cohort_id: Mapped[uuid.UUID | None]
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    revoked_at: Mapped[datetime | None]

    @property
    def is_pending(self) -> bool:
        return self.used_at is None and self.revoked_at is None


class TokenBlacklist(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "token_blacklist"

    token_jti: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    blacklisted_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]


class PasswordResetToken(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


class AuditLog(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "audit_logs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(100))
    resource_id: Mapped[uuid.UUID | None]
    meta_data: Mapped[dict[str, Any] | None]
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
