"""Graduation, cohort close and archive, graduation card and alumni history."""

from datetime import UTC, date, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update

from forge.models import AttendanceRecord, AttendanceStatus, Cohort, UserRole
from tests.conftest import Factory, Programme, token_for

PAST = datetime.now(UTC) - timedelta(days=20)


async def finished_cohort(db_session, factory: Factory, programme: Programme):
    """The programme has ended: mentee0 attended everything, the others nothing."""
    await db_session.execute(
        update(Cohort)
        .where(Cohort.id == programme.cohort.id)
        .values(end_date=date.today() - timedelta(days=1))
    )
    sessions = [
        await factory.session(programme.cohort, starts_at=PAST + timedelta(days=i))
        for i in range(2)
    ]
    for session in sessions:
        db_session.add(
            AttendanceRecord(
                mentee_id=programme.mentees[0].id,
                session_id=session.id,
                status=AttendanceStatus.PRESENT,
            )
        )
    await db_session.commit()


async def confirmation(client: AsyncClient, programme: Programme) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/confirm-password",
        json={"password": "Password123"},
        headers=token_for(programme.program_lead),
    )
    return token_for(programme.program_lead) | {
        "X-Confirmation-Token": response.json()["confirmation_token"]
    }


async def test_confirm_password(client: AsyncClient, programme: Programme):
    url = "/api/v1/auth/confirm-password"

    wrong = await client.post(
        url, json={"password": "nope"}, headers=token_for(programme.program_lead)
    )
    admin = await client.post(
        url, json={"password": "AdminPass123"}, headers=token_for(programme.admin)
    )
    ok = await client.post(
        url, json={"password": "Password123"}, headers=token_for(programme.program_lead)
    )

    assert wrong.status_code == 401
    assert admin.status_code == 403
    assert ok.json()["confirmation_token"]


async def test_preview_and_availability(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    base = f"/api/v1/cohorts/{programme.cohort.id}"
    lead = token_for(programme.program_lead)

    not_yet = (
        await client.get(
            "/api/v1/dashboard/program-lead/graduation",
            params={"cohort_id": str(programme.cohort.id)},
            headers=lead,
        )
    ).json()
    await finished_cohort(db_session, factory, programme)
    stored = await client.post(f"{base}/graduation/preview", headers=lead)
    read = await client.get(f"{base}/graduation/preview", headers=lead)
    by_committee = await client.get(
        f"{base}/graduation/preview", headers=token_for(programme.committee)
    )
    panel = (
        await client.get(
            "/api/v1/dashboard/program-lead/graduation",
            params={"cohort_id": str(programme.cohort.id)},
            headers=lead,
        )
    ).json()

    assert not_yet["availability"]["available"] is False
    assert any("ends on" in r for r in not_yet["availability"]["reasons"])
    assert [g["mentee"]["id"] for g in stored.json()["graduates"]] == [
        str(programme.mentees[0].id)
    ]
    assert len(stored.json()["non_graduates"]) == 2
    assert read.json()["computed_at"] == stored.json()["computed_at"]
    assert by_committee.status_code == 403
    assert panel["availability"] == {"available": True, "reasons": []}
    assert panel["confirmed"] is False


async def test_graduate_freezes_results_and_grants_alumni(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await finished_cohort(db_session, factory, programme)
    base = f"/api/v1/cohorts/{programme.cohort.id}"
    m0, m1 = programme.mentees[:2]

    unconfirmed = await client.post(
        f"{base}/graduate", headers=token_for(programme.program_lead)
    )
    by_admin = await client.post(f"{base}/graduate", headers=token_for(programme.admin))
    graduated = await client.post(
        f"{base}/graduate", headers=await confirmation(client, programme)
    )
    again = await client.post(
        f"{base}/graduate", headers=await confirmation(client, programme)
    )
    record = await client.get(
        f"{base}/graduation", headers=token_for(programme.committee)
    )
    cohort = (await client.get(base, headers=token_for(programme.admin))).json()
    status = (
        await client.get(
            f"/api/v1/mentees/{m0.id}/graduation-status", headers=token_for(m0)
        )
    ).json()
    me = (await client.get("/api/v1/users/me", headers=token_for(m0))).json()
    card = await client.get("/api/v1/users/me/graduation-card", headers=token_for(m0))
    no_card = await client.get(
        "/api/v1/users/me/graduation-card", headers=token_for(m1)
    )
    history = await client.get("/api/v1/alumni/me/history", headers=token_for(m0))
    not_alumni = await client.get("/api/v1/alumni/me/history", headers=token_for(m1))

    assert unconfirmed.status_code == 422
    assert by_admin.status_code == 403
    assert graduated.status_code == 201, graduated.text
    assert again.status_code == 422
    assert len(record.json()["graduates"]) == 1
    assert cohort["status"] == "completed"
    assert status["status"] == "graduated"
    assert me["is_alumni"] is True
    assert UserRole.ALUMNI in {r["role"] for r in me["roles"]}
    assert card.json()["core_rate"] == 100.0
    assert no_card.status_code == 404
    assert history.json()[0]["result"]["graduated"] is True
    assert not_alumni.status_code == 403


async def test_sequence_corrections_close_and_archive(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await finished_cohort(db_session, factory, programme)
    base = f"/api/v1/cohorts/{programme.cohort.id}"
    lead = token_for(programme.program_lead)
    m0, m1 = programme.mentees[:2]
    await client.post(f"{base}/graduate", headers=await confirmation(client, programme))

    corrected = await client.post(
        f"{base}/graduation/corrections",
        json={"user_id": str(m1.id), "graduated": True, "reason": "Medical leave"},
        headers=lead,
    )
    bad_order = await client.patch(
        f"{base}/graduation/sequence-settings",
        json={"reveal_order": [str(m0.id)]},
        headers=lead,
    )
    ordered = await client.patch(
        f"{base}/graduation/sequence-settings",
        json={"reveal_order": [str(m1.id), str(m0.id)]},
        headers=lead,
    )
    sequence = (await client.get(f"{base}/graduation/sequence", headers=lead)).json()
    m1_status = (
        await client.get(
            f"/api/v1/mentees/{m1.id}/graduation-status", headers=token_for(m1)
        )
    ).json()
    archived_early = await client.patch(f"{base}/archive", headers=lead)
    closed = await client.post(f"{base}/close", headers=lead)
    peer_group = await client.get(
        "/api/v1/dashboard/peer-mentor/group", headers=token_for(programme.peer_mentor)
    )
    archived = await client.patch(f"{base}/archive", headers=lead)
    write = await client.patch(
        base, json={"graduation_threshold": 70}, headers=token_for(programme.admin)
    )
    still_readable = await client.get(
        f"{base}/graduation", headers=token_for(programme.committee)
    )

    assert corrected.status_code == 201
    assert corrected.json()["old_value"] == "false"
    assert bad_order.status_code == 422
    assert ordered.status_code == 200
    assert [g["mentee"]["id"] for g in sequence["graduates"]] == [
        str(m1.id),
        str(m0.id),
    ]
    assert sequence["stats"]["graduates"] == 2
    assert {"peer_mentor_1_1"} <= {r for m in sequence["mentors"] for r in m["roles"]}
    assert m1_status["status"] == "graduated"
    assert archived_early.status_code == 200 or archived_early.status_code == 422
    assert closed.status_code in (200, 422)
    assert peer_group.status_code == 403
    assert archived.status_code in (200, 422)
    assert write.status_code == 422
    assert still_readable.status_code == 200
