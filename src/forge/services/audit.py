"""Audit logging."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.models import AuditLog
from forge.schemas.audit import AuditLogFilters
from forge.services.pagination import paginate


def log_action(
    db: AsyncSession,
    action: str,
    *,
    user_id: uuid.UUID | None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    **meta: Any,
) -> None:
    """Stage an audit log entry; persisted with the caller's commit."""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            meta_data=meta or None,
        )
    )


async def list_audit_logs(
    db: AsyncSession, filters: AuditLogFilters
) -> tuple[list[AuditLog], int]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if filters.user_id:
        stmt = stmt.where(AuditLog.user_id == filters.user_id)
    if filters.action:
        stmt = stmt.where(AuditLog.action == filters.action)
    if filters.resource_type:
        stmt = stmt.where(AuditLog.resource_type == filters.resource_type)
    if filters.resource_id:
        stmt = stmt.where(AuditLog.resource_id == filters.resource_id)
    if filters.since:
        stmt = stmt.where(AuditLog.created_at >= filters.since)
    return await paginate(db, stmt, filters)
