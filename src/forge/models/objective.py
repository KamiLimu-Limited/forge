"""Personal objectives and their Start, Mid and End self-ratings."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from forge.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum


class ObjectiveType(enum.StrEnum):
    HUMAN = "human"
    TECHNICAL = "technical"


class RatingPoint(enum.StrEnum):
    START = "start"
    MID = "mid"
    END = "end"


class Objective(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "objectives"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[ObjectiveType] = mapped_column(pg_enum(ObjectiveType))
    text: Mapped[str] = mapped_column(Text)

    ratings: Mapped[list["ObjectiveRating"]] = relationship(
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="ObjectiveRating.rated_at",
    )


class ObjectiveRating(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "objective_ratings"
    __table_args__ = (UniqueConstraint("objective_id", "rating_point"),)

    objective_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("objectives.id", ondelete="CASCADE"), index=True
    )
    rating_point: Mapped[RatingPoint] = mapped_column(pg_enum(RatingPoint))
    score: Mapped[int] = mapped_column(SmallInteger)
    rated_at: Mapped[datetime] = mapped_column(server_default=func.now())
