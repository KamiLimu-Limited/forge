"""Points, graduation and extra-activity endpoint tests."""

from datetime import UTC, date, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from forge.models import (
    AttendanceRecord,
    AttendanceStatus,
    CohortStatus,
    Notification,
    NotificationType,
    SessionStatus,
)
from forge.services.points import send_graduation_warnings
from tests.conftest import Factory, Programme, token_for

PAST = datetime.now(UTC) - timedelta(days=10)


async def record(db, mentee, session, status=AttendanceStatus.ATTENDED):
    db.add(AttendanceRecord(mentee_id=mentee.id, session_id=session.id, status=status))
    await db.commit()


async def seed_history(db_session, factory: Factory, programme: Programme):
    """Mentee0 attends 3/4 core sessions plus the web track session; mentee1 attends 1/4."""
    sessions = [
        await factory.session(
            programme.cohort,
            starts_at=PAST + timedelta(days=i),
            kami_limu_month=1 + i // 2,
        )
        for i in range(4)
    ]
    web = await factory.session(
        programme.cohort, starts_at=PAST, track="web", session_type="ict"
    )
    await factory.session(
        programme.cohort, starts_at=PAST, status=SessionStatus.CANCELLED
    )
    await factory.session(
        programme.cohort, starts_at=datetime.now(UTC) + timedelta(days=3)
    )
    m0, m1 = programme.mentees[:2]
    for s in sessions[:3]:
        await record(db_session, m0, s)
    await record(db_session, m0, sessions[3], AttendanceStatus.EXCUSED)
    await record(db_session, m0, web)
    await record(db_session, m1, sessions[0])
    return sessions


async def test_points_breakdown_and_rates(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed_history(db_session, factory, programme)
    mentee = programme.mentees[0]
    headers = token_for(mentee)

    points = (
        await client.get(f"/api/v1/mentees/{mentee.id}/points", headers=headers)
    ).json()
    detail = (
        await client.get(
            f"/api/v1/mentees/{mentee.id}/points/breakdown", headers=headers
        )
    ).json()
    rates = (
        await client.get(
            f"/api/v1/mentees/{mentee.id}/attendance-rates", headers=headers
        )
    ).json()
    monthly = (
        await client.get(
            f"/api/v1/mentees/{mentee.id}/attendance-rates/monthly", headers=headers
        )
    ).json()

    assert points["core_points_earned"] == 40
    assert points["core_points_available"] == 40
    assert points["sessions_excused"] == 1
    assert len(detail["sessions"]) == 5
    assert rates["core_rate"] == 100.0
    assert {b["key"] for b in rates["by_track"]} == {"core", "web"}
    assert [b["key"] for b in monthly] == ["1", "2"]


async def test_mid_cohort_joiner_not_penalised(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed_history(db_session, factory, programme)
    joiner = await factory.user()
    await factory.enroll(
        joiner, programme.cohort, enrolled_at=datetime.now(UTC) - timedelta(days=1)
    )

    points = (
        await client.get(
            f"/api/v1/mentees/{joiner.id}/points", headers=token_for(joiner)
        )
    ).json()

    assert points["core_points_available"] == 0


async def test_graduation_status_and_report(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed_history(db_session, factory, programme)
    m1 = programme.mentees[1]

    status = (
        await client.get(
            f"/api/v1/mentees/{m1.id}/graduation-status", headers=token_for(m1)
        )
    ).json()
    report = await client.get(
        f"/api/v1/cohorts/{programme.cohort.id}/graduation-report",
        headers=token_for(programme.committee),
    )
    forbidden = await client.get(
        f"/api/v1/cohorts/{programme.cohort.id}/graduation-report",
        headers=token_for(m1),
    )

    assert status["status"] == "at_risk"
    assert status["combined_rate"] == 25.0
    assert status["points_to_threshold"] == 22
    body = report.json()
    assert [m["combined_rate"] for m in body["mentees"]] == [0.0, 25.0, 100.0]
    assert body["counts"]["on_track"] == 1
    assert forbidden.status_code == 403


async def test_final_graduation_when_cohort_completed(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed_history(db_session, factory, programme)
    programme.cohort.status = CohortStatus.COMPLETED
    await db_session.commit()
    m0 = programme.mentees[0]

    status = (
        await client.get(
            f"/api/v1/mentees/{m0.id}/graduation-status", headers=token_for(m0)
        )
    ).json()

    assert status == status | {"status": "graduated", "is_final": True}


async def test_progress_access_rules(client: AsyncClient, programme: Programme):
    m0, m2 = programme.mentees[0], programme.mentees[2]
    url = f"/api/v1/mentees/{m0.id}/points"

    assert (
        await client.get(url, headers=token_for(programme.peer_mentor))
    ).status_code == 200
    assert (
        await client.get(url, headers=token_for(programme.ict_mentor))
    ).status_code == 200
    assert (
        await client.get(url, headers=token_for(programme.committee))
    ).status_code == 200
    assert (await client.get(url, headers=token_for(m2))).status_code == 403
    assert (
        await client.get(
            f"/api/v1/mentees/{m2.id}/points", headers=token_for(programme.ict_mentor)
        )
    ).status_code == 403


async def test_graduation_warnings_sent_once(
    db_session, factory: Factory, programme: Programme
):
    await seed_history(db_session, factory, programme)

    first = await send_graduation_warnings(db_session)
    second = await send_graduation_warnings(db_session)

    kinds = list(
        await db_session.scalars(
            select(Notification.notification_type).where(
                Notification.user_id == programme.mentees[1].id
            )
        )
    )
    assert first >= 1 and second == 0
    assert NotificationType.GRADUATION_AT_RISK in kinds


ACADEMIC = {
    "title": "Applied git in OS course",
    "date": str(date.today()),
    "details": {"course_name": "Operating Systems", "kami_limu_pillar": "technical"},
}


async def test_activity_lifecycle_awards_points(
    client: AsyncClient, factory: Factory, programme: Programme
):
    mentee = programme.mentees[1]
    created = await client.post(
        "/api/v1/extra-activities/academic", json=ACADEMIC, headers=token_for(mentee)
    )
    assert created.status_code == 201, created.text
    activity = created.json()
    assert activity["type"] == "academic" and activity["status"] == "pending"

    edited = await client.patch(
        f"/api/v1/extra-activities/{activity['id']}",
        json={"details": {"course_name": "Distributed Systems"}},
        headers=token_for(mentee),
    )
    assert edited.json()["details"]["course_name"] == "Distributed Systems"
    assert edited.json()["details"]["kami_limu_pillar"] == "technical"

    queue = await client.get(
        "/api/v1/extra-activities/pending", headers=token_for(programme.committee)
    )
    assert queue.json()["total"] == 1

    approved = await client.patch(
        f"/api/v1/extra-activities/{activity['id']}/approve",
        json={"points_awarded": 7},
        headers=token_for(programme.committee),
    )
    assert approved.json()["points_awarded"] == 7

    locked = await client.patch(
        f"/api/v1/extra-activities/{activity['id']}",
        json={"title": "x"},
        headers=token_for(mentee),
    )
    points = (
        await client.get(
            f"/api/v1/mentees/{mentee.id}/points", headers=token_for(mentee)
        )
    ).json()
    assert locked.status_code == 422
    assert points["extra_points"] == 7


async def test_activity_types_validate_their_details(
    client: AsyncClient, programme: Programme
):
    headers = token_for(programme.mentees[0])
    base = {"title": "Something", "date": str(date.today())}

    event = await client.post(
        "/api/v1/extra-activities/events",
        json=base
        | {
            "details": {
                "event_role": "speaker",
                "mode": "virtual",
                "learnings": "Public speaking",
            }
        },
        headers=headers,
    )
    bad_event = await client.post(
        "/api/v1/extra-activities/events",
        json=base | {"details": {"course_name": "x"}},
        headers=headers,
    )
    opportunity = await client.post(
        "/api/v1/extra-activities/opportunities",
        json=base
        | {
            "details": {
                "organization": "Safaricom",
                "application_date": str(date.today()),
            }
        },
        headers=headers,
    )
    consultation = await client.post(
        "/api/v1/extra-activities/consultations",
        json=base
        | {
            "details": {
                "mentor_name": "Jane",
                "consultation_date": str(date.today()),
                "outcome": "CV review",
            }
        },
        headers=headers,
    )

    assert event.status_code == 201
    assert bad_event.status_code == 422
    assert opportunity.json()["details"]["outcome_status"] == "applied"
    assert consultation.status_code == 201


async def test_activity_visibility_and_rejection(
    client: AsyncClient, programme: Programme
):
    m0 = programme.mentees[0]
    activity = (
        await client.post(
            "/api/v1/extra-activities/academic", json=ACADEMIC, headers=token_for(m0)
        )
    ).json()
    url = f"/api/v1/extra-activities/{activity['id']}"

    assert (
        await client.get(url, headers=token_for(programme.peer_mentor))
    ).status_code == 200
    assert (
        await client.get(url, headers=token_for(programme.mentees[2]))
    ).status_code == 404
    assert (
        await client.patch(f"{url}/approve", json={}, headers=token_for(m0))
    ).status_code == 403

    rejected = await client.patch(
        f"{url}/reject",
        json={"reason": "Not related"},
        headers=token_for(programme.committee),
    )
    group = await client.get(
        "/api/v1/extra-activities", headers=token_for(programme.peer_mentor)
    )

    assert rejected.json()["status"] == "rejected"
    assert group.json()["total"] == 1


async def test_non_mentee_cannot_submit(client: AsyncClient, programme: Programme):
    response = await client.post(
        "/api/v1/extra-activities/academic",
        json=ACADEMIC,
        headers=token_for(programme.committee),
    )

    assert response.status_code == 403
