"""Audit log schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from forge.schemas.common import PageParams, Schema


class AuditLogFilters(PageParams):
    user_id: UUID | None = None
    action: str | None = None
    resource_type: str | None = None
    resource_id: UUID | None = None
    since: datetime | None = None


class AuditLogResponse(Schema):
    id: UUID
    user_id: UUID | None
    action: str
    resource_type: str | None
    resource_id: UUID | None
    meta_data: dict[str, Any] | None
    ip_address: str | None
    created_at: datetime
