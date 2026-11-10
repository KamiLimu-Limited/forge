"""Cohort leaderboards: mentees on five dimensions and peer mentors on four.

Names are always shown.
"""

import uuid
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.models import (
    PEER_MENTOR_ROLES,
    ActivityStatus,
    ActivityType,
    Cohort,
    ExtraActivity,
    LeaderboardKind,
    LeaderboardSnapshot,
    User,
)
from forge.schemas.leaderboard import (
    DimensionEntry,
    DimensionRankingResponse,
    LeaderboardDimension,
    LeaderboardResponse,
    LeaderboardRow,
    PeerMentorDimension,
    PeerMentorLeaderboardResponse,
    PeerMentorRow,
)
from forge.services.audit import log_action
from forge.services.csv_utils import to_csv
from forge.services.points import compute_stats, mentee_enrollments

T = TypeVar("T")
D = LeaderboardDimension
ACTIVITY_DIMENSIONS = {
    ActivityType.ACADEMIC: D.ACADEMIC,
    ActivityType.EVENT: D.EVENTS,
    ActivityType.OPPORTUNITY: D.APPLICATIONS,
    ActivityType.SCHOLARSHIP: D.APPLICATIONS,
    ActivityType.CONSULTATION: D.CONSULTATIONS,
}


@dataclass
class Standing:
    user_id: uuid.UUID
    name: str
    total_points: int
    values: dict[LeaderboardDimension, float]


def dense_rank(items: list[T], key: Callable[[T], float]) -> Iterator[tuple[int, T]]:
    """Yield ``(rank, item)`` ordered by ``key`` descending; ties share a rank."""
    rank, previous = 0, None
    for item in sorted(items, key=key, reverse=True):
        if key(item) != previous:
            rank, previous = rank + 1, key(item)
        yield rank, item


async def activity_counts(
    db: AsyncSession, cohort_id: uuid.UUID
) -> defaultdict[uuid.UUID, defaultdict[ActivityType, int]]:
    counts: defaultdict[uuid.UUID, defaultdict[ActivityType, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    rows = await db.execute(
        select(ExtraActivity.mentee_id, ExtraActivity.type, func.count())
        .where(
            ExtraActivity.cohort_id == cohort_id,
            ExtraActivity.status == ActivityStatus.ACTIVE,
        )
        .group_by(ExtraActivity.mentee_id, ExtraActivity.type)
    )
    for user_id, activity_type, count in rows:
        counts[user_id][activity_type] = count
    return counts


async def standings(db: AsyncSession, cohort: Cohort) -> list[Standing]:
    enrollments = await mentee_enrollments(db, cohort.id)
    stats = await compute_stats(db, cohort.id, [e.user_id for e in enrollments])
    counts = await activity_counts(db, cohort.id)
    result = []
    for e in enrollments:
        values: dict[LeaderboardDimension, float] = dict.fromkeys(D, 0)
        values[D.CORE_ATTENDANCE] = stats[e.user_id].core_rate
        for activity_type, count in counts[e.user_id].items():
            values[ACTIVITY_DIMENSIONS[activity_type]] += count
        result.append(
            Standing(e.user_id, e.user.full_name, stats[e.user_id].total_points, values)
        )
    return result


async def leaderboard(
    db: AsyncSession, cohort: Cohort, viewer: User | None = None
) -> LeaderboardResponse:
    entries = [
        LeaderboardRow(
            rank=rank,
            mentee_id=s.user_id,
            display_name=s.name,
            is_me=viewer is not None and s.user_id == viewer.id,
            total_points=s.total_points,
            **{d.value: s.values[d] for d in LeaderboardDimension},
        )
        for rank, s in dense_rank(
            await standings(db, cohort), key=lambda s: s.total_points
        )
    ]
    return LeaderboardResponse(
        cohort_id=cohort.id, generated_at=datetime.now(UTC), entries=entries
    )


async def dimension_ranking(
    db: AsyncSession, cohort: Cohort, viewer: User, dimension: LeaderboardDimension
) -> DimensionRankingResponse:
    entries = [
        DimensionEntry(
            rank=rank,
            mentee_id=s.user_id,
            display_name=s.name,
            is_me=s.user_id == viewer.id,
            value=s.values[dimension],
        )
        for rank, s in dense_rank(
            await standings(db, cohort), key=lambda s: s.values[dimension]
        )
    ]
    return DimensionRankingResponse(
        cohort_id=cohort.id, dimension=dimension, entries=entries
    )


async def peer_mentor_leaderboard(
    db: AsyncSession,
    cohort: Cohort,
    viewer: User | None = None,
    ranked_by: PeerMentorDimension = PeerMentorDimension.OVERALL_RATE,
) -> PeerMentorLeaderboardResponse:
    enrollments = {
        e.user_id: e for e in await mentee_enrollments(db, cohort.id, PEER_MENTOR_ROLES)
    }
    stats = await compute_stats(db, cohort.id, list(enrollments))
    counts = await activity_counts(db, cohort.id)
    rows = [
        PeerMentorRow(
            rank=0,
            peer_mentor_id=user_id,
            display_name=e.user.full_name,
            is_me=viewer is not None and user_id == viewer.id,
            sessions_attended=stats[user_id].total.attended,
            extra_sessions=sum(counts[user_id].values()),
            core_rate=stats[user_id].core_rate,
            overall_rate=stats[user_id].overall_rate,
        )
        for user_id, e in enrollments.items()
    ]
    entries = [
        row.model_copy(update={"rank": rank})
        for rank, row in dense_rank(rows, key=lambda r: getattr(r, ranked_by.value))
    ]
    return PeerMentorLeaderboardResponse(
        cohort_id=cohort.id,
        ranked_by=ranked_by,
        generated_at=datetime.now(UTC),
        entries=entries,
    )


async def take_snapshot(
    db: AsyncSession, cohort: Cohort, actor: User
) -> list[LeaderboardSnapshot]:
    """Store both leaderboards as they stand now."""
    mentees = await leaderboard(db, cohort)
    peer_mentors = await peer_mentor_leaderboard(db, cohort)
    snapshots = [
        LeaderboardSnapshot(
            cohort_id=cohort.id,
            kind=kind,
            taken_by=actor.id,
            rows=[e.model_dump(mode="json", exclude={"is_me"}) for e in board.entries],
        )
        for kind, board in (
            (LeaderboardKind.MENTEE, mentees),
            (LeaderboardKind.PEER_MENTOR, peer_mentors),
        )
    ]
    db.add_all(snapshots)
    await db.flush()
    log_action(
        db,
        "snapshot_leaderboard",
        user_id=actor.id,
        resource_type="cohort",
        resource_id=cohort.id,
    )
    await db.commit()
    return snapshots


async def list_snapshots(
    db: AsyncSession, cohort: Cohort, kind: LeaderboardKind | None
) -> list[LeaderboardSnapshot]:
    stmt = select(LeaderboardSnapshot).where(LeaderboardSnapshot.cohort_id == cohort.id)
    if kind is not None:
        stmt = stmt.where(LeaderboardSnapshot.kind == kind)
    return list(await db.scalars(stmt.order_by(LeaderboardSnapshot.taken_at.desc())))


async def leaderboard_csv(
    db: AsyncSession, cohort: Cohort, kind: LeaderboardKind = LeaderboardKind.MENTEE
) -> str:
    if kind is LeaderboardKind.PEER_MENTOR:
        board = await peer_mentor_leaderboard(db, cohort)
        dims = [d.value for d in PeerMentorDimension]
        return to_csv(
            ["rank", "peer_mentor", *dims],
            [
                [e.rank, e.display_name, *(getattr(e, d) for d in dims)]
                for e in board.entries
            ],
        )
    mentees = await leaderboard(db, cohort)
    dims = [d.value for d in LeaderboardDimension]
    return to_csv(
        ["rank", "mentee", "total_points", *dims],
        [
            [e.rank, e.display_name, e.total_points, *(getattr(e, d) for d in dims)]
            for e in mentees.entries
        ],
    )
