"""Pagination helper for SQLAlchemy selects."""

from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.schemas.common import PageParams

T = TypeVar("T")


async def paginate(
    db: AsyncSession, stmt: Select[T], params: PageParams
) -> tuple[list[T], int]:
    count_stmt: Select[Any] = select(func.count()).select_from(
        stmt.order_by(None).subquery()
    )
    total = await db.scalar(count_stmt) or 0
    rows = await db.scalars(stmt.offset(params.offset).limit(params.page_size))
    return list(rows.unique()), total
