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
    points=10,
    month=1,
    track=None,
):
    return SessionRow(
        mentee_id=MENTEE,
        session_id=uuid.uuid4(),
        title="s",
        starts_at=NOW - timedelta(days=1),
        kami_limu_month=month,
        track=track,
        session_type=SessionType.ICT if track else SessionType.CORE,
        points=points,
        record_status=status,
        window_closes_at=NOW + closes_in if closes_in is not None else None,
    )


@pytest.mark.parametrize(
    ("status", "closes_in", "expected"),
    [
        (AttendanceStatus.ATTENDED, timedelta(hours=1), SessionOutcome.ATTENDED),
        (AttendanceStatus.EXCUSED, -timedelta(hours=1), SessionOutcome.EXCUSED),
        (AttendanceStatus.MISSED, -timedelta(hours=1), SessionOutcome.ABSENT),
        (AttendanceStatus.DISPUTED, timedelta(hours=1), SessionOutcome.ABSENT),
        (None, timedelta(hours=1), SessionOutcome.UPCOMING),
        (AttendanceStatus.PENDING, timedelta(hours=1), SessionOutcome.UPCOMING),
        (None, -timedelta(hours=1), SessionOutcome.ABSENT),
        (None, None, SessionOutcome.ABSENT),
    ],
)
def test_classify(status, closes_in, expected):
    assert classify(row(status, closes_in=closes_in), NOW) is expected


def test_percent_caps_and_handles_empty():
    assert percent(5, 10) == 50.0
    assert percent(15, 10) == 100.0
    assert percent(0, 0) == 100.0


def test_tally_excludes_excused_and_upcoming():
    rows = [
        row(AttendanceStatus.ATTENDED),
        row(AttendanceStatus.ATTENDED, month=2, track="web"),
        row(AttendanceStatus.MISSED, month=2),
        row(AttendanceStatus.EXCUSED),
        row(None, closes_in=timedelta(hours=2)),
    ]
    stats = tally(rows, {MENTEE: 5}, COHORT, NOW)[MENTEE]

    assert (stats.total.earned, stats.total.available) == (20, 30)
    assert (stats.total.excused, stats.total.upcoming) == (1, 1)
    assert stats.core_rate == pytest.approx(66.67)
    assert stats.combined_rate == pytest.approx(83.33)
    assert stats.by_month[2].available == 20
    assert stats.by_track["web"].earned == 10


@pytest.mark.parametrize(
    ("earned", "extra", "final", "expected"),
    [
        (90, 0, False, GraduationStatus.ON_TRACK),
        (82, 0, False, GraduationStatus.WARNING),
        (70, 0, False, GraduationStatus.AT_RISK),
        (70, 10, False, GraduationStatus.WARNING),
        (80, 0, True, GraduationStatus.GRADUATED),
        (79, 0, True, GraduationStatus.NOT_GRADUATED),
    ],
)
def test_graduation_status(earned, extra, final, expected):
    stats = MenteeStats(
        MENTEE, COHORT, total=Tally(earned=earned, available=100), extra_points=extra
    )

    assert stats.graduation_status(80, final) is expected


def test_points_to_threshold():
    stats = MenteeStats(
        MENTEE, COHORT, total=Tally(earned=60, available=100), extra_points=5
    )

    assert stats.points_to_threshold(80) == 15
