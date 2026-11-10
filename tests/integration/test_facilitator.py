"""Facilitator rating tests."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from forge.models import (
    AttendanceRecord,
    AttendanceStatus,
    MentorRole,
    SessionCategory,
    SessionMentor,
    SessionStatus,
)
from tests.conftest import Factory, Programme, token_for

PAST = datetime.now(UTC) - timedelta(days=10)


async def seed(db_session, factory: Factory, programme: Programme):
    """A peer mentorship task both peer mentors facilitate, and a Thursday session
    the 1:1 peer mentor leads."""
    task = await factory.session(
        programme.cohort,
        title="Task 1",
        category=SessionCategory.PEER_MENTORSHIP,
        starts_at=PAST,
        ends_at=PAST + timedelta(days=5),
        status=SessionStatus.COMPLETED,
    )
    thursday = await factory.session(
        programme.cohort, title="Storytelling", starts_at=PAST + timedelta(days=1)
    )
    for session, mentor in (
        (task, programme.peer_mentor),
        (task, programme.ict_mentor),
        (thursday, programme.peer_mentor),
    ):
        db_session.add(
            SessionMentor(
                session_id=session.id, user_id=mentor.id, mentor_role=MentorRole.LEAD
            )
        )
    m0, m1, m2 = programme.mentees
    for mentee, session, score, feedback in (
        (m0, task, 5, "Very helpful"),
        (m1, task, 3, "OK"),
        (m2, task, 1, "Not my group"),
        (m2, thursday, 4, "Good story"),
    ):
        db_session.add(
            AttendanceRecord(
                mentee_id=mentee.id,
                session_id=session.id,
                status=AttendanceStatus.PRESENT,
                ratings=[score] * 9,
                feedback=feedback,
            )
        )
    await db_session.commit()
    return task, thursday


async def test_peer_mentor_rated_by_own_group_on_tasks(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    task, thursday = await seed(db_session, factory, programme)
    headers = token_for(programme.peer_mentor)

    sessions = (
        await client.get("/api/v1/facilitator/me/sessions", headers=headers)
    ).json()
    summary = (
        await client.get("/api/v1/facilitator/me/summary", headers=headers)
    ).json()
    ratings = (
        await client.get(
            f"/api/v1/facilitator/me/sessions/{task.id}/ratings", headers=headers
        )
    ).json()
    over_time = (
        await client.get("/api/v1/facilitator/me/ratings-over-time", headers=headers)
    ).json()
    not_mine = await client.get(
        f"/api/v1/facilitator/me/sessions/{thursday.id}/ratings",
        headers=token_for(programme.ict_mentor),
    )

    averages = {s["session"]["title"]: s["average"] for s in sessions}
    assert averages == {"Task 1": 4.0, "Storytelling": 4.0}
    assert summary["sessions_completed"] == 1
    assert summary["average"] == 4.0
    assert ratings["responses"] == 2
    assert {f["feedback"] for f in ratings["feedback"]} == {"Very helpful", "OK"}
    assert [p["title"] for p in over_time] == ["Task 1", "Storytelling"]
    assert not_mine.status_code == 404


async def test_peer_mentor_average_and_group_feedback(
    client: AsyncClient, db_session, factory: Factory, programme: Programme
):
    await seed(db_session, factory, programme)

    average = (
        await client.get(
            "/api/v1/facilitator/peer-mentor-average",
            headers=token_for(programme.peer_mentor),
        )
    ).json()
    feedback = (
        await client.get(
            "/api/v1/peer-mentor/me/peer-mentorship-feedback",
            headers=token_for(programme.peer_mentor),
        )
    ).json()
    ict = await client.get(
        "/api/v1/peer-mentor/me/peer-mentorship-feedback",
        headers=token_for(programme.ict_mentor),
    )
    mentee = await client.get(
        "/api/v1/facilitator/me/summary", headers=token_for(programme.mentees[0])
    )

    # The ICT mentor has no 1:1 group, so no task ratings count for them.
    assert (average["peer_mentors"], average["average"]) == (1, 4.0)
    assert [f["session"]["title"] for f in feedback] == ["Task 1"]
    assert feedback[0]["responses"] == 2
    assert all(
        e["respondent"].startswith("Participant-") for e in feedback[0]["feedback"]
    )
    assert ict.status_code == 403
    assert mentee.status_code == 403
