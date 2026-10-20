"""Personal audit log endpoint."""

from typing import Annotated

from fastapi import APIRouter, Query

from forge.api.deps import ActiveUser, DbSession
from forge.schemas.audit import AuditLogFilters, AuditLogResponse
from forge.schemas.common import Page
from forge.services.audit import list_audit_logs

router = APIRouter(prefix="/audit-logs", tags=["Audit"])


@router.get("/me")
async def my_audit_logs(
    filters: Annotated[AuditLogFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[AuditLogResponse]:
    """Actions you performed (logins, submissions, reviews, ...)."""
    filters = filters.model_copy(update={"user_id": user.id})
    logs, total = await list_audit_logs(db, filters)
    return Page[AuditLogResponse].build(logs, total, filters)
