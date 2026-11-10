"""Unit tests for the points engine's pure calculations."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from forge.models import AttendanceStatus, SessionType
from forge.schemas.points import GraduationStatus, SessionOutcome
from forge.services.points import (
    MenteeStats,
    SessionRow,
    Tally,
    classify,
    percent,
    tally,
)

NOW = datetime(2026, 5, 1, tzinfo=UTC)
MENTEE = uuid.uuid4()
COHORT = uuid.uuid4()


def row(
    status: AttendanceStatus | None,
    *,
    closes_in: timedelta | None = -timedelta(hours=1),
    starts_in: timedelta = -timedelta(days=1),
    points=10,
    month=1,
    track=None,
):
    return SessionRow(
        mentee_id=MENTEE,
        session_id=uuid.uuid4(),
        title="s",
        starts_at=NOW + starts_in,
        kami_limu_month=month,
        track=track,
        session_type=SessionType.HANDS_ON if track else SessionType.THEORY,
        points=points,
        record_status=status,
        window_closes_at=NOW + closes_in if closes_in is not None else None,
    )


@pytest.mark.parametrize(
    ("status", "closes_in", "expected"),
    [
        (AttendanceStatus.PRESENT, timedelta(hours=1), SessionOutcome.PRESENT),
        (AttendanceStatus.ABSENT, timedelta(hours=1), SessionOutcome.ABSENT),
        (AttendanceStatus.EXCUSED, -timedelta(hours=1), SessionOutcome.EXCUSED),
        (AttendanceStatus.MISSED, -timedelta(hours=1), SessionOutcome.MISSED),
        (None, timedelta(hours=1), SessionOutcome.REMAINING),
        (AttendanceStatus.PENDING, timedelta(hours=1), SessionOutcome.REMAINING),
        (None, -timedelta(hours=1), SessionOutcome.MISSED),
        (None, None, SessionOutcome.MISSED),
    ],
)
def test_classify(status, closes_in, expected):
    assert classify(row(status, closes_in=closes_in), NOW) is expected


def test_future_session_is_remaining():
    future = row(None, closes_in=None, starts_in=timedelta(days=2))

    assert classify(future, NOW) is SessionOutcome.REMAINING


def test_percent_caps_and_handles_empty():
    assert percent(5, 10) == 50.0
    assert percent(15, 10) == 100.0
    assert percent(0, 0) == 100.0


def test_tally_buckets():
    rows = [
        row(AttendanceStatus.PRESENT),
        row(AttendanceStatus.PRESENT, month=2, track="web"),
        row(AttendanceStatus.MISSED, month=2),
        row(AttendanceStatus.ABSENT, points=5),
        row(AttendanceStatus.EXCUSED),
        row(None, closes_in=timedelta(hours=2)),
        row(None, closes_in=None, starts_in=timedelta(days=3), points=5),
    ]
    stats = tally(rows, {MENTEE: 5}, COHORT, NOW)[MENTEE]

    assert (stats.total.earned, stats.total.available) == (20, 35)
    assert (stats.total.missed, stats.total.missed_points) == (1, 10)
    assert stats.total.absent == 1
    assert stats.total.excused == 1
    assert (stats.total.remaining, stats.total.remaining_points) == (2, 15)
    assert stats.core_rate == pytest.approx(57.14)
    assert stats.overall_rate == pytest.approx(71.43)
    assert stats.by_month[2].available == 20
    assert stats.by_track["web"].earned == 10


@pytest.mark.parametrize(
    ("earned", "extra", "final", "expected"),
    [
        (90, 0, False, None),
        (70, 0, False, None),
        (80, 0, True, GraduationStatus.GRADUATED),
        (79, 0, True, GraduationStatus.NOT_GRADUATED),
        # Extra-activity points raise the overall rate but not the core rate.
        (79, 20, True, GraduationStatus.NOT_GRADUATED),
    ],
)
def test_graduation_status_uses_core_rate(earned, extra, final, expected):
    stats = MenteeStats(
        MENTEE, COHORT, total=Tally(earned=earned, available=100), extra_points=extra
    )

    assert stats.graduation_status(80, final) is expected


def test_points_to_threshold_counts_core_points_only():
    stats = MenteeStats(
        MENTEE, COHORT, total=Tally(earned=60, available=100), extra_points=5
    )

    assert stats.points_to_threshold(80) == 20
