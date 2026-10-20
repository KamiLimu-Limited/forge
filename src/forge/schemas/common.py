"""Shared schema building blocks."""

import math
from collections.abc import Sequence
from typing import Annotated, Any, Generic, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)


class RequestSchema(Schema):
    model_config = ConfigDict(extra="forbid")


Name = Annotated[str, StringConstraints(min_length=1, max_length=100)]
Title = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Rating = Annotated[int, Field(ge=1, le=5)]


class SuccessResponse(Schema):
    success: bool = True
    message: str


class ErrorResponse(Schema):
    success: bool = False
    error: str = Field(examples=["not_found"])
    detail: str | list[dict[str, object]] = Field(examples=["Resource not found"])


class PageParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


T = TypeVar("T")


class Page(Schema, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def build(cls, items: Sequence[Any], total: int, params: PageParams) -> Self:
        """Build a page from ORM rows; use on a parametrized class, e.g. ``Page[Out]``."""
        return cls.model_validate(
            {
                "items": items,
                "total": total,
                "page": params.page,
                "page_size": params.page_size,
                "total_pages": math.ceil(total / params.page_size),
            },
            from_attributes=True,
        )
