"""CSV report exports."""

import re
from datetime import UTC, datetime

from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.models import (
    ActivityStatus,
    AttendanceRecord,
    Cohort,
    CohortEnrollment,
    ExtraActivity,
    ProgrammeSession,
    User,
)
from forge.services.csv_utils import to_csv
from forge.services.points import (
    classify,
    graduation_report,
    load_rows,
    mentee_enrollments,
)


def csv_response(content: str, name: str) -> Response:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    filename = f"{slug}-{datetime.now(UTC):%Y%m%d}.csv"
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def attendance_csv(db: AsyncSession, cohort: Cohort) -> str:
    """One row per mentee and counted session, with the outcome and feedback ratings."""
    now = datetime.now(UTC)
    enrollments = {e.user_id: e for e in await mentee_enrollments(db, cohort.id)}
    rows = await load_rows(db, cohort.id, list(enrollments), now)
    records = {
        (r.mentee_id, r.session_id): r
        for r in await db.scalars(
            select(AttendanceRecord)
            .join(ProgrammeSession, ProgrammeSession.id == AttendanceRecord.session_id)
            .where(ProgrammeSession.cohort_id == cohort.id)
        )
    }
    lines = []
    for row in rows:
        mentee = enrollments[row.mentee_id].user
        record = records.get((row.mentee_id, row.session_id))
        lines.append(
            [
                mentee.email,
                mentee.full_name,
                row.title,
                row.starts_at.isoformat(),
                row.kami_limu_month,
                row.track or "",
                row.session_type.value,
                row.points,
                record.status.value if record else "",
                classify(row, now).value,
                *(
                    (
                        getattr(record, f)
                        if record and getattr(record, f) is not None
                        else ""
                    )
                    for f in (
                        "quality_rating",
                        "usefulness_rating",
                        "understanding_score",
                    )
                ),
            ]
        )
    return to_csv(
        [
            "email",
            "mentee",
            "session",
            "starts_at",
            "kami_limu_month",
            "track",
            "session_type",
            "points",
            "record_status",
            "outcome",
            "quality_rating",
            "usefulness_rating",
            "understanding_score",
        ],
        lines,
    )


async def full_report_csv(db: AsyncSession, cohort: Cohort) -> str:
    """One row per mentee: points, rates, graduation status and activity counts."""
    report = await graduation_report(db, cohort)
    activity_counts = dict(
        (
            await db.execute(
                select(ExtraActivity.mentee_id, func.count())
                .where(
                    ExtraActivity.cohort_id == cohort.id,
                    ExtraActivity.status == ActivityStatus.APPROVED,
                )
                .group_by(ExtraActivity.mentee_id)
            )
        ).all()
    )
    mentor_names = dict(
        (
            await db.execute(
                select(User.id, User.first_name + " " + User.last_name).where(
                    User.id.in_(
                        select(CohortEnrollment.peer_mentor_id).where(
                            CohortEnrollment.cohort_id == cohort.id
                        )
                    )
                )
            )
        ).all()
    )
    return to_csv(
        [
            "email",
            "mentee",
            "ict_track",
            "peer_mentor",
            "total_points",
            "core_rate",
            "combined_rate",
            "status",
            "approved_activities",
        ],
        [
            [
                e.mentee.email,
                f"{e.mentee.first_name} {e.mentee.last_name}",
                e.ict_track or "",
                mentor_names.get(e.peer_mentor_id, "") if e.peer_mentor_id else "",
                e.total_points,
                e.core_rate,
                e.combined_rate,
                e.status.value,
                activity_counts.get(e.mentee.id, 0),
            ]
            for e in report.mentees
        ],
    )
