"""Dashboard, notification, analytics and export tests."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy import select

from forge.core.config import settings
from forge.models import (
    ActivityStatus,
    ActivityType,
    AttendanceRecord,
    AttendanceStatus,
    EmailStatus,
    ExtraActivity,
    MentorRole,
    Notification,
    SessionMentor,
)
from forge.services import notifications as notification_service
from tests.conftest import Factory, Programme, token_for

PAST = datetime.now(UTC) - timedelta(days=10)


async def seed(db_session, factory: Factory, programme: Programme):
    core = [
        await factory.session(
            programme.cohort, starts_at=PAST + timedelta(days=i), kami_limu_month=1 + i
        )
        for i in range(2)
    ]
    web = await factory.session(
        programme.cohort,
        starts_at=PAST,
        track="web",
        session_type="ict",
        title="Web 101",
    )
    upcoming = await factory.session(
        programme.cohort, starts_at=datetime.now(UTC) + timedelta(days=2), title="Next"
    )
    db_session.add(
        SessionMentor(
            session_id=core[0].id,
            user_id=programme.prof_mentor.id,
            mentor_role=MentorRole.LEAD,
        )
    )
    m0, m1, _ = programme.mentees
    for session in (*core, web):
        db_session.add(
            AttendanceRecord(
                mentee_id=m0.id,
                session_id=session.id,
                status=AttendanceStatus.ATTENDED,
                quality_rating=5,
                usefulness_rating=4,
                feedback="Loved it",
            )
        )
    db_session.add(
        AttendanceRecord(
            mentee_id=m1.id,
            session_id=core[0].id,
            status=AttendanceStatus.ATTENDED,
            quality_rating=3,
        )
    )
    db_session.add(
        ExtraActivity(
            type=ActivityType.ACADEMIC,
            mentee_id=m1.id,
            cohort_id=programme.cohort.id,
            title="Course",
            date=date.today(),
            status=ActivityStatus.PENDING,
            details={"course_name": "OS"},
        )
    )
    await db_session.commit()
    return core, web, upcoming


async def test_mentee_dashboard(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    _, _, upcoming = await seed(db_session, factory, programme)
    headers = token_for(programme.mentees[0])

    overview = (
        await client.get("/api/v1/dashboard/mentee/overview", headers=headers)
    ).json()
    history = (
        await client.get("/api/v1/dashboard/mentee/attendance/history", headers=headers)
    ).json()
    monthly = (
        await client.get("/api/v1/dashboard/mentee/attendance/monthly", headers=headers)
    ).json()
    by_track = (
        await client.get("/api/v1/dashboard/mentee/attendance/track", headers=headers)
    ).json()
    activities = await client.get(
        "/api/v1/dashboard/mentee/extra-activities", headers=headers
    )
    as_committee = await client.get(
        "/api/v1/dashboard/mentee/overview", headers=token_for(programme.committee)
    )

    assert overview["points"]["core_points_earned"] == 30
    assert overview["graduation"]["status"] == "on_track"
    assert overview["next_session"]["id"] == str(upcoming.id)
    assert len(history) == 3
    assert [m["key"] for m in monthly] == ["1", "2"]
    assert {t["key"] for t in by_track} == {"core", "web"}
    assert activities.status_code == 200
    assert as_committee.status_code == 403


async def test_peer_mentor_dashboard(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed(db_session, factory, programme)
    headers = token_for(programme.peer_mentor)
    m0, m1, m2 = programme.mentees

    group = (
        await client.get("/api/v1/dashboard/peer-mentor/group", headers=headers)
    ).json()
    at_risk = (
        await client.get("/api/v1/dashboard/peer-mentor/at-risk", headers=headers)
    ).json()
    drill = await client.get(
        f"/api/v1/dashboard/peer-mentor/mentees/{m1.id}", headers=headers
    )
    outside = await client.get(
        f"/api/v1/dashboard/peer-mentor/mentees/{m2.id}", headers=headers
    )

    assert [m["mentee"]["id"] for m in group["mentees"]] == [str(m1.id), str(m0.id)]
    assert group["at_risk"] == 1
    assert [m["mentee"]["id"] for m in at_risk] == [str(m1.id)]
    assert drill.status_code == 200
    assert drill.json()["recent_activities"][0]["type"] == "academic"
    assert outside.status_code == 404


async def test_ict_and_professional_mentor_dashboards(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    core, web, _ = await seed(db_session, factory, programme)

    track = (
        await client.get(
            "/api/v1/dashboard/ict-peer-mentor/track-overview",
            headers=token_for(programme.ict_mentor),
        )
    ).json()
    ict_sessions = (
        await client.get(
            "/api/v1/dashboard/ict-peer-mentor/sessions",
            headers=token_for(programme.ict_mentor),
        )
    ).json()
    prof = (
        await client.get(
            "/api/v1/dashboard/professional-mentor/sessions",
            headers=token_for(programme.prof_mentor),
        )
    ).json()

    assert track["track"] == "web"
    assert [m["mentee"]["id"] for m in track["mentees"]] == [
        str(programme.mentees[0].id)
    ]
    assert track["mentees"][0]["track"]["rate"] == 100.0
    assert [s["session"]["id"] for s in ict_sessions] == [str(web.id)]
    assert ict_sessions[0]["eligible"] == 1
    assert prof[0]["session"]["id"] == str(core[0].id)
    assert prof[0]["attended"] == 2
    assert prof[0]["average_quality"] == 4.0


async def test_session_feedback_is_anonymous(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    core, _, _ = await seed(db_session, factory, programme)
    url = f"/api/v1/sessions/{core[0].id}/feedback"

    feedback = (await client.get(url, headers=token_for(programme.prof_mentor))).json()
    denied = await client.get(url, headers=token_for(programme.mentees[0]))

    assert feedback["responses"] == 2
    assert feedback["averages"]["quality_rating"] == 4.0
    assert all(e["respondent"].startswith("Mentee-") for e in feedback["entries"])
    assert str(programme.mentees[0].id) not in str(feedback)
    assert denied.status_code == 403


async def test_committee_dashboard(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed(db_session, factory, programme)
    headers = token_for(programme.committee)
    params = {"cohort_id": str(programme.cohort.id)}

    health = (
        await client.get(
            "/api/v1/dashboard/committee/cohort-health", params=params, headers=headers
        )
    ).json()
    queue = (
        await client.get(
            "/api/v1/dashboard/committee/activities-queue",
            params=params,
            headers=headers,
        )
    ).json()
    overrides = await client.get(
        "/api/v1/dashboard/committee/override-queue", params=params, headers=headers
    )
    trends = await client.get(
        "/api/v1/dashboard/committee/analytics/attendance-trends",
        params=params,
        headers=headers,
    )
    quality = await client.get(
        "/api/v1/dashboard/committee/analytics/session-quality",
        params=params,
        headers=headers,
    )
    tracks = await client.get(
        "/api/v1/dashboard/committee/analytics/track-performance",
        params=params,
        headers=headers,
    )
    denied = await client.get(
        "/api/v1/dashboard/committee/cohort-health",
        params=params,
        headers=token_for(programme.mentees[0]),
    )

    assert health["total_mentees"] == 3
    assert health["pending_activities"] == 1
    assert health["counts"]["on_track"] == 1
    assert queue["total"] == 1
    assert overrides.json()["total"] == 0
    assert trends.status_code == quality.status_code == tracks.status_code == 200
    assert denied.status_code == 403


async def test_analytics_endpoints(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed(db_session, factory, programme)
    headers = token_for(programme.committee)
    base = f"/api/v1/analytics/cohorts/{programme.cohort.id}"

    trends = (await client.get(f"{base}/attendance-trends", headers=headers)).json()
    tracks = (await client.get(f"{base}/track-performance", headers=headers)).json()
    quality = (await client.get(f"{base}/session-quality", headers=headers)).json()
    trajectory = (await client.get(f"{base}/health-trajectory", headers=headers)).json()
    engagement = (await client.get(f"{base}/extra-activities", headers=headers)).json()

    assert [(m["month"], m["sessions"]) for m in trends["months"]] == [(1, 2), (2, 1)]
    assert {t["track"] for t in tracks["tracks"]} == {"core", "web"}
    assert quality["overall_quality"] == 4.5
    assert [p["month"] for p in trajectory["months"]] == [1, 2]
    academic = next(t for t in engagement["types"] if t["type"] == "academic")
    assert academic["counts"]["pending"] == 1 and academic["mentees_participating"] == 1


async def test_snapshots_and_cross_cohort(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed(db_session, factory, programme)
    other = await factory.cohort()
    headers = token_for(programme.admin)
    base = f"/api/v1/analytics/cohorts/{programme.cohort.id}/snapshots"

    first = await client.post(base, headers=headers)
    second = await client.post(base, headers=headers)
    listing = (await client.get(base, headers=headers)).json()
    cross = await client.get(
        "/api/v1/analytics/cross-cohort",
        params=[
            ("cohort_ids", str(programme.cohort.id)),
            ("cohort_ids", str(other.id)),
        ],
        headers=headers,
    )
    cross_denied = await client.get(
        "/api/v1/analytics/cross-cohort",
        params=[
            ("cohort_ids", str(programme.cohort.id)),
            ("cohort_ids", str(other.id)),
        ],
        headers=token_for(programme.committee),
    )

    assert first.status_code == second.status_code == 201
    assert len(listing) == 1
    assert listing[0]["metrics"]["health"]["total_mentees"] == 3
    assert len(cross.json()["cohorts"]) == 2
    assert cross_denied.status_code == 403


async def test_csv_exports(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed(db_session, factory, programme)
    headers = token_for(programme.committee)
    cid = programme.cohort.id

    attendance = await client.post(f"/api/v1/exports/attendance/{cid}", headers=headers)
    report = await client.post(f"/api/v1/exports/full-report/{cid}", headers=headers)
    leaderboard = await client.post(
        f"/api/v1/exports/leaderboard/{cid}", headers=headers
    )
    denied = await client.post(
        f"/api/v1/exports/attendance/{cid}", headers=token_for(programme.mentees[0])
    )

    attendance_lines = attendance.text.strip().splitlines()
    assert attendance_lines[0].startswith("email,mentee,session")
    assert (
        len(attendance_lines) == 1 + 2 * 3 + 1
    )  # core sessions for 3 mentees + web for its 1 mentee
    report_lines = report.text.strip().splitlines()
    assert len(report_lines) == 4
    assert "Peer User" in report.text
    assert leaderboard.status_code == 200
    assert denied.status_code == 403


async def test_notification_endpoints(
    client: AsyncClient, db_session, programme: Programme
):
    mentee = programme.mentees[0]
    broadcast = await client.post(
        "/api/v1/notifications/broadcast",
        json={
            "title": "Welcome",
            "message": "Kickoff on Saturday",
            "cohort_id": str(programme.cohort.id),
            "roles": ["mentee"],
        },
        headers=token_for(programme.admin),
    )
    assert broadcast.json() == {"recipients": 3}

    headers = token_for(mentee)
    mine = (
        await client.get(
            "/api/v1/notifications/me", params={"unread_only": True}, headers=headers
        )
    ).json()
    assert mine["total"] == 1 and mine["items"][0]["title"] == "Welcome"
    assert (
        await client.get("/api/v1/notifications/me/unread-count", headers=headers)
    ).json() == {"unread": 1}

    read = await client.patch(
        f"/api/v1/notifications/{mine['items'][0]['id']}/read", headers=headers
    )
    other = await client.patch(
        f"/api/v1/notifications/{mine['items'][0]['id']}/read",
        headers=token_for(programme.mentees[1]),
    )
    all_read = await client.patch(
        "/api/v1/notifications/read-all", headers=token_for(programme.mentees[1])
    )
    not_admin = await client.post(
        "/api/v1/notifications/broadcast",
        json={"title": "x", "message": "y"},
        headers=headers,
    )

    assert read.json()["read_at"] is not None
    assert other.status_code == 404
    assert all_read.json() == {"updated": 1}
    assert not_admin.status_code == 403


async def test_email_dispatch_retries_and_reports_failures(
    client: AsyncClient, db_session, programme: Programme, monkeypatch
):
    notification_service.notify(
        db_session,
        [programme.mentees[0].id],
        notification_service.NotificationType.BROADCAST,
        {"title": "t", "message": "m"},
    )
    await db_session.commit()
    monkeypatch.setattr(
        notification_service,
        "send_email",
        AsyncMock(side_effect=RuntimeError("provider down")),
    )

    for _ in range(settings.NOTIFICATION_MAX_ATTEMPTS + 1):
        await notification_service.dispatch_pending_emails(db_session)

    notification = await db_session.scalar(
        select(Notification).where(Notification.user_id == programme.mentees[0].id)
    )
    assert notification.email_status is EmailStatus.FAILED
    assert notification.email_attempts == settings.NOTIFICATION_MAX_ATTEMPTS
    failed = await client.get(
        "/api/v1/notifications/failed", headers=token_for(programme.admin)
    )
    assert failed.json()["items"][0]["email_last_error"] == "provider down"

    monkeypatch.setattr(
        notification_service, "send_email", AsyncMock(return_value={"id": "ok"})
    )
    notification = await db_session.get(Notification, notification.id)
    notification.email_attempts = 0
    await db_session.commit()
    assert await notification_service.dispatch_pending_emails(db_session) == 1
