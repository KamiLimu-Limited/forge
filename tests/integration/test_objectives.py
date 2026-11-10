"""Objective tests."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from tests.conftest import Programme, token_for


async def set_windows(programme: Programme, db_session, *, start_open: bool):
    now = datetime.now(UTC)
    offset = timedelta(days=-1) if start_open else timedelta(days=5)
    programme.cohort.objective_windows = {
        "start": {
            "opens_at": (now + offset).isoformat(),
            "closes_at": (now + offset + timedelta(days=3)).isoformat(),
        }
    }
    await db_session.commit()


async def test_objective_lifecycle(
    client: AsyncClient, programme: Programme, db_session
):
    await set_windows(programme, db_session, start_open=True)
    mentee = token_for(programme.mentees[0])

    created = await client.post(
        "/api/v1/objectives",
        json={"type": "human", "text": "Speak up in group sessions"},
        headers=mentee,
    )
    objective = created.json()
    url = f"/api/v1/objectives/{objective['id']}"
    edited = await client.patch(url, json={"type": "technical"}, headers=mentee)
    by_other = await client.patch(
        url, json={"text": "x"}, headers=token_for(programme.mentees[1])
    )
    rated = await client.post(
        f"{url}/ratings", json={"rating_point": "start", "score": 2}, headers=mentee
    )
    rerated = await client.post(
        f"{url}/ratings", json={"rating_point": "start", "score": 3}, headers=mentee
    )
    mid_closed = await client.post(
        f"{url}/ratings", json={"rating_point": "mid", "score": 4}, headers=mentee
    )
    mine = (await client.get("/api/v1/objectives/me", headers=mentee)).json()
    windows = (await client.get("/api/v1/objectives/windows", headers=mentee)).json()

    assert created.status_code == 201
    assert edited.json()["type"] == "technical"
    assert by_other.status_code == 403
    assert rated.json()["ratings"] == [rated.json()["ratings"][0]]
    assert rerated.json()["ratings"][0]["score"] == 3
    assert mid_closed.status_code == 422
    assert len(mine) == 1
    assert {w["rating_point"]: w["is_open"] for w in windows["windows"]} == {
        "start": True,
        "mid": False,
        "end": False,
    }


async def test_peer_mentor_reads_group_objectives(
    client: AsyncClient, programme: Programme
):
    m0, m2 = programme.mentees[0], programme.mentees[2]
    await client.post(
        "/api/v1/objectives",
        json={"type": "technical", "text": "Deploy to the cloud"},
        headers=token_for(m0),
    )
    peer = await client.post(
        "/api/v1/objectives",
        json={"type": "human", "text": "Mentor with patience"},
        headers=token_for(programme.peer_mentor),
    )

    group = await client.get(
        f"/api/v1/mentees/{m0.id}/objectives", headers=token_for(programme.peer_mentor)
    )
    staff = await client.get(
        f"/api/v1/mentees/{m0.id}/objectives", headers=token_for(programme.committee)
    )
    ict = await client.get(
        f"/api/v1/mentees/{m0.id}/objectives", headers=token_for(programme.ict_mentor)
    )
    other = await client.get(
        f"/api/v1/mentees/{m0.id}/objectives", headers=token_for(m2)
    )

    assert peer.status_code == 201
    assert [o["text"] for o in group.json()] == ["Deploy to the cloud"]
    assert staff.status_code == 200
    assert ict.status_code == 403
    assert other.status_code == 403
