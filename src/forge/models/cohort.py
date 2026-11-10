"""Cohort and enrollment models."""

import copy
import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from forge.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from forge.models.activity import ActivityType, OpportunityStage
from forge.models.user import User, UserRole


class CohortStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


# Completed and archived cohorts are a read-only record.
READ_ONLY_STATUSES = (CohortStatus.COMPLETED, CohortStatus.ARCHIVED)


class RatingGroup(enum.StrEnum):
    REACTION = "reaction"
    LEARNING = "learning"
    INTENDED_BEHAVIOUR = "intended_behaviour"


_STAGE_POINTS = {
    OpportunityStage.APPLIED: 2,
    OpportunityStage.GENERAL_INTERVIEW: 3,
    OpportunityStage.TECHNICAL_INTERVIEW: 4,
    OpportunityStage.FINAL_INTERVIEW: 5,
    OpportunityStage.OFFER_MADE: 6,
}

DEFAULT_POINTS_CONFIG: dict[str, Any] = {
    ActivityType.ACADEMIC: 4,
    ActivityType.EVENT: 4,
    ActivityType.CONSULTATION: 5,
    ActivityType.OPPORTUNITY: _STAGE_POINTS,
    ActivityType.SCHOLARSHIP: _STAGE_POINTS,
    "targets": dict.fromkeys(ActivityType, 0),
}

# Questions 1-3 measure reaction, 4-6 learning and 7-9 intended behaviour.
DEFAULT_RATING_QUESTIONS: list[dict[str, Any]] = [
    {"group": group, "text": text}
    for group, text in [
        (
            RatingGroup.REACTION,
            "How would you rate the overall quality of this session?",
        ),
        (RatingGroup.REACTION, "How useful was this session to you?"),
        (RatingGroup.REACTION, "How engaging was the facilitator?"),
        (RatingGroup.LEARNING, "How well did you understand the topics covered?"),
        (
            RatingGroup.LEARNING,
            "How confident are you that you could explain what you learnt to someone else?",
        ),
        (RatingGroup.LEARNING, "How much new knowledge or skill did you gain?"),
        (
            RatingGroup.INTENDED_BEHAVIOUR,
            "How likely are you to apply these lessons in your academic work?",
        ),
        (
            RatingGroup.INTENDED_BEHAVIOUR,
            "How likely are you to apply these lessons in your career preparation?",
        ),
        (
            RatingGroup.INTENDED_BEHAVIOUR,
            "How likely are you to act on this topic within the next two weeks?",
        ),
    ]
]


def default_points_config() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_POINTS_CONFIG)


def default_rating_questions() -> list[dict[str, Any]]:
    return copy.deepcopy(DEFAULT_RATING_QUESTIONS)


class ProgrammeType(enum.StrEnum):
    UNDERGRADUATE = "undergraduate"
    POSTGRADUATE = "postgraduate"


class Cohort(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "cohorts"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    programme_type: Mapped[ProgrammeType] = mapped_column(pg_enum(ProgrammeType))
    start_date: Mapped[date]
    end_date: Mapped[date]
    # Minimum core attendance rate (percent) required to graduate.
    graduation_threshold: Mapped[int] = mapped_column(default=80, server_default="80")
    # [{"month": 1, "name": "...", "start": "2026-01-01", "end": "2026-01-31"}, ...]
    kami_limu_month_boundaries: Mapped[list[dict[str, Any]] | None]
    status: Mapped[CohortStatus] = mapped_column(
        pg_enum(CohortStatus), default=CohortStatus.DRAFT, server_default="draft"
    )
    thursday_window_hours: Mapped[int] = mapped_column(default=24, server_default="24")
    saturday_window_hours: Mapped[int] = mapped_column(default=48, server_default="48")
    # {"start": {"opens_at": ..., "closes_at": ...}, "mid": {...}, "end": {...}}
    objective_windows: Mapped[dict[str, Any] | None]
    # Days after an activity's date during which it can still be logged or edited.
    extra_log_window_days: Mapped[int] = mapped_column(default=30, server_default="30")
    track_selection_opens_at: Mapped[datetime | None]
    track_selection_closes_at: Mapped[datetime | None]
    points_config: Mapped[dict[str, Any]] = mapped_column(default=default_points_config)
    rating_questions: Mapped[list[dict[str, Any]]] = mapped_column(
        default=default_rating_questions
    )
    is_imported: Mapped[bool] = mapped_column(default=False, server_default="false")
    closed_at: Mapped[datetime | None]
    archived_at: Mapped[datetime | None]

    enrollments: Mapped[list["CohortEnrollment"]] = relationship(
        back_populates="cohort", cascade="all, delete-orphan", passive_deletes=True
    )
    ict_tracks: Mapped[list["CohortIctTrack"]] = relationship(
        back_populates="cohort",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="CohortIctTrack.name",
    )

    @property
    def is_read_only(self) -> bool:
        return self.status in READ_ONLY_STATUSES

    @property
    def ict_track_names(self) -> list[str]:
        return [t.name for t in self.ict_tracks]

    def __repr__(self) -> str:
        return f"<Cohort {self.name}>"


class CohortIctTrack(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An ICT specialisation offered in a cohort, led by an ICT peer mentor."""

    __tablename__ = "cohort_ict_tracks"
    __table_args__ = (UniqueConstraint("cohort_id", "name"),)

    cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    lead_mentor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    cohort: Mapped[Cohort] = relationship(back_populates="ict_tracks")
    lead_mentor: Mapped[User | None] = relationship(lazy="joined")


class CohortEnrollment(Base, UUIDPrimaryKeyMixin):
    """A user's participation in a cohort in a given role."""

    __tablename__ = "cohort_enrollments"
    __table_args__ = (UniqueConstraint("user_id", "cohort_id", "role"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole))
    # The 1:1 peer mentor responsible for this mentee; mentees sharing it form a group.
    peer_mentor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    ict_track: Mapped[str | None] = mapped_column(String(100))
    enrolled_at: Mapped[datetime] = mapped_column(server_default=func.now())
    enrolled_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Set when the cohort closes; archived peer mentor assignments grant no access.
    archived_at: Mapped[datetime | None]

    cohort: Mapped[Cohort] = relationship(back_populates="enrollments")
    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")
