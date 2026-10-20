"""Session scheduling endpoint tests."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from forge.models import Notification, NotificationType, SessionStatus
from tests.conftest import Factory, Programme, token_for


def session_payload(cohort_id, **overrides):
    starts = datetime.now(UTC) + timedelta(days=3)
    return {
        "cohort_id": str(cohort_id),
        "title": "Intro to Git",
        "starts_at": starts.isoformat(),
        "duration_minutes": 120,
        "category": "thursday",
    } | overrides


async def test_committee_publishes_session_and_cohort_is_notified(
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
        headers=token_for(programme.committee),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["points"] == 10
    assert body["kami_limu_month"] >= 1
    assert body["mentors"][0]["user"]["email"] == "prof@test.com"

    detail = await client.get(
        f"/api/v1/sessions/{body['id']}", headers=token_for(programme.mentees[0])
    )
    window = detail.json()["attendance_window"]
    ends = datetime.fromisoformat(body["ends_at"])
    assert datetime.fromisoformat(window["closes_at"]) == ends + timedelta(hours=24)

    notified = await db_session.scalars(
        select(Notification.user_id).where(
            Notification.notification_type == NotificationType.SESSION_PUBLISHED
        )
    )
    assert {m.id for m in programme.mentees} <= set(notified)


async def test_saturday_and_peer_mentorship_windows(
    client: AsyncClient, programme: Programme
):
    headers = token_for(programme.committee)
    deadline = datetime.now(UTC) + timedelta(days=10)

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
            session_type="peer_mentorship",
            status="published",
            attendance_deadline=deadline.isoformat(),
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


async def test_ict_session_requires_offered_track(
    client: AsyncClient, programme: Programme
):
    headers = token_for(programme.committee)

    missing = await client.post(
        "/api/v1/sessions",
        json=session_payload(programme.cohort.id, session_type="ict"),
        headers=headers,
    )
    unknown = await client.post(
        "/api/v1/sessions",
        json=session_payload(programme.cohort.id, session_type="ict", track="ai"),
        headers=headers,
    )

    assert missing.status_code == 422
    assert unknown.status_code == 422


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
    headers = token_for(programme.committee)

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
    headers = token_for(programme.committee)
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
    assert detail["original_starts_at"] is not None
    assert detail["reschedule_history"][0]["reason"] == "Venue unavailable"
    assert datetime.fromisoformat(detail["attendance_window"]["opens_at"]) == new_start


async def test_cancel_session_closes_window(
    client: AsyncClient, programme: Programme, factory: Factory
):
    session = await factory.session(programme.cohort)
    headers = token_for(programme.committee)

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
    headers = token_for(programme.committee)
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
