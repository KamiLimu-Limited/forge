"""Points, attendance-rate and graduation engine.

Counting rules:

* A session counts for a participant once it is published (or live, completed or
  rescheduled) and applies to them (see :mod:`forge.services.eligibility`).
* ``present`` earns the session's points. ``absent`` and ``missed`` earn nothing.
  ``excused`` sessions leave the denominator.
* Sessions whose window has not closed and that have no submission are
  *remaining*: not yet counted. Once the window closes they count as missed.
* The core rate is core points earned over core points available. The overall
  rate adds active extra-activity points to the points earned, capped at 100%.
* Graduation is decided once, when the cohort graduates, on the core rate
  against the cohort threshold.
"""

import math
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.models import (
    PARTICIPANT_ROLES,
    ActivityStatus,
    AttendanceRecord,
    AttendanceStatus,
    AttendanceWindow,
    AttendanceWindowOverride,
    Cohort,
    CohortEnrollment,
    CohortStatus,
    ExtraActivity,
    ProgrammeSession,
    SessionType,
    UserRole,
)
from forge.schemas.points import (
    ActivityPointsEntry,
    AttendanceRateResponse,
    GraduationReportEntry,
    GraduationReportResponse,
    GraduationStatus,
    GraduationStatusResponse,
    PointsBreakdownResponse,
    PointsDetailResponse,
    RateBucket,
    SessionOutcome,
    SessionPointsEntry,
)
from forge.schemas.user import UserSummary
from forge.services.eligibility import COUNTED_STATUSES, applies_to_enrollment


@dataclass(frozen=True)
class SessionRow:
    mentee_id: uuid.UUID
    session_id: uuid.UUID
    title: str
    starts_at: datetime
    kami_limu_month: int
    track: str | None
    session_type: SessionType
    points: int
    record_status: AttendanceStatus | None
    window_closes_at: datetime | None


def classify(row: SessionRow, now: datetime) -> SessionOutcome:
    match row.record_status:
        case AttendanceStatus.PRESENT:
            return SessionOutcome.PRESENT
        case AttendanceStatus.ABSENT:
            return SessionOutcome.ABSENT
        case AttendanceStatus.EXCUSED:
            return SessionOutcome.EXCUSED
        case AttendanceStatus.MISSED:
            return SessionOutcome.MISSED
    closes_at = row.window_closes_at
    if row.starts_at > now or (closes_at is not None and closes_at > now):
        return SessionOutcome.REMAINING
    return SessionOutcome.MISSED


def percent(part: int, whole: int) -> float:
    return round(min(part / whole, 1.0) * 100, 2) if whole else 100.0


@dataclass
class Tally:
    earned: int = 0
    available: int = 0
    attended: int = 0
    due: int = 0
    absent: int = 0
    missed: int = 0
    missed_points: int = 0
    excused: int = 0
    remaining: int = 0
    remaining_points: int = 0

    def add(self, outcome: SessionOutcome, points: int) -> None:
        match outcome:
            case SessionOutcome.PRESENT:
                self.earned += points
                self.available += points
                self.attended += 1
                self.due += 1
            case SessionOutcome.ABSENT | SessionOutcome.MISSED:
                self.available += points
                self.due += 1
                if outcome is SessionOutcome.MISSED:
                    self.missed += 1
                    self.missed_points += points
                else:
                    self.absent += 1
            case SessionOutcome.EXCUSED:
                self.excused += 1
            case SessionOutcome.REMAINING:
                self.remaining += 1
                self.remaining_points += points

    def bucket(self, key: str) -> RateBucket:
        return RateBucket(
            key=key,
            points_earned=self.earned,
            points_available=self.available,
            sessions_attended=self.attended,
            sessions_due=self.due,
            rate=percent(self.earned, self.available),
        )


@dataclass
class MenteeStats:
    mentee_id: uuid.UUID
    cohort_id: uuid.UUID
    total: Tally = field(default_factory=Tally)
    by_month: defaultdict[int, Tally] = field(
        default_factory=lambda: defaultdict(Tally)
    )
    by_track: defaultdict[str, Tally] = field(
        default_factory=lambda: defaultdict(Tally)
    )
    by_type: defaultdict[str, Tally] = field(default_factory=lambda: defaultdict(Tally))
    sessions: list[SessionPointsEntry] = field(default_factory=list)
    extra_points: int = 0

    @property
    def total_points(self) -> int:
        return self.total.earned + self.extra_points

    @property
    def core_rate(self) -> float:
        return percent(self.total.earned, self.total.available)

    @property
    def overall_rate(self) -> float:
        return percent(self.total_points, self.total.available)

    def meets_threshold(self, threshold: int) -> bool:
        return self.core_rate >= threshold

    def graduation_status(self, threshold: int, final: bool) -> GraduationStatus | None:
        if not final:
            return None
        return (
            GraduationStatus.GRADUATED
            if self.meets_threshold(threshold)
            else GraduationStatus.NOT_GRADUATED
        )

    def points_to_threshold(self, threshold: int) -> int:
        return max(
            math.ceil(self.total.available * threshold / 100) - self.total.earned, 0
        )


def tally(
    rows: Iterable[SessionRow],
    extra_points: dict[uuid.UUID, int],
    cohort_id: uuid.UUID,
    now: datetime,
) -> dict[uuid.UUID, MenteeStats]:
    stats: dict[uuid.UUID, MenteeStats] = {}
    for row in rows:
        s = stats.setdefault(row.mentee_id, MenteeStats(row.mentee_id, cohort_id))
        outcome = classify(row, now)
        for t in (
            s.total,
            s.by_month[row.kami_limu_month],
            s.by_track[row.track or "core"],
            s.by_type[row.session_type.value],
        ):
            t.add(outcome, row.points)
        s.sessions.append(
            SessionPointsEntry(
                session_id=row.session_id,
                title=row.title,
                starts_at=row.starts_at,
                kami_limu_month=row.kami_limu_month,
                track=row.track,
                session_type=row.session_type,
                points=row.points,
                outcome=outcome,
                points_earned=row.points if outcome is SessionOutcome.PRESENT else 0,
            )
        )
    for mentee_id, points in extra_points.items():
        stats.setdefault(
            mentee_id, MenteeStats(mentee_id, cohort_id)
        ).extra_points = points
    return stats


async def load_rows(
    db: AsyncSession,
    cohort_id: uuid.UUID,
    mentee_ids: list[uuid.UUID] | None,
    now: datetime,
) -> list[SessionRow]:
    # Mirrors windows.effective_closes_at; GREATEST/LEAST ignore NULLs in Postgres.
    effective_close = func.greatest(
        func.least(AttendanceWindow.closes_at, AttendanceWindow.closed_at),
        AttendanceWindowOverride.new_closes_at,
    )
    stmt = (
        select(
            CohortEnrollment.user_id,
            ProgrammeSession.id,
            ProgrammeSession.title,
            ProgrammeSession.starts_at,
            ProgrammeSession.kami_limu_month,
            ProgrammeSession.track,
            ProgrammeSession.session_type,
            ProgrammeSession.points,
            AttendanceRecord.status,
            effective_close,
        )
        .select_from(ProgrammeSession)
        .join(CohortEnrollment, applies_to_enrollment())
        .outerjoin(
            AttendanceRecord,
            and_(
                AttendanceRecord.session_id == ProgrammeSession.id,
                AttendanceRecord.mentee_id == CohortEnrollment.user_id,
            ),
        )
        .outerjoin(AttendanceWindow, AttendanceWindow.session_id == ProgrammeSession.id)
        .outerjoin(
            AttendanceWindowOverride,
            and_(
                AttendanceWindowOverride.attendance_window_id == AttendanceWindow.id,
                AttendanceWindowOverride.mentee_id == CohortEnrollment.user_id,
            ),
        )
        .where(
            ProgrammeSession.cohort_id == cohort_id,
            ProgrammeSession.status.in_(COUNTED_STATUSES),
        )
        .order_by(ProgrammeSession.starts_at)
    )
    if mentee_ids is not None:
        stmt = stmt.where(CohortEnrollment.user_id.in_(mentee_ids))
    return [SessionRow(*row) for row in (await db.execute(stmt))]


async def load_extra_points(
    db: AsyncSession, cohort_id: uuid.UUID, mentee_ids: list[uuid.UUID] | None
) -> dict[uuid.UUID, int]:
    stmt = (
        select(ExtraActivity.mentee_id, func.sum(ExtraActivity.points_awarded))
        .where(
            ExtraActivity.cohort_id == cohort_id,
            ExtraActivity.status == ActivityStatus.ACTIVE,
        )
        .group_by(ExtraActivity.mentee_id)
    )
    if mentee_ids is not None:
        stmt = stmt.where(ExtraActivity.mentee_id.in_(mentee_ids))
    return {mentee_id: int(total or 0) for mentee_id, total in (await db.execute(stmt))}


async def compute_stats(
    db: AsyncSession, cohort_id: uuid.UUID, mentee_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, MenteeStats]:
    """Stats for the given participants (default: everyone in the cohort), keyed by id."""
    now = datetime.now(UTC)
    rows = await load_rows(db, cohort_id, mentee_ids, now)
    stats = tally(
        rows, await load_extra_points(db, cohort_id, mentee_ids), cohort_id, now
    )
    for mentee_id in mentee_ids or []:
        stats.setdefault(mentee_id, MenteeStats(mentee_id, cohort_id))
    return stats


async def mentee_stats(db: AsyncSession, enrollment: CohortEnrollment) -> MenteeStats:
    return (await compute_stats(db, enrollment.cohort_id, [enrollment.user_id]))[
        enrollment.user_id
    ]


def breakdown(stats: MenteeStats) -> PointsBreakdownResponse:
    return PointsBreakdownResponse(
        mentee_id=stats.mentee_id,
        cohort_id=stats.cohort_id,
        core_points_earned=stats.total.earned,
        core_points_available=stats.total.available,
        extra_points=stats.extra_points,
        total_points=stats.total_points,
        sessions_attended=stats.total.attended,
        sessions_due=stats.total.due,
        sessions_absent=stats.total.absent,
        sessions_missed=stats.total.missed,
        points_missed=stats.total.missed_points,
        sessions_excused=stats.total.excused,
        sessions_remaining=stats.total.remaining,
        points_remaining=stats.total.remaining_points,
    )


async def detailed_breakdown(
    db: AsyncSession, stats: MenteeStats
) -> PointsDetailResponse:
    activities = await db.scalars(
        select(ExtraActivity)
        .where(
            ExtraActivity.cohort_id == stats.cohort_id,
            ExtraActivity.mentee_id == stats.mentee_id,
            ExtraActivity.status == ActivityStatus.ACTIVE,
        )
        .order_by(ExtraActivity.date)
    )
    return PointsDetailResponse(
        **breakdown(stats).model_dump(),
        sessions=stats.sessions,
        extra_activities=[
            ActivityPointsEntry(
                activity_id=a.id,
                type=a.type,
                title=a.title,
                points_awarded=a.points_awarded,
            )
            for a in activities
        ],
    )


def rates(stats: MenteeStats) -> AttendanceRateResponse:
    return AttendanceRateResponse(
        mentee_id=stats.mentee_id,
        cohort_id=stats.cohort_id,
        core_rate=stats.core_rate,
        overall_rate=stats.overall_rate,
        by_month=[t.bucket(str(m)) for m, t in sorted(stats.by_month.items())],
        by_track=[t.bucket(k) for k, t in sorted(stats.by_track.items())],
        by_session_type=[t.bucket(k) for k, t in sorted(stats.by_type.items())],
    )


def graduation(stats: MenteeStats, cohort: Cohort) -> GraduationStatusResponse:
    final = is_final(cohort)
    return GraduationStatusResponse(
        mentee_id=stats.mentee_id,
        cohort_id=stats.cohort_id,
        status=stats.graduation_status(cohort.graduation_threshold, final),
        core_rate=stats.core_rate,
        overall_rate=stats.overall_rate,
        threshold=cohort.graduation_threshold,
        points_to_threshold=stats.points_to_threshold(cohort.graduation_threshold),
        is_final=final,
    )


def is_final(cohort: Cohort) -> bool:
    return cohort.status in (CohortStatus.COMPLETED, CohortStatus.ARCHIVED)


async def mentee_enrollments(
    db: AsyncSession,
    cohort_id: uuid.UUID,
    roles: Iterable[UserRole] = (UserRole.MENTEE,),
) -> list[CohortEnrollment]:
    return list(
        await db.scalars(
            select(CohortEnrollment).where(
                CohortEnrollment.cohort_id == cohort_id,
                CohortEnrollment.role.in_(list(roles)),
            )
        )
    )


async def participant_enrollments(
    db: AsyncSession, cohort_id: uuid.UUID
) -> list[CohortEnrollment]:
    return await mentee_enrollments(db, cohort_id, PARTICIPANT_ROLES)


async def graduation_report(
    db: AsyncSession, cohort: Cohort
) -> GraduationReportResponse:
    enrollments = await mentee_enrollments(db, cohort.id)
    stats = await compute_stats(db, cohort.id, [e.user_id for e in enrollments])
    final = is_final(cohort)
    entries = [
        GraduationReportEntry(
            mentee=UserSummary.model_validate(e.user),
            peer_mentor_id=e.peer_mentor_id,
            ict_track=e.ict_track,
            total_points=stats[e.user_id].total_points,
            core_rate=stats[e.user_id].core_rate,
            overall_rate=stats[e.user_id].overall_rate,
            status=stats[e.user_id].graduation_status(
                cohort.graduation_threshold, final
            ),
        )
        for e in enrollments
    ]
    entries.sort(key=lambda e: (e.core_rate, e.mentee.last_name))
    counts = dict.fromkeys(GraduationStatus, 0) if final else {}
    for entry in entries:
        if entry.status is not None:
            counts[entry.status] += 1
    return GraduationReportResponse(
        cohort_id=cohort.id,
        threshold=cohort.graduation_threshold,
        generated_at=datetime.now(UTC),
        counts=counts,
        mentees=entries,
    )
