"""Full programme flow through the public API, plus the scheduler runner."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from forge.models import Invitation
from forge.services import scheduler
from tests.conftest import auth_header, token_for


async def test_invite_to_leaderboard(client: AsyncClient, admin_user, db_session):
    admin = token_for(admin_user)

    cohort = (
        await client.post(
            "/api/v1/cohorts",
            json={
                "name": "Cohort 11",
                "programme_type": "undergraduate",
                "start_date": str((datetime.now(UTC) - timedelta(days=30)).date()),
                "end_date": str((datetime.now(UTC) + timedelta(days=200)).date()),
                "status": "active",
            },
            headers=admin,
        )
    ).json()

    await client.post(
        "/api/v1/auth/invite",
        json={
            "email": "ada@test.com",
            "first_name": "Ada",
            "last_name": "L",
            "roles": ["mentee"],
            "cohort_id": cohort["id"],
        },
        headers=admin,
    )
    token = await db_session.scalar(
        select(Invitation.token).where(Invitation.email == "ada@test.com")
    )
    ada = (
        await client.post(
            "/api/v1/auth/activate", json={"token": token, "password": "Analytic4l"}
        )
    ).json()
    ada_headers = auth_header(ada["access_token"])

    session = (
        await client.post(
            "/api/v1/sessions",
            json={
                "cohort_id": cohort["id"],
                "title": "Engines",
                "starts_at": datetime.now(UTC).isoformat(),  # after Ada enrolled
                "duration_minutes": 60,
                "category": "thursday",
                "points": 20,
                "status": "published",
            },
            headers=admin,
        )
    ).json()

    window = (
        await client.get(
            f"/api/v1/sessions/{session['id']}/attendance-window", headers=ada_headers
        )
    ).json()
    assert window["is_open"] is True

    submitted = await client.post(
        "/api/v1/attendance",
        json={"session_id": session["id"], "quality_rating": 5, "usefulness_rating": 5},
        headers=ada_headers,
    )
    assert submitted.status_code == 201

    me = (await client.get("/api/v1/users/me", headers=ada_headers)).json()
    points = (
        await client.get(f"/api/v1/mentees/{me['id']}/points", headers=ada_headers)
    ).json()
    status = (
        await client.get(
            f"/api/v1/mentees/{me['id']}/graduation-status", headers=ada_headers
        )
    ).json()
    board = (
        await client.get(
            f"/api/v1/cohorts/{cohort['id']}/leaderboard", headers=ada_headers
        )
    ).json()

    assert points["total_points"] == 20
    assert status["status"] == "on_track"
    assert board["entries"][0] == board["entries"][0] | {
        "rank": 1,
        "is_me": True,
        "total_points": 20,
    }


async def test_run_jobs_executes_each_job_and_survives_failures():
    calls: list[str] = []

    async def ok(db):
        calls.append("ok")

    async def boom(db):
        calls.append("boom")
        raise RuntimeError("job failed")

    await scheduler.run_jobs([boom, ok])

    assert calls == ["boom", "ok"]


def test_default_jobs_registered():
    names = {job.__name__ for job in scheduler.default_jobs()}

    assert {
        "close_expired_windows",
        "dispatch_pending_emails",
        "send_graduation_warnings",
    } <= names
