"""Competitions, rounds and entries."""

import uuid

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.exceptions import BusinessRuleViolation, Conflict, NotFound
from forge.models import (
    CohortEnrollment,
    Competition,
    CompetitionEntry,
    CompetitionRound,
    User,
    UserRole,
)
from forge.schemas.competition import (
    CompetitionCreateRequest,
    CompetitionFilters,
    CompetitionStatusEntry,
    CompetitionUpdateRequest,
    EntryCreate,
    EntryResponse,
    EntryUpdateRequest,
    RoundCreateRequest,
    RoundUpdateRequest,
)
from forge.services.access import (
    ensure_cohort_member,
    ensure_cohort_staff,
    get_cohort_or_404,
    is_cohort_staff,
)
from forge.services.audit import log_action
from forge.services.pagination import paginate
from forge.services.sessions import accessible_cohort_ids


async def create_competition(
    db: AsyncSession, user: User, data: CompetitionCreateRequest
) -> Competition:
    await get_cohort_or_404(db, data.cohort_id)
    ensure_cohort_staff(user, data.cohort_id)
    competition = Competition(**data.model_dump(), rounds=[])
    db.add(competition)
    await db.flush()
    log_action(
        db,
        "create_competition",
        user_id=user.id,
        resource_type="competition",
        resource_id=competition.id,
    )
    await db.commit()
    await db.refresh(competition)
    return competition


async def list_competitions(
    db: AsyncSession, user: User, filters: CompetitionFilters
) -> tuple[list[Competition], int]:
    stmt = select(Competition).order_by(Competition.start_date.desc())
    if not user.is_admin:
        stmt = stmt.where(
            Competition.cohort_id.in_(await accessible_cohort_ids(db, user))
        )
    for name in ("cohort_id", "competition_type", "status"):
        if (value := getattr(filters, name)) is not None:
            stmt = stmt.where(getattr(Competition, name) == value)
    return await paginate(db, stmt, filters)


async def get_visible_competition(
    db: AsyncSession, user: User, competition_id: uuid.UUID
) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise NotFound("Competition not found")
    await ensure_cohort_member(db, user, competition.cohort_id)
    return competition


async def update_competition(
    db: AsyncSession,
    user: User,
    competition: Competition,
    data: CompetitionUpdateRequest,
) -> Competition:
    ensure_cohort_staff(user, competition.cohort_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(competition, key, value)
    if competition.end_date < competition.start_date:
        raise BusinessRuleViolation("end_date must not precede start_date")
    await db.commit()
    await db.refresh(competition)
    return competition


async def add_round(
    db: AsyncSession, user: User, competition: Competition, data: RoundCreateRequest
) -> CompetitionRound:
    ensure_cohort_staff(user, competition.cohort_id)
    if any(r.round_number == data.round_number for r in competition.rounds):
        raise Conflict(f"Round {data.round_number} already exists")
    round_ = CompetitionRound(competition_id=competition.id, **data.model_dump())
    db.add(round_)
    await db.commit()
    await db.refresh(round_)
    return round_


async def update_round(
    db: AsyncSession, user: User, round_id: uuid.UUID, data: RoundUpdateRequest
) -> CompetitionRound:
    round_ = await db.get(CompetitionRound, round_id)
    if round_ is None:
        raise NotFound("Round not found")
    competition = await db.get(Competition, round_.competition_id)
    assert competition is not None
    ensure_cohort_staff(user, competition.cohort_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(round_, key, value)
    await db.commit()
    await db.refresh(round_)
    return round_


async def _cohort_mentees(db: AsyncSession, cohort_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        await db.scalars(
            select(CohortEnrollment.user_id).where(
                CohortEnrollment.cohort_id == cohort_id,
                CohortEnrollment.role == UserRole.MENTEE,
            )
        )
    )


async def add_entries(
    db: AsyncSession, user: User, competition: Competition, entries: list[EntryCreate]
) -> list[CompetitionEntry]:
    ensure_cohort_staff(user, competition.cohort_id)
    mentees = await _cohort_mentees(db, competition.cohort_id)
    round_ids = {r.id for r in competition.rounds}
    created = []
    for entry in entries:
        members = [entry.mentee_id] if entry.mentee_id else entry.team_member_ids or []
        if unknown := [m for m in members if m not in mentees]:
            raise BusinessRuleViolation(
                f"Not mentees of this cohort: {', '.join(map(str, unknown))}"
            )
        if entry.round_id and entry.round_id not in round_ids:
            raise BusinessRuleViolation("round_id does not belong to this competition")
        created.append(
            CompetitionEntry(
                competition_id=competition.id,
                round_id=entry.round_id,
                mentee_id=entry.mentee_id,
                team_name=entry.team_name,
                team_member_ids=[str(m) for m in entry.team_member_ids]
                if entry.team_member_ids
                else None,
            )
        )
    db.add_all(created)
    log_action(
        db,
        "add_competition_entries",
        user_id=user.id,
        resource_type="competition",
        resource_id=competition.id,
        count=len(created),
    )
    await db.commit()
    return created


def _involves(mentee_ids: list[uuid.UUID]) -> ColumnElement[bool]:
    """Entries by any of the mentees, individually or as a team member."""
    return or_(
        CompetitionEntry.mentee_id.in_(mentee_ids),
        *(CompetitionEntry.team_member_ids.contains([str(m)]) for m in mentee_ids),
    )


async def list_entries(
    db: AsyncSession, user: User, competition: Competition
) -> list[CompetitionEntry]:
    """Committee sees every entry; mentees their own and peer mentors their group's."""
    stmt = select(CompetitionEntry).where(
        CompetitionEntry.competition_id == competition.id
    )
    if not is_cohort_staff(user, competition.cohort_id):
        group = list(
            await db.scalars(
                select(CohortEnrollment.user_id).where(
                    CohortEnrollment.peer_mentor_id == user.id
                )
            )
        )
        stmt = stmt.where(_involves([user.id, *group]))
    return list(await db.scalars(stmt.order_by(CompetitionEntry.created_at)))


async def update_entry(
    db: AsyncSession, user: User, entry_id: uuid.UUID, data: EntryUpdateRequest
) -> CompetitionEntry:
    entry = await db.get(CompetitionEntry, entry_id)
    if entry is None:
        raise NotFound("Entry not found")
    competition = await db.get(Competition, entry.competition_id)
    assert competition is not None
    ensure_cohort_staff(user, competition.cohort_id)
    values = data.model_dump(exclude_unset=True)
    if values.get("round_id") and values["round_id"] not in {
        r.id for r in competition.rounds
    }:
        raise BusinessRuleViolation("round_id does not belong to this competition")
    for key, value in values.items():
        setattr(entry, key, value)
    log_action(
        db,
        "update_competition_entry",
        user_id=user.id,
        resource_type="competition_entry",
        resource_id=entry.id,
    )
    await db.commit()
    await db.refresh(entry)
    return entry


async def mentee_competition_status(
    db: AsyncSession, mentee_id: uuid.UUID, cohort_id: uuid.UUID
) -> list[CompetitionStatusEntry]:
    rows = await db.execute(
        select(CompetitionEntry, Competition)
        .join(Competition, Competition.id == CompetitionEntry.competition_id)
        .where(Competition.cohort_id == cohort_id, _involves([mentee_id]))
        .order_by(Competition.start_date)
    )
    result = []
    for entry, competition in rows:
        round_name = next(
            (r.round_name for r in competition.rounds if r.id == entry.round_id), None
        )
        result.append(
            CompetitionStatusEntry(
                competition_id=competition.id,
                competition_name=competition.name,
                competition_type=competition.competition_type,
                entry=EntryResponse.model_validate(entry),
                round_name=round_name,
            )
        )
    return result
