"""ICT track and track selection tests."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from forge.models import AuditLog
from tests.conftest import Programme, token_for


async def open_window(client: AsyncClient, programme: Programme, hours: int = 24):
    now = datetime.now(UTC)
    return await client.put(
        f"/api/v1/cohorts/{programme.cohort.id}/ict-track-selection/window",
        json={
            "opens_at": (now - timedelta(hours=1)).isoformat(),
            "closes_at": (now + timedelta(hours=hours)).isoformat(),
        },
        headers=token_for(programme.program_lead),
    )


async def test_set_tracks_with_lead_mentors(client: AsyncClient, programme: Programme):
    url = f"/api/v1/cohorts/{programme.cohort.id}/ict-tracks"
    lead = token_for(programme.program_lead)

    bad_lead = await client.put(
        url,
        json={
            "tracks": [{"name": "web", "lead_mentor_id": str(programme.peer_mentor.id)}]
        },
        headers=lead,
    )
    remove_selected = await client.put(
        url, json={"tracks": [{"name": "cloud"}]}, headers=lead
    )
    by_committee = await client.put(
        url, json={"tracks": [{"name": "web"}]}, headers=token_for(programme.committee)
    )
    updated = await client.put(
        url,
        json={
            "tracks": [
                {
                    "name": "web",
                    "description": "Software engineering",
                    "lead_mentor_id": str(programme.ict_mentor.id),
                },
                {"name": "data"},
                {"name": "cloud"},
            ]
        },
        headers=lead,
    )
    listed = await client.get(url, headers=token_for(programme.mentees[0]))

    assert bad_lead.status_code == 422
    assert remove_selected.status_code == 422
    assert by_committee.status_code == 403
    assert updated.status_code == 200, updated.text
    tracks = {t["name"]: t for t in listed.json()}
    assert set(tracks) == {"web", "data", "cloud"}
    assert tracks["web"]["lead_mentor"]["id"] == str(programme.ict_mentor.id)


async def test_track_selection_window(client: AsyncClient, programme: Programme):
    base = f"/api/v1/cohorts/{programme.cohort.id}/ict-track-selection"
    mentee = token_for(programme.mentees[2])

    closed = await client.put(f"{base}/me", json={"ict_track": "web"}, headers=mentee)
    await open_window(client, programme)
    unknown = await client.put(f"{base}/me", json={"ict_track": "ai"}, headers=mentee)
    chosen = await client.put(f"{base}/me", json={"ict_track": "web"}, headers=mentee)
    mine = (await client.get(base, headers=mentee)).json()

    assert closed.status_code == 422
    assert unknown.status_code == 422
    assert chosen.json()["ict_track"] == "web"
    assert mine == mine | {"ict_track": "web"}
    assert mine["window"]["is_open"] is True


async def test_summary_and_admin_override(
    client: AsyncClient, programme: Programme, db_session
):
    base = f"/api/v1/cohorts/{programme.cohort.id}/ict-track-selection"
    lead = token_for(programme.program_lead)
    newcomer = await client.post(
        f"/api/v1/cohorts/{programme.cohort.id}/enrollments",
        json={"user_id": str(programme.outsider.id)},
        headers=lead,
    )
    assert newcomer.status_code == 201

    before = (await client.get(f"{base}/summary", headers=lead)).json()
    overridden = await client.put(
        f"{base}/{programme.outsider.id}",
        json={"ict_track": "data", "reason": "Missed the window"},
        headers=lead,
    )
    after = (await client.get(f"{base}/summary", headers=lead)).json()
    as_mentee = await client.get(
        f"{base}/summary", headers=token_for(programme.mentees[0])
    )

    assert [u["id"] for u in before["not_selected"]] == [str(programme.outsider.id)]
    assert overridden.json()["ict_track"] == "data"
    assert after["not_selected"] == []
    assert {c["ict_track"]: c["mentees"] for c in after["counts"]} == {
        "data": 3,
        "web": 1,
    }
    assert as_mentee.status_code == 403
    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "override_ict_track")
    )
    assert audit.meta_data["reason"] == "Missed the window"
