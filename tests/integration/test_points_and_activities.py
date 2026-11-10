"""Points, graduation and extra-activity endpoint tests."""

from datetime import UTC, date, datetime, timedelta

from httpx import AsyncClient

from forge.models import (
    AttendanceRecord,
    AttendanceStatus,
    CohortStatus,
    Consultant,
    SessionStatus,
    SessionType,
)
from tests.conftest import Factory, Programme, token_for

PAST = datetime.now(UTC) - timedelta(days=10)


async def record(db, mentee, session, status=AttendanceStatus.PRESENT):
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
        programme.cohort,
        starts_at=PAST,
        track="web",
        session_type=SessionType.HANDS_ON,
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
    assert (points["sessions_remaining"], points["points_remaining"]) == (1, 10)
    assert points["sessions_missed"] == 0
    assert len(detail["sessions"]) == 6
    assert rates["core_rate"] == 100.0
    assert rates["overall_rate"] == 100.0
    assert {b["key"] for b in rates["by_track"]} == {"core", "web"}
    assert [b["key"] for b in monthly] == ["1", "2"]


async def test_missed_bucket(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed_history(db_session, factory, programme)
    m1 = programme.mentees[1]

    points = (
        await client.get(f"/api/v1/mentees/{m1.id}/points", headers=token_for(m1))
    ).json()

    assert (points["sessions_missed"], points["points_missed"]) == (3, 30)


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

    assert status["status"] is None
    assert status["core_rate"] == 25.0
    assert status["points_to_threshold"] == 22
    assert "warning_threshold" not in status
    body = report.json()
    assert [m["core_rate"] for m in body["mentees"]] == [0.0, 25.0, 100.0]
    assert {m["status"] for m in body["mentees"]} == {None}
    assert body["counts"] == {}
    assert forbidden.status_code == 403


async def test_final_graduation_when_cohort_completed(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed_history(db_session, factory, programme)
    programme.cohort.status = CohortStatus.COMPLETED
    await db_session.commit()
    m0, m1 = programme.mentees[:2]

    def status(mentee):
        return client.get(
            f"/api/v1/mentees/{mentee.id}/graduation-status", headers=token_for(mentee)
        )

    graduate = (await status(m0)).json()
    assert (graduate["status"], graduate["is_final"]) == ("graduated", True)
    assert (await status(m1)).json()["status"] == "not_graduated"


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


async def test_removed_and_phase_two_routes_are_not_served(client: AsyncClient):
    paths = (await client.get("/api/v1/openapi.json")).json()["paths"]

    for path in [
        "/api/v1/cohorts/{cohort_id}",
        "/api/v1/extra-activities/pending",
        "/api/v1/extra-activities/{activity_id}/approve",
        "/api/v1/extra-activities/{activity_id}/reject",
        "/api/v1/dashboard/committee/activities-queue",
        "/api/v1/dashboard/committee/override-queue",
        "/api/v1/cohorts/{cohort_id}/leaderboard/settings",
        "/api/v1/dashboard/peer-mentor/at-risk",
        "/api/v1/skill-ratings",
        "/api/v1/mentees/{mentee_id}/skill-progress",
        "/api/v1/peer-mentor-tasks",
        "/api/v1/competitions",
        "/api/v1/peer-mentor/notes",
        "/api/v1/ict-peer-mentor/progress-notes",
    ]:
        if path == "/api/v1/cohorts/{cohort_id}":
            assert "delete" not in paths[path]
        else:
            assert path not in paths, path


ACADEMIC = {
    "title": "Operating Systems coursework",
    "date": str(date.today()),
    "details": {
        "kami_limu_pillar": "ICT",
        "related_session_ids": ["00000000-0000-0000-0000-000000000001"],
        "how_applied": "Used git branching for the group project",
    },
}
APPLICATION = {
    "title": "Software Engineering intern",
    "date": str(date.today()),
    "details": {
        "organisation": "Safaricom",
        "date_applied": str(date.today()),
        "how_applied": "Used the resume session",
    },
}


async def test_points_awarded_on_submission(client: AsyncClient, programme: Programme):
    mentee = programme.mentees[1]
    created = await client.post(
        "/api/v1/extra-activities/academic", json=ACADEMIC, headers=token_for(mentee)
    )
    assert created.status_code == 201, created.text
    activity = created.json()
    assert activity["status"] == "active"
    assert activity["points_awarded"] == 4

    edited = await client.patch(
        f"/api/v1/extra-activities/{activity['id']}",
        json={"details": {"how_applied": "Code review practice"}},
        headers=token_for(mentee),
    )
    points = (
        await client.get(
            f"/api/v1/mentees/{mentee.id}/points", headers=token_for(mentee)
        )
    ).json()

    assert edited.json()["details"]["how_applied"] == "Code review practice"
    assert edited.json()["details"]["kami_limu_pillar"] == "ICT"
    assert points["extra_points"] == 4


async def test_stage_updates_recalculate_points(
    client: AsyncClient, programme: Programme
):
    headers = token_for(programme.mentees[0])
    job = (
        await client.post(
            "/api/v1/extra-activities/opportunities", json=APPLICATION, headers=headers
        )
    ).json()
    url = f"/api/v1/extra-activities/{job['id']}"

    interviewed = await client.patch(
        url, json={"details": {"stage": "technical_interview"}}, headers=headers
    )
    bad_outcome = await client.patch(
        url,
        json={"details": {"final_outcome": "offer_made_and_accepted"}},
        headers=headers,
    )
    offered = await client.patch(
        url,
        json={
            "details": {
                "stage": "offer_made",
                "final_outcome": "offer_made_and_accepted",
            }
        },
        headers=headers,
    )

    assert job["points_awarded"] == 2
    assert job["details"]["final_outcome"] == "waiting_for_response"
    assert interviewed.json()["points_awarded"] == 4
    assert bad_outcome.status_code == 422
    assert offered.json()["points_awarded"] == 6


async def test_points_follow_cohort_config(client: AsyncClient, programme: Programme):
    config_url = f"/api/v1/cohorts/{programme.cohort.id}/points-config"
    config = await client.get(config_url, headers=token_for(programme.mentees[0]))
    assert config.status_code == 200
    body = config.json() | {"academic": 7}
    body["targets"]["academic"] = 3

    forbidden = await client.put(
        config_url, json=body, headers=token_for(programme.committee)
    )
    updated = await client.put(
        config_url, json=body, headers=token_for(programme.program_lead)
    )
    await client.post(
        "/api/v1/extra-activities/academic",
        json=ACADEMIC,
        headers=token_for(programme.mentees[0]),
    )
    progress = (
        await client.get(
            "/api/v1/extra-activities/me/progress",
            headers=token_for(programme.mentees[0]),
        )
    ).json()

    assert forbidden.status_code == 403
    assert updated.json()["academic"] == 7
    academic = next(t for t in progress["types"] if t["type"] == "academic")
    assert academic == {"type": "academic", "logged": 1, "target": 3, "points": 7}


async def test_activity_types_validate_their_details(
    client: AsyncClient, db_session, programme: Programme
):
    headers = token_for(programme.mentees[0])
    base = {"title": "Something", "date": str(date.today())}
    consultant = Consultant(name="Jane Doe")
    db_session.add(consultant)
    await db_session.commit()

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
    bad_role = await client.post(
        "/api/v1/extra-activities/events",
        json=base
        | {
            "details": {
                "event_role": "volunteer",
                "mode": "virtual",
                "learnings": "x",
            }
        },
        headers=headers,
    )
    scholarship = await client.post(
        "/api/v1/extra-activities/scholarships", json=APPLICATION, headers=headers
    )
    consultation = {
        "consultant_id": str(consultant.id),
        "details": {"consultation_type": "Career", "summary": "CV review"},
    }
    completed = await client.post(
        "/api/v1/extra-activities/consultations",
        json=base | consultation,
        headers=headers,
    )
    scheduled = await client.post(
        "/api/v1/extra-activities/consultations",
        json=base
        | consultation
        | {"details": consultation["details"] | {"status": "scheduled"}},
        headers=headers,
    )
    unknown_consultant = await client.post(
        "/api/v1/extra-activities/consultations",
        json=base | consultation | {"consultant_id": str(programme.admin.id)},
        headers=headers,
    )

    assert event.json()["points_awarded"] == 4
    assert bad_role.status_code == 422
    assert scholarship.json()["type"] == "scholarship"
    assert completed.json()["points_awarded"] == 5
    assert scheduled.json()["points_awarded"] == 0
    assert unknown_consultant.status_code == 404


async def test_log_window(client: AsyncClient, programme: Programme):
    headers = token_for(programme.mentees[0])

    too_old = await client.post(
        "/api/v1/extra-activities/academic",
        json=ACADEMIC | {"date": str(date.today() - timedelta(days=31))},
        headers=headers,
    )
    future = await client.post(
        "/api/v1/extra-activities/academic",
        json=ACADEMIC | {"date": str(date.today() + timedelta(days=1))},
        headers=headers,
    )

    assert too_old.status_code == 422
    assert future.status_code == 422


async def test_activity_visibility_and_reversal(
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
    for user in (m0, programme.committee):
        assert (
            await client.post(
                f"{url}/reverse",
                json={"reason": "Not related"},
                headers=token_for(user),
            )
        ).status_code == 403

    reversed_ = await client.post(
        f"{url}/reverse",
        json={"reason": "Not related"},
        headers=token_for(programme.program_lead),
    )
    again = await client.post(
        f"{url}/reverse", json={"reason": "Twice"}, headers=token_for(programme.admin)
    )
    edit = await client.patch(url, json={"title": "x"}, headers=token_for(m0))
    points = (
        await client.get(f"/api/v1/mentees/{m0.id}/points", headers=token_for(m0))
    ).json()
    group = await client.get(
        "/api/v1/extra-activities", headers=token_for(programme.peer_mentor)
    )

    body = reversed_.json()
    assert (body["status"], body["points_awarded"]) == ("reversed", 0)
    assert body["reversal_reason"] == "Not related"
    assert again.status_code == 422
    assert edit.status_code == 422
    assert points["extra_points"] == 0
    assert group.json()["total"] == 1


async def test_peer_mentor_can_log_but_committee_cannot(
    client: AsyncClient, programme: Programme
):
    peer = await client.post(
        "/api/v1/extra-activities/academic",
        json=ACADEMIC,
        headers=token_for(programme.peer_mentor),
    )
    committee = await client.post(
        "/api/v1/extra-activities/academic",
        json=ACADEMIC,
        headers=token_for(programme.committee),
    )

    assert peer.status_code == 201
    assert committee.status_code == 403


async def test_consultant_roster(client: AsyncClient, programme: Programme):
    admin = token_for(programme.admin)
    created = await client.post(
        "/api/v1/consultants", json={"name": "Dr. Achieng"}, headers=admin
    )
    consultant = created.json()
    url = f"/api/v1/consultants/{consultant['id']}"

    forbidden = await client.post(
        "/api/v1/consultants",
        json={"name": "x"},
        headers=token_for(programme.program_lead),
    )
    renamed = await client.patch(url, json={"organisation": "UoN"}, headers=admin)
    listed = await client.get(
        "/api/v1/consultants", headers=token_for(programme.mentees[0])
    )
    deleted = await client.delete(url, headers=admin)
    after = await client.get("/api/v1/consultants", headers=admin)

    assert created.status_code == 201
    assert forbidden.status_code == 403
    assert renamed.json()["organisation"] == "UoN"
    assert [c["name"] for c in listed.json()] == ["Dr. Achieng"]
    assert deleted.status_code == 204
    assert after.json() == []
