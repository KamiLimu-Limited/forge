"""Leaderboard and competition tests."""

from datetime import UTC, date, datetime, timedelta

from httpx import AsyncClient

from forge.models import (
    ActivityStatus,
    ActivityType,
    AttendanceRecord,
    AttendanceStatus,
    ExtraActivity,
)
from tests.conftest import Factory, Programme, token_for

PAST = datetime.now(UTC) - timedelta(days=10)


async def seed(db_session, factory: Factory, programme: Programme):
    sessions = [
        await factory.session(programme.cohort, starts_at=PAST + timedelta(days=i))
        for i in range(2)
    ]
    m0, m1, m2 = programme.mentees
    for mentee, attended in ((m0, 2), (m1, 1), (m2, 1)):
        for s in sessions[:attended]:
            db_session.add(
                AttendanceRecord(
                    mentee_id=mentee.id,
                    session_id=s.id,
                    status=AttendanceStatus.ATTENDED,
                )
            )
    db_session.add(
        ExtraActivity(
            type=ActivityType.EVENT,
            mentee_id=m2.id,
            cohort_id=programme.cohort.id,
            title="Hackathon",
            date=date.today(),
            status=ActivityStatus.APPROVED,
            points_awarded=5,
            details={},
        )
    )
    await db_session.commit()


async def test_leaderboard_ranks_by_total_points(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed(db_session, factory, programme)

    board = (
        await client.get(
            f"/api/v1/cohorts/{programme.cohort.id}/leaderboard",
            headers=token_for(programme.mentees[1]),
        )
    ).json()

    assert [(e["rank"], e["total_points"]) for e in board["entries"]] == [
        (1, 20),
        (2, 15),
        (3, 10),
    ]
    assert board["entries"][2]["is_me"] is True
    assert board["entries"][1]["events"] == 1


async def test_dimension_ranking_shares_ties(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed(db_session, factory, programme)

    ranking = (
        await client.get(
            f"/api/v1/cohorts/{programme.cohort.id}/leaderboard/core_attendance",
            headers=token_for(programme.committee),
        )
    ).json()

    assert [(e["rank"], e["value"]) for e in ranking["entries"]] == [
        (1, 100.0),
        (2, 50.0),
        (2, 50.0),
    ]


async def test_anonymous_leaderboard(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed(db_session, factory, programme)
    url = f"/api/v1/cohorts/{programme.cohort.id}/leaderboard"

    toggled = await client.patch(
        f"{url}/settings",
        json={"leaderboard_anonymous": True},
        headers=token_for(programme.committee),
    )
    mentee_view = (
        await client.get(url, headers=token_for(programme.mentees[0]))
    ).json()
    staff_view = (await client.get(url, headers=token_for(programme.committee))).json()
    by_mentee = await client.patch(
        f"{url}/settings",
        json={"leaderboard_anonymous": False},
        headers=token_for(programme.mentees[0]),
    )

    assert toggled.json()["leaderboard_anonymous"] is True
    assert mentee_view["anonymous"] is True
    names = [e["display_name"] for e in mentee_view["entries"]]
    assert names.count("Anonymous mentee") == 2
    assert all(e["mentee_id"] for e in staff_view["entries"])
    assert by_mentee.status_code == 403


async def test_leaderboard_csv_export(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed(db_session, factory, programme)

    response = await client.get(
        f"/api/v1/cohorts/{programme.cohort.id}/leaderboard/export",
        headers=token_for(programme.committee),
    )

    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("rank,mentee,total_points,core_attendance")
    assert len(lines) == 4


async def test_outsider_cannot_see_leaderboard(
    client: AsyncClient, programme: Programme
):
    response = await client.get(
        f"/api/v1/cohorts/{programme.cohort.id}/leaderboard",
        headers=token_for(programme.outsider),
    )

    assert response.status_code == 403


async def test_competition_workflow(client: AsyncClient, programme: Programme):
    committee = token_for(programme.committee)
    m0, m1, m2 = programme.mentees

    competition = await client.post(
        "/api/v1/competitions",
        json={
            "cohort_id": str(programme.cohort.id),
            "name": "Innovation Challenge",
            "competition_type": "innovation",
            "start_date": str(date.today()),
            "end_date": str(date.today() + timedelta(days=30)),
        },
        headers=committee,
    )
    assert competition.status_code == 201, competition.text
    cid = competition.json()["id"]

    round1 = await client.post(
        f"/api/v1/competitions/{cid}/rounds",
        json={"round_number": 1, "round_name": "Pitch"},
        headers=committee,
    )
    duplicate_round = await client.post(
        f"/api/v1/competitions/{cid}/rounds",
        json={"round_number": 1, "round_name": "Again"},
        headers=committee,
    )
    entries = await client.post(
        f"/api/v1/competitions/{cid}/entries",
        json={
            "entries": [
                {"mentee_id": str(m0.id), "round_id": round1.json()["id"]},
                {"team_name": "Rocket", "team_member_ids": [str(m1.id), str(m2.id)]},
            ]
        },
        headers=committee,
    )
    outsider_entry = await client.post(
        f"/api/v1/competitions/{cid}/entries",
        json={"entries": [{"mentee_id": str(programme.outsider.id)}]},
        headers=committee,
    )
    assert round1.status_code == 201
    assert duplicate_round.status_code == 409
    assert entries.status_code == 201
    assert outsider_entry.status_code == 422

    team_entry = entries.json()[1]["id"]
    advanced = await client.patch(
        f"/api/v1/entries/{team_entry}",
        json={"status": "winner", "result": "1st place"},
        headers=committee,
    )
    assert advanced.json()["status"] == "winner"

    mine = await client.get(
        f"/api/v1/competitions/{cid}/entries", headers=token_for(m2)
    )
    group = await client.get(
        f"/api/v1/competitions/{cid}/entries", headers=token_for(programme.peer_mentor)
    )
    status = await client.get(
        f"/api/v1/mentees/{m0.id}/competition-status", headers=token_for(m0)
    )
    listing = await client.get("/api/v1/competitions", headers=token_for(m0))
    hidden = await client.get(
        f"/api/v1/competitions/{cid}", headers=token_for(programme.outsider)
    )

    assert len(mine.json()) == 1 and mine.json()[0]["team_name"] == "Rocket"
    assert len(group.json()) == 2
    assert status.json()[0]["round_name"] == "Pitch"
    assert listing.json()["total"] == 1
    assert hidden.status_code == 403


async def test_mentee_cannot_create_competition(
    client: AsyncClient, programme: Programme
):
    response = await client.post(
        "/api/v1/competitions",
        json={
            "cohort_id": str(programme.cohort.id),
            "name": "X",
            "competition_type": "scholarship",
            "start_date": str(date.today()),
            "end_date": str(date.today()),
        },
        headers=token_for(programme.mentees[0]),
    )

    assert response.status_code == 403
