"""Cohort leaderboard across six dimensions."""

import uuid
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.models import ActivityStatus, ActivityType, Cohort, ExtraActivity, User
from forge.schemas.competition import (
    DimensionEntry,
    DimensionRankingResponse,
    LeaderboardDimension,
    LeaderboardResponse,
    LeaderboardRow,
)
from forge.services.access import is_cohort_staff
from forge.services.csv_utils import to_csv
from forge.services.points import compute_stats, mentee_enrollments

T = TypeVar("T")
D = LeaderboardDimension
ACTIVITY_DIMENSIONS = {
    ActivityType.ACADEMIC: D.ACADEMIC,
    ActivityType.EVENT: D.EVENTS,
    ActivityType.OPPORTUNITY: D.OPPORTUNITIES,
    ActivityType.CONSULTATION: D.CONSULTATIONS,
}


@dataclass
class Standing:
    mentee_id: uuid.UUID
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


async def standings(db: AsyncSession, cohort: Cohort) -> list[Standing]:
    enrollments = await mentee_enrollments(db, cohort.id)
    stats = await compute_stats(db, cohort.id, [e.user_id for e in enrollments])
    counts: defaultdict[uuid.UUID, dict[ActivityType, int]] = defaultdict(dict)
    rows = await db.execute(
        select(ExtraActivity.mentee_id, ExtraActivity.type, func.count())
        .where(
            ExtraActivity.cohort_id == cohort.id,
            ExtraActivity.status == ActivityStatus.APPROVED,
        )
        .group_by(ExtraActivity.mentee_id, ExtraActivity.type)
    )
    for mentee_id, activity_type, count in rows:
        counts[mentee_id][activity_type] = count

    result = []
    for e in enrollments:
        s = stats[e.user_id]
        values: dict[LeaderboardDimension, float] = {
            D.CORE_ATTENDANCE: s.core_rate,
            D.GRADUATION_RATE: s.combined_rate,
        }
        for activity_type, dimension in ACTIVITY_DIMENSIONS.items():
            values[dimension] = counts[e.user_id].get(activity_type, 0)
        result.append(Standing(e.user_id, e.user.full_name, s.total_points, values))
    return result


def _display(
    standing: Standing, viewer: User, anonymous: bool
) -> tuple[uuid.UUID | None, str]:
    if anonymous and standing.mentee_id != viewer.id:
        return None, "Anonymous mentee"
    return standing.mentee_id, standing.name


def _anonymous_for(cohort: Cohort, viewer: User) -> bool:
    return cohort.leaderboard_anonymous and not is_cohort_staff(viewer, cohort.id)


async def leaderboard(
    db: AsyncSession, cohort: Cohort, viewer: User
) -> LeaderboardResponse:
    anonymous = _anonymous_for(cohort, viewer)
    entries = []
    for rank, s in dense_rank(
        await standings(db, cohort), key=lambda s: s.total_points
    ):
        mentee_id, name = _display(s, viewer, anonymous)
        entries.append(
            LeaderboardRow(
                rank=rank,
                mentee_id=mentee_id,
                display_name=name,
                is_me=s.mentee_id == viewer.id,
                total_points=s.total_points,
                **{d.value: s.values[d] for d in LeaderboardDimension},
            )
        )
    return LeaderboardResponse(
        cohort_id=cohort.id,
        anonymous=anonymous,
        generated_at=datetime.now(UTC),
        entries=entries,
    )


async def dimension_ranking(
    db: AsyncSession, cohort: Cohort, viewer: User, dimension: LeaderboardDimension
) -> DimensionRankingResponse:
    anonymous = _anonymous_for(cohort, viewer)
    entries = []
    for rank, s in dense_rank(
        await standings(db, cohort), key=lambda s: s.values[dimension]
    ):
        mentee_id, name = _display(s, viewer, anonymous)
        entries.append(
            DimensionEntry(
                rank=rank,
                mentee_id=mentee_id,
                display_name=name,
                is_me=s.mentee_id == viewer.id,
                value=s.values[dimension],
            )
        )
    return DimensionRankingResponse(
        cohort_id=cohort.id, dimension=dimension, anonymous=anonymous, entries=entries
    )


async def leaderboard_csv(db: AsyncSession, cohort: Cohort, viewer: User) -> str:
    board = await leaderboard(db, cohort, viewer)
    dims = [d.value for d in LeaderboardDimension]
    return to_csv(
        ["rank", "mentee", "total_points", *dims],
        [
            [e.rank, e.display_name, e.total_points, *(getattr(e, d) for d in dims)]
            for e in board.entries
        ],
    )
