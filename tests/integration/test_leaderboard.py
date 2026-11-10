"""Leaderboard tests."""

from datetime import UTC, date, datetime, timedelta

from httpx import AsyncClient

from forge.models import (
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
    attendees = (
        (m0, 2),
        (m1, 1),
        (m2, 1),
        (programme.peer_mentor, 2),
        (programme.ict_mentor, 1),
    )
    for user, attended in attendees:
        for s in sessions[:attended]:
            db_session.add(
                AttendanceRecord(
                    mentee_id=user.id, session_id=s.id, status=AttendanceStatus.PRESENT
                )
            )
    for activity_type, user in (
        (ActivityType.EVENT, m2),
        (ActivityType.OPPORTUNITY, m2),
        (ActivityType.SCHOLARSHIP, m2),
        (ActivityType.ACADEMIC, programme.ict_mentor),
    ):
        db_session.add(
            ExtraActivity(
                type=activity_type,
                mentee_id=user.id,
                cohort_id=programme.cohort.id,
                title="Logged",
                date=date.today(),
                points_awarded=2,
                details={},
            )
        )
    await db_session.commit()


async def test_leaderboard_ranks_by_total_points_with_names(
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
        (2, 16),
        (3, 10),
    ]
    assert board["entries"][2]["is_me"] is True
    assert all(e["display_name"] != "Anonymous mentee" for e in board["entries"])
    assert "anonymous" not in board
    entry = board["entries"][1]
    assert (entry["events"], entry["applications"]) == (1, 2)
    assert "graduation_rate" not in entry


async def test_dimension_ranking_shares_ties(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed(db_session, factory, programme)
    base = f"/api/v1/cohorts/{programme.cohort.id}/leaderboard"

    ranking = (
        await client.get(
            f"{base}/core_attendance", headers=token_for(programme.committee)
        )
    ).json()
    removed = await client.get(
        f"{base}/graduation_rate", headers=token_for(programme.committee)
    )

    assert [(e["rank"], e["value"]) for e in ranking["entries"]] == [
        (1, 100.0),
        (2, 50.0),
        (2, 50.0),
    ]
    assert removed.status_code == 422


async def test_peer_mentor_leaderboard(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed(db_session, factory, programme)
    url = f"/api/v1/cohorts/{programme.cohort.id}/leaderboard/peer-mentors"

    by_rate = (await client.get(url, headers=token_for(programme.peer_mentor))).json()
    by_extra = (
        await client.get(
            url,
            params={"ranked_by": "extra_sessions"},
            headers=token_for(programme.committee),
        )
    ).json()
    mentee = await client.get(url, headers=token_for(programme.mentees[0]))

    assert [e["display_name"] for e in by_rate["entries"]] == ["Peer User", "Ict User"]
    first = by_rate["entries"][0]
    assert (first["sessions_attended"], first["core_rate"], first["is_me"]) == (
        2,
        100.0,
        True,
    )
    assert by_extra["entries"][0]["display_name"] == "Ict User"
    assert by_extra["entries"][0]["extra_sessions"] == 1
    assert mentee.status_code == 403


async def test_leaderboard_snapshots(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed(db_session, factory, programme)
    url = f"/api/v1/cohorts/{programme.cohort.id}/leaderboard/snapshots"

    by_committee = await client.post(url, headers=token_for(programme.committee))
    taken = await client.post(url, headers=token_for(programme.program_lead))
    listed = await client.get(
        url, params={"kind": "mentee"}, headers=token_for(programme.committee)
    )
    by_mentee = await client.get(url, headers=token_for(programme.mentees[0]))

    assert by_committee.status_code == 403
    assert {s["kind"] for s in taken.json()} == {"mentee", "peer_mentor"}
    assert len(listed.json()) == 1
    assert listed.json()[0]["rows"][0]["total_points"] == 20
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
    assert lines[0] == (
        "rank,mentee,total_points,core_attendance,academic,events,applications,"
        "consultations"
    )
    assert len(lines) == 4


async def test_outsider_cannot_see_leaderboard(
    client: AsyncClient, programme: Programme
):
    response = await client.get(
        f"/api/v1/cohorts/{programme.cohort.id}/leaderboard",
        headers=token_for(programme.outsider),
    )

    assert response.status_code == 403
