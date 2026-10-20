"""Peer mentorship notes, tasks and skill-rating tests."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, text

from forge.models import (
    Cohort,
    Notification,
    NotificationType,
    PeerMentorNote,
    PeerMentorTask,
)
from forge.services.mentorship import send_task_deadline_reminders
from tests.conftest import Programme, token_for

NOW = datetime.now(UTC)


async def test_private_notes_are_encrypted_and_scoped(
    client: AsyncClient, programme: Programme, db_session
):
    m0, m2 = programme.mentees[0], programme.mentees[2]
    mentor = token_for(programme.peer_mentor)

    created = await client.post(
        "/api/v1/peer-mentor/notes",
        json={"mentee_id": str(m0.id), "note_text": "Struggling with exams"},
        headers=mentor,
    )
    outside_group = await client.post(
        "/api/v1/peer-mentor/notes",
        json={"mentee_id": str(m2.id), "note_text": "x"},
        headers=mentor,
    )
    listed = await client.get(f"/api/v1/peer-mentor/notes/{m0.id}", headers=mentor)
    as_mentee = await client.get(
        f"/api/v1/peer-mentor/notes/{m0.id}", headers=token_for(m0)
    )

    assert created.status_code == 201
    assert outside_group.status_code == 403
    assert [n["note_text"] for n in listed.json()] == ["Struggling with exams"]
    assert as_mentee.status_code == 403

    raw = await db_session.scalar(
        text("SELECT note_text FROM peer_mentor_notes WHERE id = :id"),
        {"id": created.json()["id"]},
    )
    assert raw != "Struggling with exams" and raw.startswith("gAAAA")
    assert (
        await db_session.scalar(select(PeerMentorNote.note_text))
    ) == "Struggling with exams"


async def test_ict_progress_notes_require_shared_track(
    client: AsyncClient, programme: Programme
):
    headers = token_for(programme.ict_mentor)
    on_track, off_track = programme.mentees[0], programme.mentees[1]

    ok = await client.post(
        "/api/v1/ict-peer-mentor/progress-notes",
        json={"mentee_id": str(on_track.id), "progress_note": "Built a REST API"},
        headers=headers,
    )
    denied = await client.post(
        "/api/v1/ict-peer-mentor/progress-notes",
        json={"mentee_id": str(off_track.id), "progress_note": "x"},
        headers=headers,
    )
    listed = await client.get(
        f"/api/v1/ict-peer-mentor/progress-notes/{on_track.id}", headers=headers
    )

    assert ok.status_code == 201
    assert denied.status_code == 403
    assert len(listed.json()) == 1


async def test_task_lifecycle(client: AsyncClient, programme: Programme, db_session):
    mentor = token_for(programme.peer_mentor)
    m0, m1, m2 = programme.mentees

    created = await client.post(
        "/api/v1/peer-mentor-tasks",
        json={
            "title": "Write a CV",
            "launch_date": (NOW - timedelta(hours=1)).isoformat(),
            "deadline_date": (NOW + timedelta(days=3)).isoformat(),
            "resource_link": "https://example.com/cv-template",
        },
        headers=mentor,
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    launched = list(
        await db_session.scalars(
            select(Notification.user_id).where(
                Notification.notification_type == NotificationType.TASK_LAUNCHED
            )
        )
    )
    assert set(launched) == {m0.id, m1.id}

    mentee_tasks = await client.get("/api/v1/peer-mentor-tasks", headers=token_for(m0))
    outsider_tasks = await client.get(
        "/api/v1/peer-mentor-tasks", headers=token_for(m2)
    )
    submitted = await client.post(
        f"/api/v1/peer-mentor-tasks/{task_id}/submit",
        json={"notes": "Done"},
        headers=token_for(m0),
    )
    not_mine = await client.post(
        f"/api/v1/peer-mentor-tasks/{task_id}/submit", headers=token_for(m2)
    )
    status = await client.get(
        f"/api/v1/peer-mentor-tasks/{task_id}/submissions", headers=mentor
    )

    assert mentee_tasks.json()["total"] == 1
    assert outsider_tasks.json()["total"] == 0
    assert submitted.json()["submission_status"] == "completed"
    assert not_mine.status_code == 404
    assert sorted(s["submission_status"] for s in status.json()) == [
        "completed",
        "pending",
    ]


async def test_future_tasks_hidden_until_launch_then_announced(
    client: AsyncClient, programme: Programme, db_session
):
    created = await client.post(
        "/api/v1/peer-mentor-tasks",
        json={
            "title": "Future task",
            "launch_date": (NOW + timedelta(days=1)).isoformat(),
            "deadline_date": (NOW + timedelta(days=5)).isoformat(),
        },
        headers=token_for(programme.peer_mentor),
    )
    task_id = created.json()["id"]
    hidden = await client.get(
        f"/api/v1/peer-mentor-tasks/{task_id}", headers=token_for(programme.mentees[0])
    )
    assert hidden.status_code == 404

    task = await db_session.get(PeerMentorTask, task_id)
    task.launch_date = NOW - timedelta(minutes=1)
    task.deadline_date = NOW + timedelta(hours=2)
    await db_session.commit()

    sent = await send_task_deadline_reminders(db_session)
    again = await send_task_deadline_reminders(db_session)
    kinds = list(
        await db_session.scalars(
            select(Notification.notification_type).where(
                Notification.related_resource_id == task.id
            )
        )
    )
    assert sent == 2 and again == 0
    assert kinds.count(NotificationType.TASK_LAUNCHED) == 2
    assert kinds.count(NotificationType.TASK_DEADLINE_REMINDER) == 2


async def test_task_dates_validated(client: AsyncClient, programme: Programme):
    response = await client.post(
        "/api/v1/peer-mentor-tasks",
        json={
            "title": "Bad",
            "launch_date": NOW.isoformat(),
            "deadline_date": (NOW - timedelta(days=1)).isoformat(),
        },
        headers=token_for(programme.peer_mentor),
    )

    assert response.status_code == 422


async def open_window(db_session, programme: Programme, point: str = "early"):
    cohort = await db_session.get(Cohort, programme.cohort.id)
    cohort.skill_rating_windows = {
        point: {
            "opens_at": (NOW - timedelta(days=1)).isoformat(),
            "closes_at": (NOW + timedelta(days=1)).isoformat(),
        }
    }
    await db_session.commit()


RATINGS = {"communication": 2, "leadership": 3, "technical": 4}


async def test_skill_ratings_respect_windows_and_skills(
    client: AsyncClient, programme: Programme, db_session
):
    mentee = token_for(programme.mentees[0])

    closed = await client.post(
        "/api/v1/skill-ratings",
        json={"rating_point": "early", "ratings": RATINGS},
        headers=mentee,
    )
    await open_window(db_session, programme)
    missing_skill = await client.post(
        "/api/v1/skill-ratings",
        json={"rating_point": "early", "ratings": {"communication": 2}},
        headers=mentee,
    )
    out_of_range = await client.post(
        "/api/v1/skill-ratings",
        json={"rating_point": "early", "ratings": RATINGS | {"technical": 9}},
        headers=mentee,
    )
    created = await client.post(
        "/api/v1/skill-ratings",
        json={"rating_point": "early", "ratings": RATINGS},
        headers=mentee,
    )
    replaced = await client.post(
        "/api/v1/skill-ratings",
        json={"rating_point": "early", "ratings": RATINGS | {"leadership": 4}},
        headers=mentee,
    )
    windows = await client.get("/api/v1/skill-ratings/windows", headers=mentee)

    assert closed.status_code == 422
    assert missing_skill.status_code == 422
    assert out_of_range.status_code == 422
    assert created.status_code == 201
    assert replaced.status_code == 200 and replaced.json()["ratings"]["leadership"] == 4
    early = next(w for w in windows.json() if w["rating_point"] == "early")
    assert early["is_open"] and early["submitted"]


async def test_skill_progress_shows_change(
    client: AsyncClient, programme: Programme, db_session
):
    mentee = programme.mentees[0]
    for point, ratings in (
        ("early", RATINGS),
        ("late", {"communication": 4, "leadership": 3, "technical": 5}),
    ):
        await open_window(db_session, programme, point)
        await client.post(
            "/api/v1/skill-ratings",
            json={"rating_point": point, "ratings": ratings},
            headers=token_for(mentee),
        )

    progress = await client.get(
        f"/api/v1/mentees/{mentee.id}/skill-progress",
        headers=token_for(programme.peer_mentor),
    )

    body = progress.json()
    assert [r["rating_point"] for r in body["ratings"]] == ["early", "late"]
    assert body["change"] == {"communication": 2, "leadership": 0, "technical": 1}
