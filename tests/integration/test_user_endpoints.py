"""Integration tests for user management endpoints."""

import pytest
from httpx import AsyncClient

from forge.models import User, UserRole
from tests.conftest import Factory, Programme, token_for


def auth_header(token: str) -> dict[str, str]:
    """Create authorization header."""
    return {"Authorization": f"Bearer {token}"}


class TestUserProfile:
    """Tests for user profile endpoints."""

    @pytest.mark.asyncio
    async def test_get_profile(
        self,
        client: AsyncClient,
        regular_user: User,
        user_token: str,
    ):
        """Test getting current user's profile."""
        response = await client.get(
            "/api/v1/users/me",
            headers=auth_header(user_token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "user@test.com"
        assert data["first_name"] == "Regular"
        assert data["last_name"] == "User"
        assert data["account_state"] == "active"

    @pytest.mark.asyncio
    async def test_get_profile_no_auth(self, client: AsyncClient):
        """Test getting profile without authentication."""
        response = await client.get("/api/v1/users/me")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_update_profile(
        self,
        client: AsyncClient,
        regular_user: User,
        user_token: str,
    ):
        """Test updating current user's profile."""
        response = await client.patch(
            "/api/v1/users/me",
            json={"first_name": "Updated", "last_name": "Name"},
            headers=auth_header(user_token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "Updated"
        assert data["last_name"] == "Name"

    @pytest.mark.asyncio
    async def test_update_profile_partial(
        self,
        client: AsyncClient,
        regular_user: User,
        user_token: str,
    ):
        """Test partial profile update."""
        response = await client.patch(
            "/api/v1/users/me",
            json={"first_name": "OnlyFirst"},
            headers=auth_header(user_token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "OnlyFirst"
        assert data["last_name"] == "User"  # Unchanged


class TestAdminUserManagement:
    """Tests for admin user management endpoints."""

    @pytest.mark.asyncio
    async def test_list_users(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_token: str,
        regular_user: User,
    ):
        """Test listing all users."""
        response = await client.get(
            "/api/v1/admin/users",
            headers=auth_header(admin_token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 2
        assert len(data["items"]) >= 2

    @pytest.mark.asyncio
    async def test_list_users_pagination(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_token: str,
    ):
        """Test user list pagination."""
        response = await client.get(
            "/api/v1/admin/users?page=1&page_size=1",
            headers=auth_header(admin_token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 1
        assert len(data["items"]) <= 1

    @pytest.mark.asyncio
    async def test_list_users_non_admin(
        self,
        client: AsyncClient,
        user_token: str,
    ):
        """Test that non-admin cannot list users."""
        response = await client.get(
            "/api/v1/admin/users",
            headers=auth_header(user_token),
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_user_details(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_token: str,
        regular_user: User,
    ):
        """Test getting user details by ID."""
        response = await client.get(
            f"/api/v1/admin/users/{regular_user.id}",
            headers=auth_header(admin_token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "user@test.com"
        assert "roles" in data

    @pytest.mark.asyncio
    async def test_get_user_details_not_found(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_token: str,
    ):
        """Test getting non-existent user."""
        import uuid

        fake_id = uuid.uuid4()
        response = await client.get(
            f"/api/v1/admin/users/{fake_id}",
            headers=auth_header(admin_token),
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_update_user(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_token: str,
        regular_user: User,
    ):
        """Test admin updating user details."""
        response = await client.patch(
            f"/api/v1/admin/users/{regular_user.id}",
            json={"first_name": "AdminUpdated"},
            headers=auth_header(admin_token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "AdminUpdated"

    @pytest.mark.asyncio
    async def test_suspend_user(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_token: str,
        regular_user: User,
    ):
        """Test suspending a user account."""
        response = await client.post(
            f"/api/v1/admin/users/{regular_user.id}/suspend",
            headers=auth_header(admin_token),
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_suspend_self(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_token: str,
    ):
        """Test that admin cannot suspend themselves."""
        response = await client.post(
            f"/api/v1/admin/users/{admin_user.id}/suspend",
            headers=auth_header(admin_token),
        )

        assert response.status_code == 400
        assert "own account" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_activate_user(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_token: str,
        suspended_user: User,
    ):
        """Test reactivating a suspended user."""
        response = await client.post(
            f"/api/v1/admin/users/{suspended_user.id}/activate",
            headers=auth_header(admin_token),
        )

        assert response.status_code == 200
        assert response.json()["success"] is True


async def test_profile_fields(client: AsyncClient, programme: Programme):
    headers = token_for(programme.mentees[0])

    updated = await client.patch(
        "/api/v1/users/me",
        json={
            "university": "Strathmore University",
            "programme_of_study": "Computer Science",
            "degree_level": "bachelors",
            "gender": "male",
            "phone": "+254 700 000000",
            "birthday": "2003-04-05",
            "social_links": {"github": "https://github.com/mentee0"},
        },
        headers=headers,
    )
    no_track = await client.patch(
        "/api/v1/users/me", json={"ict_track": "data"}, headers=headers
    )
    bad_phone = await client.patch(
        "/api/v1/users/me", json={"phone": "call me"}, headers=headers
    )
    admin_view = (
        await client.get(
            f"/api/v1/admin/users/{programme.mentees[0].id}",
            headers=token_for(programme.admin),
        )
    ).json()

    body = updated.json()
    assert (body["university"], body["degree_level"]) == (
        "Strathmore University",
        "bachelors",
    )
    assert body["social_links"]["github"] == "https://github.com/mentee0"
    assert body["ict_track"] == "web"
    assert body["is_alumni"] is False
    assert no_track.status_code == 422
    assert bad_phone.status_code == 422
    assert admin_view["birthday"] == "2003-04-05"
    assert admin_view["ict_track"] == "web"


async def test_my_cohorts_and_active_context(
    client: AsyncClient, programme: Programme, factory: Factory
):
    other = await factory.cohort(name="Cohort 12")
    await factory.enroll(programme.peer_mentor, other, UserRole.MENTEE)
    headers = token_for(programme.peer_mentor)

    cohorts = (await client.get("/api/v1/users/me/cohorts", headers=headers)).json()
    wrong_role = await client.put(
        "/api/v1/users/me/active-cohort",
        json={"cohort_id": str(other.id), "role": "peer_mentor_1_1"},
        headers=headers,
    )
    switched = await client.put(
        "/api/v1/users/me/active-cohort",
        json={"cohort_id": str(other.id), "role": "mentee"},
        headers=headers,
    )
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    assert {c["cohort"]["id"]: c["roles"] for c in cohorts} == {
        str(programme.cohort.id): ["peer_mentor_1_1"],
        str(other.id): ["mentee"],
    }
    assert wrong_role.status_code == 400
    assert switched.status_code == 200
    assert (me["active_cohort_id"], me["active_role"]) == (str(other.id), "mentee")


async def test_role_enum(client: AsyncClient, programme: Programme):
    url = f"/api/v1/admin/users/{programme.outsider.id}/roles"
    headers = token_for(programme.admin)

    partner = await client.post(url, json={"role": "partner"}, headers=headers)
    lead = await client.post(url, json={"role": "program_lead"}, headers=headers)
    old_name = await client.post(url, json={"role": "peer_mentor_1:1"}, headers=headers)

    assert partner.status_code == 422
    assert lead.status_code == 201
    assert old_name.status_code == 422
