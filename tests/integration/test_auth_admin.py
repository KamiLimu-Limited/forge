"""Auth gap-fill, admin management, audit and security tests."""

import uuid

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from forge.core.config import settings
from forge.core.rate_limit import auth_rate_limiter
from forge.models import CohortEnrollment, Invitation, User
from tests.conftest import Factory, auth_header, token_for

CSV = (
    "email,first_name,last_name,roles\n"
    "a@test.com,Ann,One,mentee\n"
    "b@test.com,Ben,Two,peer_mentor_1:1;alumni\n"
    "not-an-email,Bad,Row,mentee\n"
    "c@test.com,Cat,Three,wizard\n"
)


async def test_bulk_invite_csv(client: AsyncClient, admin_user, factory: Factory):
    cohort = await factory.cohort()

    response = await client.post(
        "/api/v1/auth/bulk-invite/csv",
        files={"file": ("users.csv", CSV, "text/csv")},
        data={"cohort_id": str(cohort.id)},
        headers=token_for(admin_user),
    )

    body = response.json()
    assert response.status_code == 201
    assert (body["total"], body["successful"], body["failed"]) == (4, 2, 2)
    assert {r["email"] for r in body["results"] if r["success"]} == {
        "a@test.com",
        "b@test.com",
    }


async def test_bulk_invite_csv_rejects_bad_header(client: AsyncClient, admin_user):
    response = await client.post(
        "/api/v1/auth/bulk-invite/csv",
        files={"file": ("users.csv", "name,email\nx,y\n", "text/csv")},
        headers=token_for(admin_user),
    )

    assert response.status_code == 400


async def test_bulk_invite_json_reports_duplicates(
    client: AsyncClient, admin_user, regular_user
):
    users = [
        {
            "email": "fresh@test.com",
            "first_name": "F",
            "last_name": "R",
            "roles": ["mentee"],
        },
        {
            "email": "user@test.com",
            "first_name": "U",
            "last_name": "S",
            "roles": ["mentee"],
        },
    ]

    response = await client.post(
        "/api/v1/auth/bulk-invite", json={"users": users}, headers=token_for(admin_user)
    )

    assert [r["success"] for r in response.json()["results"]] == [True, False]


async def test_invite_activate_into_cohort(
    client: AsyncClient, admin_user, factory: Factory, db_session
):
    cohort = await factory.cohort()
    invite = await client.post(
        "/api/v1/auth/invite",
        json={
            "email": "Joiner@Test.com",
            "first_name": "Jo",
            "last_name": "Iner",
            "roles": ["mentee"],
            "cohort_id": str(cohort.id),
        },
        headers=token_for(admin_user),
    )
    token = await db_session.scalar(
        select(Invitation.token).where(Invitation.id == uuid.UUID(invite.json()["id"]))
    )

    preview = await client.get(f"/api/v1/auth/invitations/{token}")
    activated = await client.post(
        "/api/v1/auth/activate", json={"token": token, "password": "Str0ngPass"}
    )
    reused = await client.post(
        "/api/v1/auth/activate", json={"token": token, "password": "Str0ngPass"}
    )
    me = await client.get(
        "/api/v1/users/me", headers=auth_header(activated.json()["access_token"])
    )

    assert preview.json()["email"] == "joiner@test.com"
    assert activated.status_code == 200
    assert reused.status_code == 400
    assert me.json()["roles"][0]["cohort_id"] == str(cohort.id)
    enrolled = await db_session.scalar(
        select(CohortEnrollment).where(
            CohortEnrollment.user_id == uuid.UUID(me.json()["id"])
        )
    )
    assert enrolled.cohort_id == cohort.id


async def test_invitation_admin(client: AsyncClient, admin_user, db_session):
    headers = token_for(admin_user)
    created = await client.post(
        "/api/v1/auth/invite",
        json={
            "email": "pending@x.com",
            "first_name": "P",
            "last_name": "X",
            "roles": ["mentee"],
        },
        headers=headers,
    )
    invitation_id = created.json()["id"]
    old_token = await db_session.scalar(
        select(Invitation.token).where(Invitation.id == uuid.UUID(invitation_id))
    )

    listed = await client.get(
        "/api/v1/admin/invitations", params={"pending_only": True}, headers=headers
    )
    resent = await client.post(
        f"/api/v1/admin/invitations/{invitation_id}/resend", headers=headers
    )
    old_link = await client.get(f"/api/v1/auth/invitations/{old_token}")
    revoked = await client.delete(
        f"/api/v1/admin/invitations/{invitation_id}", headers=headers
    )
    reinvite = await client.post(
        "/api/v1/auth/invite",
        json={
            "email": "pending@x.com",
            "first_name": "P",
            "last_name": "X",
            "roles": ["mentee"],
        },
        headers=headers,
    )

    assert listed.json()["total"] == 1
    assert resent.status_code == 200
    assert old_link.status_code == 400
    assert revoked.status_code == 204
    assert reinvite.status_code == 201


async def test_role_assignment(
    client: AsyncClient, admin_user, regular_user, factory: Factory
):
    cohort = await factory.cohort()
    headers = token_for(admin_user)
    url = f"/api/v1/admin/users/{regular_user.id}/roles"

    added = await client.post(
        url, json={"role": "committee", "cohort_id": str(cohort.id)}, headers=headers
    )
    duplicate = await client.post(
        url, json={"role": "committee", "cohort_id": str(cohort.id)}, headers=headers
    )
    filtered = await client.get(
        "/api/v1/admin/users", params={"role": "committee"}, headers=headers
    )
    removed = await client.delete(f"{url}/{added.json()['id']}", headers=headers)
    self_demote = await client.delete(
        f"/api/v1/admin/users/{admin_user.id}/roles/{admin_user.roles[0].id}",
        headers=headers,
    )

    assert added.status_code == 201
    assert duplicate.status_code == 409
    assert filtered.json()["total"] == 1
    assert removed.status_code == 204
    assert self_demote.status_code == 400


async def test_admin_user_search_and_suspension(
    client: AsyncClient, admin_user, regular_user
):
    headers = token_for(admin_user)

    search = await client.get(
        "/api/v1/admin/users", params={"search": "regular"}, headers=headers
    )
    suspended = await client.post(
        f"/api/v1/admin/users/{regular_user.id}/suspend", headers=headers
    )
    blocked = await client.get("/api/v1/users/me", headers=token_for(regular_user))
    self_suspend = await client.post(
        f"/api/v1/admin/users/{admin_user.id}/suspend", headers=headers
    )

    assert search.json()["total"] == 1
    assert suspended.status_code == 200
    assert blocked.status_code == 403
    assert self_suspend.status_code == 400


async def test_audit_logs(client: AsyncClient, admin_user, regular_user):
    await client.post(
        "/api/v1/auth/login", json={"email": "user@test.com", "password": "UserPass123"}
    )

    mine = await client.get("/api/v1/audit-logs/me", headers=token_for(regular_user))
    everyone = await client.get(
        "/api/v1/admin/audit-logs",
        params={"action": "login"},
        headers=token_for(admin_user),
    )
    denied = await client.get(
        "/api/v1/admin/audit-logs", headers=token_for(regular_user)
    )

    assert [log["action"] for log in mine.json()["items"]] == ["login"]
    assert everyone.json()["total"] == 1
    assert denied.status_code == 403


async def test_refresh_rotation_and_logout_revocation(
    client: AsyncClient, regular_user
):
    tokens = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "user@test.com", "password": "UserPass123"},
        )
    ).json()

    rotated = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    new = rotated.json()
    logout = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": new["refresh_token"]},
        headers=auth_header(new["access_token"]),
    )
    after_logout = await client.get(
        "/api/v1/users/me", headers=auth_header(new["access_token"])
    )
    refresh_after = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new["refresh_token"]}
    )

    assert rotated.status_code == 200
    assert replay.status_code == 401
    assert logout.status_code == 200
    assert after_logout.status_code == 401
    assert after_logout.json()["detail"] == "Token has been revoked"
    assert refresh_after.status_code == 401


async def test_password_reset_flow(client: AsyncClient, regular_user, db_session):
    from forge.models import PasswordResetToken

    await client.post("/api/v1/auth/request-reset", json={"email": "user@test.com"})
    token = await db_session.scalar(select(PasswordResetToken.token))

    reset = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "BrandNew123"},
    )
    old = await client.post(
        "/api/v1/auth/login", json={"email": "user@test.com", "password": "UserPass123"}
    )
    new = await client.post(
        "/api/v1/auth/login", json={"email": "user@test.com", "password": "BrandNew123"}
    )

    assert reset.status_code == 200
    assert old.status_code == 401
    assert new.status_code == 200


@pytest.mark.parametrize(
    "token",
    [
        jwt.encode(
            {"sub": str(uuid.uuid4()), "type": "access", "jti": "x", "exp": 9999999999},
            "wrong-key-" * 4,
            algorithm="HS256",
        ),
        jwt.encode(
            {"sub": str(uuid.uuid4()), "type": "access", "jti": "x", "exp": 9999999999},
            "",
            algorithm="none",
        ),
        "not.a.jwt",
    ],
)
async def test_tampered_tokens_rejected(client: AsyncClient, token: str):
    response = await client.get("/api/v1/users/me", headers=auth_header(token))

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


async def test_refresh_token_cannot_access_api(client: AsyncClient, regular_user):
    tokens = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "user@test.com", "password": "UserPass123"},
        )
    ).json()

    response = await client.get(
        "/api/v1/users/me", headers=auth_header(tokens["refresh_token"])
    )

    assert response.status_code == 401


async def test_login_is_rate_limited(client: AsyncClient):
    auth_rate_limiter.reset()
    statuses = [
        (
            await client.post(
                "/api/v1/auth/login", json={"email": "x@test.com", "password": "nope"}
            )
        ).status_code
        for _ in range(settings.RATE_LIMIT_AUTH_TIMES + 1)
    ]

    assert statuses[:-1] == [401] * settings.RATE_LIMIT_AUTH_TIMES
    assert statuses[-1] == 429


async def test_sql_injection_attempt_is_harmless(
    client: AsyncClient, regular_user, db_session
):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@test.com' OR '1'='1", "password": "x' OR '1'='1"},
    )

    assert response.status_code == 422
    assert (
        await db_session.scalar(select(User.email).where(User.id == regular_user.id))
        == "user@test.com"
    )


async def test_errors_share_envelope(client: AsyncClient):
    missing = await client.get("/api/v1/nope")
    invalid = await client.post("/api/v1/auth/login", json={})

    assert missing.json() == {
        "success": False,
        "error": "not_found",
        "detail": "Not Found",
    }
    assert invalid.json()["error"] == "validation_error"
    assert isinstance(invalid.json()["detail"], list)
