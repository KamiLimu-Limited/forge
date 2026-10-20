"""Attendance engine tests."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from forge.models import AttendanceRecord, AttendanceStatus, SessionStatus
from forge.services.attendance import close_expired_windows
from tests.conftest import Factory, Programme, token_for

PAST = datetime.now(UTC) - timedelta(days=5)


async def submit(client, mentee, session, **extra):
    return await client.post(
        "/api/v1/attendance",
        json={
            "session_id": str(session.id),
            "quality_rating": 5,
            "usefulness_rating": 4,
            "feedback": "Great",
        }
        | extra,
        headers=token_for(mentee),
    )


async def test_submit_within_window(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort)
    mentee = programme.mentees[0]

    response = await submit(
        client, mentee, session, personal_notes="remember git rebase"
    )
    duplicate = await submit(client, mentee, session)

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "attended"
    assert response.json()["personal_notes"] == "remember git rebase"
    assert duplicate.status_code == 409


async def test_submit_rejected_when_window_closed(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort, starts_at=PAST)

    response = await submit(client, programme.mentees[0], session)

    assert response.status_code == 422
    assert "not open" in response.json()["detail"]


async def test_submit_rejected_before_session_starts(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(
        programme.cohort, starts_at=datetime.now(UTC) + timedelta(days=1)
    )

    assert (await submit(client, programme.mentees[0], session)).status_code == 422


async def test_track_session_only_for_track_mentees(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort, track="web")

    on_track = await submit(client, programme.mentees[0], session)
    off_track = await submit(client, programme.mentees[1], session)
    outsider = await submit(client, programme.outsider, session)

    assert on_track.status_code == 201
    assert off_track.status_code == 403
    assert outsider.status_code == 403


async def test_not_attended_cannot_carry_ratings(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort)

    response = await submit(
        client, programme.mentees[0], session, status="not_attended"
    )

    assert response.status_code == 422


async def test_update_and_visibility(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort)
    mentee = programme.mentees[0]
    record = (await submit(client, mentee, session, personal_notes="private")).json()
    url = f"/api/v1/attendance/{record['id']}"

    updated = await client.patch(
        url, json={"quality_rating": 3}, headers=token_for(mentee)
    )
    as_mentor = await client.get(url, headers=token_for(programme.peer_mentor))
    as_committee = await client.get(url, headers=token_for(programme.committee))
    as_peer = await client.get(url, headers=token_for(programme.mentees[1]))

    assert updated.json()["quality_rating"] == 3
    assert as_mentor.status_code == 200
    assert "personal_notes" not in as_mentor.json()
    assert as_committee.status_code == 200
    assert as_peer.status_code == 404


async def test_my_attendance_and_group_views(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort)
    for mentee in programme.mentees:
        await submit(client, mentee, session)

    mine = await client.get(
        "/api/v1/attendance/me", headers=token_for(programme.mentees[0])
    )
    group = await client.get(
        "/api/v1/peer-mentors/me/attendance", headers=token_for(programme.peer_mentor)
    )
    cohort = await client.get(
        f"/api/v1/cohorts/{programme.cohort.id}/attendance",
        headers=token_for(programme.committee),
    )
    forbidden = await client.get(
        f"/api/v1/cohorts/{programme.cohort.id}/attendance",
        headers=token_for(programme.mentees[0]),
    )

    assert mine.json()["total"] == 1
    assert group.json()["total"] == 2
    assert cohort.json()["total"] == 3
    assert forbidden.status_code == 403


async def test_window_status_and_manual_close(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort)
    mentee = token_for(programme.mentees[0])

    before = (
        await client.get(
            f"/api/v1/sessions/{session.id}/attendance-window", headers=mentee
        )
    ).json()
    closed = await client.post(
        f"/api/v1/attendance-windows/{before['window_id']}/close",
        headers=token_for(programme.admin),
    )
    after = (
        await client.get(
            f"/api/v1/sessions/{session.id}/attendance-window", headers=mentee
        )
    ).json()
    by_committee = await client.post(
        f"/api/v1/attendance-windows/{before['window_id']}/close",
        headers=token_for(programme.committee),
    )

    assert before["is_open"] is True
    assert closed.json()["is_active"] is False
    assert after["is_open"] is False
    assert by_committee.status_code == 403


async def test_override_request_workflow(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort, starts_at=PAST)
    mentee = programme.mentees[0]

    request = await client.post(
        "/api/v1/attendance/override-requests",
        json={"session_id": str(session.id), "reason": "I was in hospital"},
        headers=token_for(mentee),
    )
    assert request.status_code == 201, request.text
    request_id = request.json()["id"]

    queue = await client.get(
        "/api/v1/attendance/override-requests",
        params={"status": "pending"},
        headers=token_for(programme.committee),
    )
    assert queue.json()["total"] == 1

    by_mentee = await client.patch(
        f"/api/v1/attendance/override-requests/{request_id}/approve",
        json={},
        headers=token_for(mentee),
    )
    approved = await client.patch(
        f"/api/v1/attendance/override-requests/{request_id}/approve",
        json={"reason": "Medical note received"},
        headers=token_for(programme.committee),
    )
    again = await client.patch(
        f"/api/v1/attendance/override-requests/{request_id}/deny",
        json={},
        headers=token_for(programme.committee),
    )

    assert by_mentee.status_code == 403
    assert approved.json()["status"] == "approved"
    assert again.status_code == 422

    window = (
        await client.get(
            f"/api/v1/sessions/{session.id}/attendance-window",
            headers=token_for(mentee),
        )
    ).json()
    assert window["is_open"] is True and window["has_override"] is True
    assert (await submit(client, mentee, session)).status_code == 201


async def test_override_rejected_while_window_open(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort)

    response = await client.post(
        "/api/v1/attendance/override-requests",
        json={"session_id": str(session.id), "reason": "Just in case"},
        headers=token_for(programme.mentees[0]),
    )

    assert response.status_code == 422


async def test_committee_can_excuse(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort)
    record = (
        await submit(
            client,
            programme.mentees[0],
            session,
            status="not_attended",
            quality_rating=None,
            usefulness_rating=None,
        )
    ).json()

    response = await client.patch(
        f"/api/v1/attendance/{record['id']}/status",
        json={"status": "excused", "reason": "Exam"},
        headers=token_for(programme.committee),
    )

    assert response.json()["status"] == "excused"


async def test_close_expired_windows_marks_missed(
    db_session, programme: Programme, factory: Factory, client: AsyncClient
):
    expired = await factory.session(programme.cohort, starts_at=PAST)
    await factory.session(
        programme.cohort, starts_at=PAST, status=SessionStatus.CANCELLED
    )
    open_session = await factory.session(programme.cohort)
    await submit(client, programme.mentees[0], open_session)

    created = await close_expired_windows(db_session)
    again = await close_expired_windows(db_session)

    statuses = list(
        await db_session.scalars(
            select(AttendanceRecord.status).where(
                AttendanceRecord.session_id == expired.id
            )
        )
    )
    assert created == 3
    assert again == 0
    assert statuses == [AttendanceStatus.MISSED] * 3
