"""Session scheduling endpoint tests."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from forge.models import (
    AttendanceWindow,
    Notification,
    NotificationType,
    SessionCategory,
    SessionStatus,
    UserRole,
)
from forge.services.sessions import advance_statuses
from tests.conftest import Factory, Programme, token_for


def session_payload(cohort_id, **overrides):
    starts = datetime.now(UTC) + timedelta(days=3)
    return {
        "cohort_id": str(cohort_id),
        "title": "Intro to Git",
        "starts_at": starts.isoformat(),
        "ends_at": (starts + timedelta(hours=2)).isoformat(),
        "category": "thursday",
    } | overrides


async def test_program_lead_publishes_session(
    client: AsyncClient, programme: Programme, db_session
):
    response = await client.post(
        "/api/v1/sessions",
        json=session_payload(
            programme.cohort.id,
            status="published",
            mentors=[{"user_id": str(programme.prof_mentor.id), "mentor_role": "lead"}],
            resources=[
                {"resource_type": "slides", "url": "https://example.com/slides"}
            ],
        ),
        headers=token_for(programme.program_lead),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["points"] == 10
    assert body["session_type"] == "theory"
    assert body["kami_limu_month"] >= 1
    assert body["mentors"][0]["user"]["email"] == "prof@test.com"

    detail = await client.get(
        f"/api/v1/sessions/{body['id']}", headers=token_for(programme.mentees[0])
    )
    window = detail.json()["attendance_window"]
    ends = datetime.fromisoformat(body["ends_at"])
    assert datetime.fromisoformat(window["closes_at"]) == ends + timedelta(hours=24)


async def test_committee_cannot_schedule(client: AsyncClient, programme: Programme):
    response = await client.post(
        "/api/v1/sessions",
        json=session_payload(programme.cohort.id),
        headers=token_for(programme.committee),
    )

    assert response.status_code == 403


async def test_program_delivery_lead_runs_peer_mentorship_only(
    client: AsyncClient, programme: Programme, factory: Factory
):
    pdl = await factory.user()
    await factory.enroll(pdl, programme.cohort, UserRole.PROGRAM_DELIVERY_LEAD)
    headers = token_for(pdl)
    start = datetime.now(UTC) + timedelta(days=1)

    task = await client.post(
        "/api/v1/sessions",
        json=session_payload(
            programme.cohort.id,
            category="peer_mentorship",
            ends_at=(start + timedelta(days=14)).isoformat(),
            starts_at=start.isoformat(),
        ),
        headers=headers,
    )
    thursday = await client.post(
        "/api/v1/sessions", json=session_payload(programme.cohort.id), headers=headers
    )
    edited = await client.patch(
        f"/api/v1/sessions/{task.json()['id']}",
        json={"title": "Reflection task"},
        headers=headers,
    )
    to_thursday = await client.patch(
        f"/api/v1/sessions/{task.json()['id']}",
        json={"category": "thursday"},
        headers=headers,
    )

    assert task.status_code == 201, task.text
    assert thursday.status_code == 403
    assert edited.json()["title"] == "Reflection task"
    assert to_thursday.status_code == 403


async def test_saturday_and_peer_mentorship_windows(
    client: AsyncClient, programme: Programme
):
    headers = token_for(programme.program_lead)
    starts = datetime.now(UTC) + timedelta(days=3)
    deadline = starts + timedelta(days=14)

    saturday = await client.post(
        "/api/v1/sessions",
        json=session_payload(
            programme.cohort.id, category="saturday", status="published"
        ),
        headers=headers,
    )
    peer = await client.post(
        "/api/v1/sessions",
        json=session_payload(
            programme.cohort.id,
            category="peer_mentorship",
            session_type="hands_on",
            status="published",
            starts_at=starts.isoformat(),
            ends_at=deadline.isoformat(),
        ),
        headers=headers,
    )
    too_long = await client.post(
        "/api/v1/sessions",
        json=session_payload(
            programme.cohort.id,
            ends_at=deadline.isoformat(),
            starts_at=starts.isoformat(),
        ),
        headers=headers,
    )

    sat = (
        await client.get(f"/api/v1/sessions/{saturday.json()['id']}", headers=headers)
    ).json()
    pm = (
        await client.get(f"/api/v1/sessions/{peer.json()['id']}", headers=headers)
    ).json()
    assert datetime.fromisoformat(
        sat["attendance_window"]["closes_at"]
    ) == datetime.fromisoformat(sat["ends_at"]) + timedelta(hours=48)
    assert datetime.fromisoformat(pm["attendance_window"]["closes_at"]) == deadline
    assert too_long.status_code == 422


async def test_session_enums(client: AsyncClient, programme: Programme):
    headers = token_for(programme.program_lead)

    unknown_track = await client.post(
        "/api/v1/sessions",
        json=session_payload(programme.cohort.id, track="ai"),
        headers=headers,
    )
    hybrid = await client.post(
        "/api/v1/sessions",
        json=session_payload(programme.cohort.id, mode="hybrid"),
        headers=headers,
    )
    old_type = await client.post(
        "/api/v1/sessions",
        json=session_payload(programme.cohort.id, session_type="core"),
        headers=headers,
    )

    assert unknown_track.status_code == 422
    assert hybrid.status_code == 422
    assert old_type.status_code == 422


async def test_mentees_cannot_create_or_see_drafts(
    client: AsyncClient, programme: Programme, factory: Factory
):
    draft = await factory.session(programme.cohort, status=SessionStatus.DRAFT)
    await factory.session(programme.cohort)
    mentee = token_for(programme.mentees[0])

    created = await client.post(
        "/api/v1/sessions", json=session_payload(programme.cohort.id), headers=mentee
    )
    listing = await client.get("/api/v1/sessions", headers=mentee)
    hidden = await client.get(f"/api/v1/sessions/{draft.id}", headers=mentee)
    staff = await client.get("/api/v1/sessions", headers=token_for(programme.committee))
    outsider = await client.get(
        "/api/v1/sessions", headers=token_for(programme.outsider)
    )

    assert created.status_code == 403
    assert listing.json()["total"] == 1
    assert hidden.status_code == 404
    assert staff.json()["total"] == 2
    assert outsider.json()["total"] == 0


async def test_publish_draft_via_patch(
    client: AsyncClient, programme: Programme, factory: Factory
):
    draft = await factory.session(programme.cohort, status=SessionStatus.DRAFT)
    headers = token_for(programme.program_lead)

    response = await client.patch(
        f"/api/v1/sessions/{draft.id}", json={"status": "published"}, headers=headers
    )
    detail = await client.get(f"/api/v1/sessions/{draft.id}", headers=headers)

    assert response.json()["status"] == "published"
    assert detail.json()["attendance_window"] is not None


async def test_reschedule_keeps_history_and_resets_window(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort)
    headers = token_for(programme.program_lead)
    new_start = datetime.now(UTC) + timedelta(days=7)

    response = await client.post(
        f"/api/v1/sessions/{session.id}/reschedule",
        json={"starts_at": new_start.isoformat(), "reason": "Venue unavailable"},
        headers=headers,
    )
    detail = (
        await client.get(f"/api/v1/sessions/{session.id}", headers=headers)
    ).json()

    assert response.status_code == 200
    assert detail["status"] == "rescheduled"
    ends_at = datetime.fromisoformat(detail["ends_at"])
    assert ends_at - new_start == timedelta(hours=2)
    assert detail["original_starts_at"] is not None
    assert detail["reschedule_history"][0]["reason"] == "Venue unavailable"
    assert datetime.fromisoformat(detail["attendance_window"]["opens_at"]) == new_start


async def test_cancel_session_closes_window(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort)
    headers = token_for(programme.admin)

    response = await client.request(
        "DELETE",
        f"/api/v1/sessions/{session.id}",
        json={"reason": "Holiday"},
        headers=headers,
    )
    detail = (
        await client.get(f"/api/v1/sessions/{session.id}", headers=headers)
    ).json()

    assert response.status_code == 204
    assert detail["status"] == "cancelled"
    assert detail["attendance_window"]["is_active"] is False


async def test_mentor_can_update_resources_but_not_mentee(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort)
    headers = token_for(programme.program_lead)
    await client.put(
        f"/api/v1/sessions/{session.id}/mentors",
        json={"mentors": [{"user_id": str(programme.prof_mentor.id)}]},
        headers=headers,
    )
    payload = {
        "resources": [{"resource_type": "recording", "url": "https://example.com/rec"}]
    }

    by_mentor = await client.patch(
        f"/api/v1/sessions/{session.id}/resources",
        json=payload,
        headers=token_for(programme.prof_mentor),
    )
    by_mentee = await client.patch(
        f"/api/v1/sessions/{session.id}/resources",
        json=payload,
        headers=token_for(programme.mentees[0]),
    )

    assert by_mentor.status_code == 200
    assert by_mentor.json()["resources"][0]["resource_type"] == "recording"
    assert by_mentee.status_code == 403


async def test_calendar_groups_by_month(
    client: AsyncClient, programme: Programme, factory: Factory
):
    await factory.session(programme.cohort, kami_limu_month=1)
    await factory.session(programme.cohort, kami_limu_month=2)
    await factory.session(programme.cohort, kami_limu_month=2)
    headers = token_for(programme.mentees[0])

    calendar = await client.get(
        f"/api/v1/cohorts/{programme.cohort.id}/calendar", headers=headers
    )
    month = await client.get(
        f"/api/v1/cohorts/{programme.cohort.id}/calendar/2", headers=headers
    )
    outsider = await client.get(
        f"/api/v1/cohorts/{programme.cohort.id}/calendar",
        headers=token_for(programme.outsider),
    )

    assert [(m["month"], len(m["sessions"])) for m in calendar.json()] == [
        (1, 1),
        (2, 2),
    ]
    assert len(month.json()[0]["sessions"]) == 2
    assert outsider.status_code == 403


async def test_session_filters(
    client: AsyncClient, programme: Programme, factory: Factory
):
    await factory.session(programme.cohort, kami_limu_month=1, track="web")
    await factory.session(programme.cohort, kami_limu_month=2)

    response = await client.get(
        "/api/v1/sessions",
        params={"kami_limu_month": 1, "track": "web"},
        headers=token_for(programme.committee),
    )
    unknown = await client.get(
        "/api/v1/sessions", params={"bogus": 1}, headers=token_for(programme.committee)
    )

    assert response.json()["total"] == 1
    assert unknown.status_code == 422


async def test_statuses_advance_with_the_window(
    db_session, programme: Programme, factory: Factory
):
    live = await factory.session(programme.cohort)
    done = await factory.session(
        programme.cohort, starts_at=datetime.now(UTC) - timedelta(days=5)
    )
    upcoming = await factory.session(
        programme.cohort, starts_at=datetime.now(UTC) + timedelta(days=2)
    )

    await advance_statuses(db_session)
    for session in (live, done, upcoming):
        await db_session.refresh(session)
    opened = list(
        await db_session.scalars(
            select(Notification.user_id).where(
                Notification.notification_type == NotificationType.WINDOW_OPENS,
                Notification.related_resource_id == live.id,
            )
        )
    )

    assert live.status is SessionStatus.LIVE
    assert done.status is SessionStatus.COMPLETED
    assert upcoming.status is SessionStatus.PUBLISHED
    assert {m.id for m in programme.mentees} <= set(opened)


async def test_in_progress_lists_open_windows_and_tasks(
    client: AsyncClient, programme: Programme, factory: Factory, db_session
):
    now = datetime.now(UTC)
    thursday = await factory.session(programme.cohort, title="Thursday")
    task = await factory.session(
        programme.cohort,
        title="Task",
        category=SessionCategory.PEER_MENTORSHIP,
        starts_at=now - timedelta(days=2),
        ends_at=now + timedelta(days=12),
    )
    await factory.session(
        programme.cohort, title="Old", starts_at=now - timedelta(days=5)
    )
    await factory.session(
        programme.cohort, title="Future", starts_at=now + timedelta(days=2)
    )
    await client.post(
        "/api/v1/attendance",
        json={"session_id": str(thursday.id), "status": "absent"},
        headers=token_for(programme.mentees[0]),
    )

    response = await client.get(
        "/api/v1/sessions/in-progress", headers=token_for(programme.mentees[0])
    )
    committee = await client.get(
        "/api/v1/sessions/in-progress", headers=token_for(programme.committee)
    )

    items = response.json()
    assert [i["session"]["title"] for i in items] == ["Thursday", "Task"]
    assert [i["submitted"] for i in items] == [True, False]
    window = await db_session.scalar(
        select(AttendanceWindow).where(AttendanceWindow.session_id == task.id)
    )
    assert datetime.fromisoformat(items[1]["closes_at"]) == window.closes_at
    assert committee.status_code == 403


async def test_personal_notes_are_private(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort)
    url = f"/api/v1/sessions/{session.id}/notes/me"
    mine = token_for(programme.mentees[0])

    empty = await client.get(url, headers=mine)
    saved = await client.put(url, json={"body": "remember git rebase"}, headers=mine)
    edited = await client.put(url, json={"body": "and git bisect"}, headers=mine)
    read = await client.get(url, headers=mine)
    other = await client.get(url, headers=token_for(programme.mentees[1]))

    assert empty.status_code == 404
    assert saved.json()["body"] == "remember git rebase"
    assert edited.status_code == 200
    assert read.json()["body"] == "and git bisect"
    assert other.status_code == 404
