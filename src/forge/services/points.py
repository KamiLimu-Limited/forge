"""Points, attendance-rate and graduation engine.

Counting rules:

* A session counts for a mentee once it has started, is published or completed,
  and applies to them (see :mod:`forge.services.eligibility`).
* ``attended`` earns the session's points. ``not_attended``, ``missed`` and
  ``disputed`` earn nothing. ``excused`` sessions leave the denominator.
* Sessions with no submission whose window is still open are *upcoming* and not
  yet counted; once the window closes they count as absent.
* The combined rate adds approved extra-activity points to the core points earned,
  capped at 100%. Graduation compares it with the cohort threshold.
"""

import math
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.config import settings
from forge.models import (
    ActivityStatus,
    AttendanceRecord,
    AttendanceStatus,
    AttendanceWindow,
    AttendanceWindowOverride,
    Cohort,
    CohortEnrollment,
    CohortStatus,
    ExtraActivity,
    Notification,
    NotificationType,
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
from forge.services.notifications import notify

ABSENT_STATUSES = (
    AttendanceStatus.NOT_ATTENDED,
    AttendanceStatus.MISSED,
    AttendanceStatus.DISPUTED,
)


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
        case AttendanceStatus.ATTENDED:
            return SessionOutcome.ATTENDED
        case AttendanceStatus.EXCUSED:
            return SessionOutcome.EXCUSED
        case status if status in ABSENT_STATUSES:
            return SessionOutcome.ABSENT
    if row.window_closes_at is not None and row.window_closes_at > now:
        return SessionOutcome.UPCOMING
    return SessionOutcome.ABSENT


def percent(part: int, whole: int) -> float:
    return round(min(part / whole, 1.0) * 100, 2) if whole else 100.0


@dataclass
class Tally:
    earned: int = 0
    available: int = 0
    attended: int = 0
    due: int = 0
    excused: int = 0
    upcoming: int = 0

    def add(self, outcome: SessionOutcome, points: int) -> None:
        match outcome:
            case SessionOutcome.ATTENDED:
                self.earned += points
                self.available += points
                self.attended += 1
                self.due += 1
            case SessionOutcome.ABSENT:
                self.available += points
                self.due += 1
            case SessionOutcome.EXCUSED:
                self.excused += 1
            case SessionOutcome.UPCOMING:
                self.upcoming += 1

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
    def combined_rate(self) -> float:
        return percent(self.total_points, self.total.available)

    def graduation_status(self, threshold: int, final: bool) -> GraduationStatus:
        rate = self.combined_rate
        if final:
            return (
                GraduationStatus.GRADUATED
                if rate >= threshold
                else GraduationStatus.NOT_GRADUATED
            )
        if rate >= threshold + settings.GRADUATION_WARNING_MARGIN:
            return GraduationStatus.ON_TRACK
        if rate >= threshold:
            return GraduationStatus.WARNING
        return GraduationStatus.AT_RISK

    def points_to_threshold(self, threshold: int) -> int:
        return max(
            math.ceil(self.total.available * threshold / 100) - self.total_points, 0
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
                points_earned=row.points if outcome is SessionOutcome.ATTENDED else 0,
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
            ProgrammeSession.starts_at <= now,
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
            ExtraActivity.status == ActivityStatus.APPROVED,
        )
        .group_by(ExtraActivity.mentee_id)
    )
    if mentee_ids is not None:
        stmt = stmt.where(ExtraActivity.mentee_id.in_(mentee_ids))
    return {mentee_id: int(total or 0) for mentee_id, total in (await db.execute(stmt))}


async def compute_stats(
    db: AsyncSession, cohort_id: uuid.UUID, mentee_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, MenteeStats]:
    """Stats for the given mentees (default: everyone in the cohort), keyed by mentee id."""
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
        sessions_excused=stats.total.excused,
        sessions_upcoming=stats.total.upcoming,
    )


async def detailed_breakdown(
    db: AsyncSession, stats: MenteeStats
) -> PointsDetailResponse:
    activities = await db.scalars(
        select(ExtraActivity)
        .where(
            ExtraActivity.cohort_id == stats.cohort_id,
            ExtraActivity.mentee_id == stats.mentee_id,
            ExtraActivity.status == ActivityStatus.APPROVED,
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
        combined_rate=stats.combined_rate,
        by_month=[t.bucket(str(m)) for m, t in sorted(stats.by_month.items())],
        by_track=[t.bucket(k) for k, t in sorted(stats.by_track.items())],
        by_session_type=[t.bucket(k) for k, t in sorted(stats.by_type.items())],
    )


def graduation(stats: MenteeStats, cohort: Cohort) -> GraduationStatusResponse:
    final = cohort.status is CohortStatus.COMPLETED
    return GraduationStatusResponse(
        mentee_id=stats.mentee_id,
        cohort_id=stats.cohort_id,
        status=stats.graduation_status(cohort.graduation_threshold, final),
        combined_rate=stats.combined_rate,
        threshold=cohort.graduation_threshold,
        warning_threshold=cohort.graduation_threshold
        + settings.GRADUATION_WARNING_MARGIN,
        points_to_threshold=stats.points_to_threshold(cohort.graduation_threshold),
        is_final=final,
    )


async def mentee_enrollments(
    db: AsyncSession, cohort_id: uuid.UUID
) -> list[CohortEnrollment]:
    return list(
        await db.scalars(
            select(CohortEnrollment).where(
                CohortEnrollment.cohort_id == cohort_id,
                CohortEnrollment.role == UserRole.MENTEE,
            )
        )
    )


async def graduation_report(
    db: AsyncSession, cohort: Cohort
) -> GraduationReportResponse:
    enrollments = await mentee_enrollments(db, cohort.id)
    stats = await compute_stats(db, cohort.id, [e.user_id for e in enrollments])
    final = cohort.status is CohortStatus.COMPLETED
    entries = [
        GraduationReportEntry(
            mentee=UserSummary.model_validate(e.user),
            peer_mentor_id=e.peer_mentor_id,
            ict_track=e.ict_track,
            total_points=stats[e.user_id].total_points,
            core_rate=stats[e.user_id].core_rate,
            combined_rate=stats[e.user_id].combined_rate,
            status=stats[e.user_id].graduation_status(
                cohort.graduation_threshold, final
            ),
        )
        for e in enrollments
    ]
    entries.sort(key=lambda e: (e.combined_rate, e.mentee.last_name))
    counts = dict.fromkeys(GraduationStatus, 0)
    for entry in entries:
        counts[entry.status] += 1
    return GraduationReportResponse(
        cohort_id=cohort.id,
        threshold=cohort.graduation_threshold,
        generated_at=datetime.now(UTC),
        counts=counts,
        mentees=entries,
    )


async def send_graduation_warnings(db: AsyncSession) -> int:
    """Warn at-risk and borderline mentees in active cohorts, at most once a week each."""
    week_ago = datetime.now(UTC) - timedelta(days=7)
    sent = 0
    for cohort in await db.scalars(
        select(Cohort).where(
            Cohort.status == CohortStatus.ACTIVE, Cohort.deleted_at.is_(None)
        )
    ):
        for mentee_id, s in (await compute_stats(db, cohort.id)).items():
            status = s.graduation_status(cohort.graduation_threshold, final=False)
            if (
                status not in (GraduationStatus.WARNING, GraduationStatus.AT_RISK)
                or s.total.due == 0
            ):
                continue
            kind = (
                NotificationType.GRADUATION_AT_RISK
                if status is GraduationStatus.AT_RISK
                else NotificationType.GRADUATION_WARNING
            )
            recently = await db.scalar(
                select(
                    exists().where(
                        Notification.user_id == mentee_id,
                        Notification.notification_type == kind,
                        Notification.created_at >= week_ago,
                    )
                )
            )
            if not recently:
                notify(
                    db,
                    [mentee_id],
                    kind,
                    {
                        "rate": s.combined_rate,
                        "threshold": cohort.graduation_threshold,
                        "cohort": cohort.name,
                    },
                    resource_type="cohort",
                    resource_id=cohort.id,
                )
                sent += 1
    await db.commit()
    return sent
