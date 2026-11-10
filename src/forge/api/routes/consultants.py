"""Consultant roster endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from forge.api.deps import AdminUser, DbSession, RequireRoles
from forge.models import PARTICIPANT_ROLES, Consultant, User
from forge.schemas.activity import (
    ConsultantRequest,
    ConsultantResponse,
    ConsultantUpdateRequest,
)
from forge.services import consultants as consultant_service

router = APIRouter(prefix="/consultants", tags=["Consultants"])

RosterReader = Annotated[User, Depends(RequireRoles(*PARTICIPANT_ROLES))]


async def target_consultant(consultant_id: UUID, db: DbSession) -> Consultant:
    return await consultant_service.get_consultant_or_404(db, consultant_id)


TargetConsultant = Annotated[Consultant, Depends(target_consultant)]


@router.get("", response_model=list[ConsultantResponse])
async def list_consultants(_: RosterReader, db: DbSession) -> list[Consultant]:
    """Consultants available in the consultation log. **Mentees, peer mentors and
    System Admins.**"""
    return await consultant_service.list_consultants(db)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ConsultantResponse)
async def create_consultant(
    data: ConsultantRequest, admin: AdminUser, db: DbSession
) -> Consultant:
    """Add a consultant to the roster. **System Admin.**"""
    return await consultant_service.create_consultant(db, data, admin)


@router.patch("/{consultant_id}", response_model=ConsultantResponse)
async def update_consultant(
    data: ConsultantUpdateRequest,
    consultant: TargetConsultant,
    admin: AdminUser,
    db: DbSession,
) -> Consultant:
    """Edit a consultant on the roster. **System Admin.**"""
    return await consultant_service.update_consultant(db, consultant, data, admin)


@router.delete("/{consultant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_consultant(
    consultant: TargetConsultant, admin: AdminUser, db: DbSession
) -> None:
    """Remove a consultant from the roster. Past consultation logs keep their
    link. **System Admin.**"""
    await consultant_service.remove_consultant(db, consultant, admin)
