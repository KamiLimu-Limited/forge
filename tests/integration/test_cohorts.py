"""Cohort and enrollment endpoint tests."""

from datetime import date

from httpx import AsyncClient

from forge.models import CohortStatus, UserRole
from tests.conftest import Factory, Programme, token_for

COHORT = {
    "name": "Cohort 11",
    "programme_type": "undergraduate",
    "start_date": "2026-01-10",
    "end_date": "2026-10-30",
}


async def test_admin_creates_cohort_with_defaults(client: AsyncClient, admin_user):
    response = await client.post(
        "/api/v1/cohorts", json=COHORT, headers=token_for(admin_user)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["graduation_threshold"] == 80
    assert (body["thursday_window_hours"], body["saturday_window_hours"]) == (24, 48)
    assert body["extra_log_window_days"] == 30
    for removed in ("skill_names", "leaderboard_anonymous", "ict_tracks_offered"):
        assert removed not in body


async def test_program_lead_creates_cohort_but_committee_cannot(
    client: AsyncClient, programme: Programme
):
    lead = await client.post(
        "/api/v1/cohorts", json=COHORT, headers=token_for(programme.program_lead)
    )
    committee = await client.post(
        "/api/v1/cohorts",
        json=COHORT | {"name": "Cohort 12"},
        headers=token_for(programme.committee),
    )

    assert lead.status_code == 201
    assert committee.status_code == 403


async def test_cohort_config_round_trip(client: AsyncClient, programme: Programme):
    url = f"/api/v1/cohorts/{programme.cohort.id}"
    lead = token_for(programme.program_lead)

    patched = await client.patch(
        url,
        json={
            "thursday_window_hours": 36,
            "objective_windows": {
                "start": {
                    "opens_at": "2026-01-01T00:00:00Z",
                    "closes_at": "2026-01-15T00:00:00Z",
                }
            },
            "track_selection_opens_at": "2026-02-01T00:00:00Z",
            "track_selection_closes_at": "2026-02-08T00:00:00Z",
        },
        headers=lead,
    )
    completed = await client.patch(url, json={"status": "completed"}, headers=lead)
    detail = (await client.get(url, headers=lead)).json()

    assert patched.status_code == 200, patched.text
    assert completed.status_code == 422
    assert detail["thursday_window_hours"] == 36
    assert set(detail["objective_windows"]) == {"start"}
    assert {t["name"] for t in detail["ict_tracks"]} == {"web", "data"}


async def test_rating_questions(client: AsyncClient, programme: Programme):
    url = f"/api/v1/cohorts/{programme.cohort.id}/rating-questions"

    defaults = (await client.get(url, headers=token_for(programme.mentees[0]))).json()
    eight = await client.put(
        url,
        json={"questions": ["q"] * 8},
        headers=token_for(programme.program_lead),
    )
    updated = await client.put(
        url,
        json={"questions": [f"Question {n}" for n in range(1, 10)]},
        headers=token_for(programme.program_lead),
    )

    assert [q["group"] for q in defaults] == ["reaction"] * 3 + ["learning"] * 3 + [
        "intended_behaviour"
    ] * 3
    assert eight.status_code == 422
    assert updated.json()[8] == {
        "number": 9,
        "group": "intended_behaviour",
        "text": "Question 9",
    }


async def test_duplicate_cohort_name_conflicts(client: AsyncClient, admin_user):
    await client.post("/api/v1/cohorts", json=COHORT, headers=token_for(admin_user))
    response = await client.post(
        "/api/v1/cohorts", json=COHORT, headers=token_for(admin_user)
    )

    assert response.status_code == 409
    assert response.json()["error"] == "conflict"


async def test_invalid_dates_rejected(client: AsyncClient, admin_user):
    response = await client.post(
        "/api/v1/cohorts",
        json=COHORT | {"end_date": "2025-01-01"},
        headers=token_for(admin_user),
    )

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


async def test_non_admin_cannot_create_cohort(client: AsyncClient, regular_user):
    response = await client.post(
        "/api/v1/cohorts", json=COHORT, headers=token_for(regular_user)
    )

    assert response.status_code == 403


async def test_drafts_hidden_from_mentees(
    client: AsyncClient, factory: Factory, regular_user, admin_user
):
    draft = await factory.cohort(status=CohortStatus.DRAFT)
    await factory.cohort()

    mentee_view = await client.get("/api/v1/cohorts", headers=token_for(regular_user))
    admin_view = await client.get("/api/v1/cohorts", headers=token_for(admin_user))
    hidden = await client.get(
        f"/api/v1/cohorts/{draft.id}", headers=token_for(regular_user)
    )

    assert mentee_view.json()["total"] == 1
    assert admin_view.json()["total"] == 2
    assert hidden.status_code == 404


async def test_update_and_no_delete(client: AsyncClient, factory: Factory, admin_user):
    cohort = await factory.cohort()
    headers = token_for(admin_user)

    patched = await client.patch(
        f"/api/v1/cohorts/{cohort.id}",
        json={"graduation_threshold": 75},
        headers=headers,
    )
    deleted = await client.delete(f"/api/v1/cohorts/{cohort.id}", headers=headers)
    still_there = await client.get(f"/api/v1/cohorts/{cohort.id}", headers=headers)

    assert patched.json()["graduation_threshold"] == 75
    assert deleted.status_code == 405
    assert still_there.status_code == 200


async def test_enroll_grants_cohort_scoped_role(
    client: AsyncClient, factory: Factory, admin_user
):
    cohort = await factory.cohort()
    user = await factory.user("new@test.com")

    response = await client.post(
        f"/api/v1/cohorts/{cohort.id}/enrollments",
        json={"user_id": str(user.id), "role": "committee"},
        headers=token_for(admin_user),
    )
    profile = await client.get("/api/v1/users/me", headers=token_for(user))
    detail = await client.get(
        f"/api/v1/cohorts/{cohort.id}", headers=token_for(admin_user)
    )

    assert response.status_code == 201
    assert response.json()["user"]["email"] == "new@test.com"
    assert {"role": "committee", "cohort_id": str(cohort.id)}.items() <= profile.json()[
        "roles"
    ][0].items()
    assert detail.json()["enrollment_counts"] == {"committee": 1}


async def test_enroll_needs_no_track_or_peer_mentor(
    client: AsyncClient, programme: Programme, factory: Factory
):
    user = await factory.user()
    url = f"/api/v1/cohorts/{programme.cohort.id}/enrollments"
    headers = token_for(programme.admin)

    with_track = await client.post(
        url, json={"user_id": str(user.id), "ict_track": "web"}, headers=headers
    )
    ok = await client.post(url, json={"user_id": str(user.id)}, headers=headers)
    duplicate = await client.post(url, json={"user_id": str(user.id)}, headers=headers)

    assert with_track.status_code == 422
    assert ok.status_code == 201
    assert (ok.json()["ict_track"], ok.json()["peer_mentor_id"]) == (None, None)
    assert duplicate.status_code == 409


async def test_peer_mentor_assigned_about_a_month_in(
    client: AsyncClient, programme: Programme, factory: Factory, db_session
):
    from sqlalchemy import select

    from forge.models import CohortEnrollment

    new = await factory.cohort(start_date=date.today())
    mentee = await factory.user()
    mentor = await factory.user()
    enrollment = await factory.enroll(mentee, new)
    await factory.enroll(mentor, new, UserRole.PEER_MENTOR_1_1)
    headers = token_for(programme.admin)

    too_early = await client.patch(
        f"/api/v1/cohorts/{new.id}/enrollments/{enrollment.id}",
        json={"peer_mentor_id": str(mentor.id)},
        headers=headers,
    )
    group_mentee = await db_session.scalar(
        select(CohortEnrollment.id).where(
            CohortEnrollment.user_id == programme.mentees[2].id
        )
    )
    not_a_mentor = await client.patch(
        f"/api/v1/cohorts/{programme.cohort.id}/enrollments/{group_mentee}",
        json={"peer_mentor_id": str(programme.mentees[0].id)},
        headers=headers,
    )
    track_change = await client.patch(
        f"/api/v1/cohorts/{programme.cohort.id}/enrollments/{group_mentee}",
        json={"peer_mentor_id": None, "ict_track": "web"},
        headers=headers,
    )

    assert too_early.status_code == 422
    assert "can be assigned from" in too_early.json()["detail"]
    assert not_a_mentor.status_code == 422
    assert track_change.status_code == 422


async def test_bulk_enroll_reports_per_user(
    client: AsyncClient, programme: Programme, factory: Factory
):
    user = await factory.user()
    response = await client.post(
        f"/api/v1/cohorts/{programme.cohort.id}/enrollments/bulk",
        json={
            "enrollments": [
                {"user_id": str(user.id)},
                {"user_id": str(programme.mentees[0].id)},
            ]
        },
        headers=token_for(programme.admin),
    )

    assert response.status_code == 201
    assert [r["success"] for r in response.json()] == [True, False]


async def test_enrollment_listing_is_scoped(client: AsyncClient, programme: Programme):
    url = f"/api/v1/cohorts/{programme.cohort.id}/enrollments"

    committee = await client.get(url, headers=token_for(programme.committee))
    mentor = await client.get(url, headers=token_for(programme.peer_mentor))
    mentee = await client.get(url, headers=token_for(programme.mentees[2]))
    outsider = await client.get(url, headers=token_for(programme.outsider))

    assert committee.json()["total"] == 6
    assert mentor.status_code == 200
    assert mentor.json()["total"] == 3  # self + two group mentees
    assert mentee.json()["total"] == 1
    assert outsider.json()["total"] == 0


async def test_update_and_remove_enrollment(
    client: AsyncClient, programme: Programme, db_session
):
    from sqlalchemy import select

    from forge.models import CohortEnrollment

    mentee = programme.mentees[2]
    enrollment_id = await db_session.scalar(
        select(CohortEnrollment.id).where(CohortEnrollment.user_id == mentee.id)
    )
    url = f"/api/v1/cohorts/{programme.cohort.id}/enrollments/{enrollment_id}"
    headers = token_for(programme.admin)

    updated = await client.patch(
        url, json={"peer_mentor_id": str(programme.peer_mentor.id)}, headers=headers
    )
    removed = await client.delete(url, headers=headers)
    profile = await client.get("/api/v1/users/me", headers=token_for(mentee))

    assert updated.json()["peer_mentor_id"] == str(programme.peer_mentor.id)
    assert removed.status_code == 204
    assert all(
        r["role"] != UserRole.MENTEE or r["cohort_id"] is None
        for r in profile.json()["roles"]
    )
