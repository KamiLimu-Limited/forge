"""The consultant roster used by consultation logs."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.exceptions import NotFound
from forge.models import Consultant, User
from forge.schemas.activity import ConsultantRequest, ConsultantUpdateRequest
from forge.services.audit import log_action


async def list_consultants(
    db: AsyncSession, include_inactive: bool = False
) -> list[Consultant]:
    stmt = select(Consultant).order_by(Consultant.name)
    if not include_inactive:
        stmt = stmt.where(Consultant.is_active.is_(True))
    return list(await db.scalars(stmt))


async def get_consultant_or_404(
    db: AsyncSession, consultant_id: uuid.UUID
) -> Consultant:
    consultant = await db.get(Consultant, consultant_id)
    if consultant is None or not consultant.is_active:
        raise NotFound("Consultant not found")
    return consultant


async def create_consultant(
    db: AsyncSession, data: ConsultantRequest, actor: User
) -> Consultant:
    consultant = Consultant(**data.model_dump())
    db.add(consultant)
    await db.flush()
    log_action(
        db,
        "create_consultant",
        user_id=actor.id,
        resource_type="consultant",
        resource_id=consultant.id,
    )
    await db.commit()
    await db.refresh(consultant)
    return consultant


async def update_consultant(
    db: AsyncSession,
    consultant: Consultant,
    data: ConsultantUpdateRequest,
    actor: User,
) -> Consultant:
    values = data.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(consultant, key, value)
    log_action(
        db,
        "update_consultant",
        user_id=actor.id,
        resource_type="consultant",
        resource_id=consultant.id,
        fields=sorted(values),
    )
    await db.commit()
    await db.refresh(consultant)
    return consultant


async def remove_consultant(
    db: AsyncSession, consultant: Consultant, actor: User
) -> None:
    """Take a consultant off the roster; past consultation logs keep the link."""
    consultant.is_active = False
    log_action(
        db,
        "remove_consultant",
        user_id=actor.id,
        resource_type="consultant",
        resource_id=consultant.id,
    )
    await db.commit()
