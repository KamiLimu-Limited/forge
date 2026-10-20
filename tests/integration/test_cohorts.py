"""Cohort and enrollment endpoint tests."""

from httpx import AsyncClient

from forge.models import CohortStatus, UserRole
from tests.conftest import Factory, Programme, token_for

COHORT = {
    "name": "Cohort 11",
    "programme_type": "undergraduate",
    "start_date": "2026-01-10",
    "end_date": "2026-10-30",
    "ict_tracks_offered": ["web", "data"],
}


async def test_admin_creates_cohort_with_defaults(client: AsyncClient, admin_user):
    response = await client.post(
        "/api/v1/cohorts", json=COHORT, headers=token_for(admin_user)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["graduation_threshold"] == 80
    assert len(body["skill_names"]) == 6


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


async def test_update_and_soft_delete(
    client: AsyncClient, factory: Factory, admin_user
):
    cohort = await factory.cohort()
    headers = token_for(admin_user)

    patched = await client.patch(
        f"/api/v1/cohorts/{cohort.id}",
        json={"graduation_threshold": 75},
        headers=headers,
    )
    deleted = await client.delete(f"/api/v1/cohorts/{cohort.id}", headers=headers)
    missing = await client.get(f"/api/v1/cohorts/{cohort.id}", headers=headers)

    assert patched.json()["graduation_threshold"] == 75
    assert deleted.status_code == 204
    assert missing.status_code == 404


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


async def test_enroll_validates_track_and_peer_mentor(
    client: AsyncClient, programme: Programme, factory: Factory
):
    user = await factory.user()
    url = f"/api/v1/cohorts/{programme.cohort.id}/enrollments"
    headers = token_for(programme.admin)

    bad_track = await client.post(
        url, json={"user_id": str(user.id), "ict_track": "ai"}, headers=headers
    )
    bad_mentor = await client.post(
        url,
        json={"user_id": str(user.id), "peer_mentor_id": str(programme.mentees[0].id)},
        headers=headers,
    )
    ok = await client.post(
        url,
        json={
            "user_id": str(user.id),
            "peer_mentor_id": str(programme.peer_mentor.id),
            "ict_track": "web",
        },
        headers=headers,
    )
    duplicate = await client.post(url, json={"user_id": str(user.id)}, headers=headers)

    assert bad_track.status_code == 422
    assert bad_mentor.status_code == 422
    assert ok.status_code == 201
    assert duplicate.status_code == 409


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
