"""Objective schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from forge.models import ObjectiveType, RatingPoint
from forge.schemas.common import Rating, RequestSchema, Schema


class ObjectiveCreateRequest(RequestSchema):
    cohort_id: UUID | None = Field(
        None, description="Defaults to your most recent cohort"
    )
    type: ObjectiveType
    text: str = Field(min_length=1, max_length=2000)


class ObjectiveUpdateRequest(RequestSchema):
    type: ObjectiveType | None = None
    text: str | None = Field(None, min_length=1, max_length=2000)


class ObjectiveRatingRequest(RequestSchema):
    rating_point: RatingPoint
    score: Rating


class ObjectiveRatingResponse(Schema):
    rating_point: RatingPoint
    score: int
    rated_at: datetime


class ObjectiveResponse(Schema):
    id: UUID
    user_id: UUID
    cohort_id: UUID
    type: ObjectiveType
    text: str
    ratings: list[ObjectiveRatingResponse]
    created_at: datetime
    updated_at: datetime


class ObjectiveWindow(Schema):
    rating_point: RatingPoint
    opens_at: datetime | None
    closes_at: datetime | None
    is_open: bool


class ObjectiveWindowsResponse(Schema):
    cohort_id: UUID
    windows: list[ObjectiveWindow]
