"""Cohort analytics, cross-cohort comparison and daily snapshots."""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from statistics import fmean
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from forge.models import (
    ActivityStatus,
    ActivityType,
    AttendanceRecord,
    AttendanceStatus,
    Cohort,
    CohortAnalyticsSnapshot,
    CohortStatus,
    ExtraActivity,
    OverrideRequest,
    OverrideRequestStatus,
    ProgrammeSession,
)
from forge.schemas.analytics import (
    ActivityEngagement,
    ActivityEngagementResponse,
    AttendanceTrendResponse,
    CohortComparison,
    CohortHealthResponse,
    CrossCohortResponse,
    HealthPoint,
    HealthTrajectoryResponse,
    SessionQuality,
    SessionQualityResponse,
    TrackPerformance,
    TrackPerformanceResponse,
    TrendPoint,
)
from forge.schemas.points import GraduationStatus
from forge.services.cohorts import month_for
from forge.services.eligibility import COUNTED_STATUSES
from forge.services.points import (
    MenteeStats,
    Tally,
    compute_stats,
    load_rows,
    mentee_enrollments,
    percent,
    tally,
)


def _status_counts(
    stats: list[MenteeStats], cohort: Cohort
) -> dict[GraduationStatus, int]:
    final = cohort.status is CohortStatus.COMPLETED
    counts = dict.fromkeys(GraduationStatus, 0)
    for s in stats:
        counts[s.graduation_status(cohort.graduation_threshold, final)] += 1
    return counts


async def _all_stats(db: AsyncSession, cohort: Cohort) -> list[MenteeStats]:
    enrollments = await mentee_enrollments(db, cohort.id)
    return list(
        (await compute_stats(db, cohort.id, [e.user_id for e in enrollments])).values()
    )


async def cohort_health(db: AsyncSession, cohort: Cohort) -> CohortHealthResponse:
    stats = await _all_stats(db, cohort)
    pending_overrides = await db.scalar(
        select(func.count())
        .select_from(OverrideRequest)
        .join(ProgrammeSession, ProgrammeSession.id == OverrideRequest.session_id)
        .where(
            ProgrammeSession.cohort_id == cohort.id,
            OverrideRequest.status == OverrideRequestStatus.PENDING,
        )
    )
    pending_activities = await db.scalar(
        select(func.count()).where(
            ExtraActivity.cohort_id == cohort.id,
            ExtraActivity.status == ActivityStatus.PENDING,
        )
    )
    return CohortHealthResponse(
        cohort_id=cohort.id,
        total_mentees=len(stats),
        counts=_status_counts(stats, cohort),
        average_core_rate=round(fmean(s.core_rate for s in stats), 2) if stats else 0.0,
        average_combined_rate=round(fmean(s.combined_rate for s in stats), 2)
        if stats
        else 0.0,
        pending_override_requests=pending_overrides or 0,
        pending_activities=pending_activities or 0,
    )


async def attendance_trends(
    db: AsyncSession, cohort: Cohort
) -> AttendanceTrendResponse:
    stats = await _all_stats(db, cohort)
    months: defaultdict[int, Tally] = defaultdict(Tally)
    sessions: defaultdict[int, set[uuid.UUID]] = defaultdict(set)
    for s in stats:
        for month, t in s.by_month.items():
            m = months[month]
            m.earned, m.available = m.earned + t.earned, m.available + t.available
        for entry in s.sessions:
            sessions[entry.kami_limu_month].add(entry.session_id)
    return AttendanceTrendResponse(
        cohort_id=cohort.id,
        months=[
            TrendPoint(
                month=month,
                sessions=len(sessions[month]),
                points_earned=t.earned,
                points_available=t.available,
                rate=percent(t.earned, t.available),
            )
            for month, t in sorted(months.items())
        ],
    )


async def track_performance(
    db: AsyncSession, cohort: Cohort
) -> TrackPerformanceResponse:
    stats = await _all_stats(db, cohort)
    tracks: defaultdict[str, Tally] = defaultdict(Tally)
    mentees: defaultdict[str, int] = defaultdict(int)
    for s in stats:
        for track, t in s.by_track.items():
            agg = tracks[track]
            agg.earned += t.earned
            agg.available += t.available
            agg.attended += t.attended
            agg.due += t.due
            mentees[track] += 1
    return TrackPerformanceResponse(
        cohort_id=cohort.id,
        tracks=[
            TrackPerformance(track=k, mentees=mentees[k], bucket=t.bucket(k))
            for k, t in sorted(tracks.items())
        ],
    )


def _avg(column: Any) -> ColumnElement[Decimal | None]:
    return func.round(func.avg(column), 2)


async def session_quality(db: AsyncSession, cohort: Cohort) -> SessionQualityResponse:
    attended = (AttendanceRecord.session_id == ProgrammeSession.id) & (
        AttendanceRecord.status == AttendanceStatus.ATTENDED
    )
    rows = await db.execute(
        select(
            ProgrammeSession.id,
            ProgrammeSession.title,
            ProgrammeSession.starts_at,
            ProgrammeSession.kami_limu_month,
            func.count(AttendanceRecord.id),
            _avg(AttendanceRecord.quality_rating),
            _avg(AttendanceRecord.usefulness_rating),
            _avg(AttendanceRecord.understanding_score),
            _avg(AttendanceRecord.academic_application_score),
            _avg(AttendanceRecord.career_application_score),
        )
        .outerjoin(AttendanceRecord, attended)
        .where(
            ProgrammeSession.cohort_id == cohort.id,
            ProgrammeSession.status.in_(COUNTED_STATUSES),
        )
        .group_by(ProgrammeSession.id)
        .order_by(ProgrammeSession.starts_at)
    )
    sessions = [
        SessionQuality(
            session_id=sid,
            title=title,
            starts_at=starts_at,
            kami_limu_month=month,
            responses=responses,
            quality=_float(q),
            usefulness=_float(u),
            understanding=_float(un),
            academic_application=_float(a),
            career_application=_float(c),
        )
        for sid, title, starts_at, month, responses, q, u, un, a, c in rows
    ]
    overall = (
        await db.execute(
            select(
                _avg(AttendanceRecord.quality_rating),
                _avg(AttendanceRecord.usefulness_rating),
            )
            .join(ProgrammeSession, attended)
            .where(ProgrammeSession.cohort_id == cohort.id)
        )
    ).one()
    return SessionQualityResponse(
        cohort_id=cohort.id,
        overall_quality=_float(overall[0]),
        overall_usefulness=_float(overall[1]),
        sessions=sessions,
    )


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


async def health_trajectory(
    db: AsyncSession, cohort: Cohort
) -> HealthTrajectoryResponse:
    """Cohort status distribution as it stood at the end of each KamiLimu month."""
    now = datetime.now(UTC)
    mentee_ids = [e.user_id for e in await mentee_enrollments(db, cohort.id)]
    rows = await load_rows(db, cohort.id, mentee_ids, now)
    activities = await db.execute(
        select(
            ExtraActivity.mentee_id, ExtraActivity.date, ExtraActivity.points_awarded
        ).where(
            ExtraActivity.cohort_id == cohort.id,
            ExtraActivity.status == ActivityStatus.APPROVED,
        )
    )
    extra_by_month = [
        (mentee_id, month_for(cohort, day), points)
        for mentee_id, day, points in activities
    ]

    points = []
    for month in sorted({r.kami_limu_month for r in rows}):
        extra: defaultdict[uuid.UUID, int] = defaultdict(int)
        for mentee_id, m, pts in extra_by_month:
            if m <= month:
                extra[mentee_id] += pts
        stats = tally(
            (r for r in rows if r.kami_limu_month <= month), dict(extra), cohort.id, now
        )
        for mentee_id in mentee_ids:
            stats.setdefault(mentee_id, MenteeStats(mentee_id, cohort.id))
        values = list(stats.values())
        counts = dict.fromkeys(GraduationStatus, 0)
        for s in values:
            counts[s.graduation_status(cohort.graduation_threshold, final=False)] += 1
        points.append(
            HealthPoint(
                month=month,
                average_rate=round(fmean(s.combined_rate for s in values), 2)
                if values
                else 0.0,
                counts=counts,
            )
        )
    return HealthTrajectoryResponse(cohort_id=cohort.id, months=points)


async def activity_engagement(
    db: AsyncSession, cohort: Cohort
) -> ActivityEngagementResponse:
    rows = await db.execute(
        select(
            ExtraActivity.type,
            ExtraActivity.status,
            func.count(),
            func.sum(ExtraActivity.points_awarded),
        )
        .where(ExtraActivity.cohort_id == cohort.id)
        .group_by(ExtraActivity.type, ExtraActivity.status)
    )
    by_type: dict[ActivityType, ActivityEngagement] = {
        t: ActivityEngagement(
            type=t,
            counts=dict.fromkeys(ActivityStatus, 0),
            points_awarded=0,
            mentees_participating=0,
        )
        for t in ActivityType
    }
    for activity_type, status, count, points in rows:
        entry = by_type[activity_type]
        entry.counts[status] = count
        entry.points_awarded += int(points or 0)
    participants = await db.execute(
        select(ExtraActivity.type, func.count(func.distinct(ExtraActivity.mentee_id)))
        .where(ExtraActivity.cohort_id == cohort.id)
        .group_by(ExtraActivity.type)
    )
    for activity_type, count in participants:
        by_type[activity_type].mentees_participating = count
    return ActivityEngagementResponse(
        cohort_id=cohort.id,
        mentees=len(await mentee_enrollments(db, cohort.id)),
        types=list(by_type.values()),
    )


async def cross_cohort(db: AsyncSession, cohorts: list[Cohort]) -> CrossCohortResponse:
    comparisons = []
    for cohort in cohorts:
        health = await cohort_health(db, cohort)
        approved = await db.scalar(
            select(func.count()).where(
                ExtraActivity.cohort_id == cohort.id,
                ExtraActivity.status == ActivityStatus.APPROVED,
            )
        )
        comparisons.append(
            CohortComparison(
                cohort_id=cohort.id,
                name=cohort.name,
                start_date=cohort.start_date,
                health=health,
                activities_per_mentee=round((approved or 0) / health.total_mentees, 2)
                if health.total_mentees
                else 0.0,
            )
        )
    return CrossCohortResponse(cohorts=comparisons)


async def take_snapshot(
    db: AsyncSession, cohort: Cohort, on: date | None = None
) -> CohortAnalyticsSnapshot:
    """Store (or replace) today's metrics for a cohort."""
    metrics = {
        "health": (await cohort_health(db, cohort)).model_dump(mode="json"),
        "attendance_trends": (await attendance_trends(db, cohort)).model_dump(
            mode="json"
        ),
        "track_performance": (await track_performance(db, cohort)).model_dump(
            mode="json"
        ),
        "activity_engagement": (await activity_engagement(db, cohort)).model_dump(
            mode="json"
        ),
    }
    snapshot_date = on or datetime.now(UTC).date()
    stmt = (
        insert(CohortAnalyticsSnapshot)
        .values(
            id=uuid.uuid4(),
            cohort_id=cohort.id,
            snapshot_date=snapshot_date,
            metrics=metrics,
        )
        .on_conflict_do_update(
            index_elements=["cohort_id", "snapshot_date"], set_={"metrics": metrics}
        )
        .returning(CohortAnalyticsSnapshot)
    )
    snapshot = (
        await db.scalars(stmt, execution_options={"populate_existing": True})
    ).one()
    await db.commit()
    return snapshot


async def list_snapshots(
    db: AsyncSession, cohort: Cohort
) -> list[CohortAnalyticsSnapshot]:
    return list(
        await db.scalars(
            select(CohortAnalyticsSnapshot)
            .where(CohortAnalyticsSnapshot.cohort_id == cohort.id)
            .order_by(CohortAnalyticsSnapshot.snapshot_date)
        )
    )


async def snapshot_active_cohorts(db: AsyncSession) -> int:
    today = datetime.now(UTC).date()
    already = select(CohortAnalyticsSnapshot.cohort_id).where(
        CohortAnalyticsSnapshot.snapshot_date == today
    )
    cohorts = list(
        await db.scalars(
            select(Cohort).where(
                Cohort.status == CohortStatus.ACTIVE,
                Cohort.deleted_at.is_(None),
                Cohort.id.not_in(already),
            )
        )
    )
    for cohort in cohorts:
        await take_snapshot(db, cohort, today)
    return len(cohorts)
