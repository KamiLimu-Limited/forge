"""Averages of the nine session rating questions."""

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.models import (
    RATING_QUESTION_COUNT,
    AttendanceRecord,
    AttendanceStatus,
    Cohort,
)
from forge.schemas.dashboard import QuestionAverage
from forge.services.cohort_config import rating_questions

Averages = list[float | None]

QUESTION_NUMBERS = range(1, RATING_QUESTION_COUNT + 1)


def _average_columns() -> list[ColumnElement[float | None]]:
    return [func.avg(AttendanceRecord.ratings[n]) for n in QUESTION_NUMBERS]


def _rounded(values: Sequence[object]) -> Averages:
    return [round(float(v), 2) if v is not None else None for v in values]  # type: ignore[arg-type]


def rated() -> ColumnElement[bool]:
    return (AttendanceRecord.status == AttendanceStatus.PRESENT) & (
        AttendanceRecord.ratings.is_not(None)
    )


async def averages(
    db: AsyncSession, *conditions: ColumnElement[bool]
) -> tuple[int, Averages]:
    """Response count and per-question averages over present, rated records."""
    row = (
        await db.execute(
            select(func.count(), *_average_columns()).where(rated(), *conditions)
        )
    ).one()
    return int(row[0]), _rounded(row[1:])


async def averages_by_session(
    db: AsyncSession, session_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, Averages]]:
    if not session_ids:
        return {}
    rows = await db.execute(
        select(AttendanceRecord.session_id, func.count(), *_average_columns())
        .where(rated(), AttendanceRecord.session_id.in_(session_ids))
        .group_by(AttendanceRecord.session_id)
    )
    return {row[0]: (int(row[1]), _rounded(row[2:])) for row in rows}


def overall(values: Averages) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 2) if present else None


def describe(values: Averages, cohort: Cohort) -> list[QuestionAverage]:
    return [
        QuestionAverage(
            number=q.number, group=q.group, text=q.text, average=values[q.number - 1]
        )
        for q in rating_questions(cohort)
    ]
