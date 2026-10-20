"""Integration tests for authentication endpoints."""

import pytest
from httpx import AsyncClient

from forge.models import User


def auth_header(token: str) -> dict[str, str]:
    """Create authorization header."""
    return {"Authorization": f"Bearer {token}"}


class TestLogin:
    """Tests for login endpoint."""

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, regular_user: User):
        """Test successful login."""
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@test.com", "password": "UserPass123"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient, regular_user: User):
        """Test login with wrong password."""
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@test.com", "password": "WrongPassword123"},
        )

        assert response.status_code == 401
        assert "Invalid email or password" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Test login with non-existent email."""
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@test.com", "password": "SomePass123"},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_suspended_user(
        self, client: AsyncClient, suspended_user: User
    ):
        """Test login with suspended account."""
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "suspended@test.com", "password": "SuspendedPass123"},
        )

        assert response.status_code == 403
        assert "suspended" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_login_pending_user(self, client: AsyncClient, pending_user: User):
        """Test login with pending account."""
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "pending@test.com", "password": "SomePass123"},
        )

        # Pending user has no password, so invalid credentials
        assert response.status_code == 401


class TestActivation:
    """Tests for account activation endpoint."""

    @pytest.mark.asyncio
    async def test_activate_success(self, client: AsyncClient, valid_invitation):
        """Test successful account activation."""
        response = await client.post(
            "/api/v1/auth/activate",
            json={
                "token": "valid-invitation-token",
                "password": "NewUserPass123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    @pytest.mark.asyncio
    async def test_activate_invalid_token(self, client: AsyncClient):
        """Test activation with invalid token."""
        response = await client.post(
            "/api/v1/auth/activate",
            json={
                "token": "invalid-token",
                "password": "NewUserPass123",
            },
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_activate_expired_token(
        self, client: AsyncClient, expired_invitation
    ):
        """Test activation with expired token."""
        response = await client.post(
            "/api/v1/auth/activate",
            json={
                "token": "expired-invitation-token",
                "password": "NewUserPass123",
            },
        )

        assert response.status_code == 400
        assert "expired" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_activate_weak_password(self, client: AsyncClient, valid_invitation):
        """Test activation with weak password."""
        response = await client.post(
            "/api/v1/auth/activate",
            json={
                "token": "valid-invitation-token",
                "password": "weak",
            },
        )

        assert response.status_code == 422


class TestRefreshToken:
    """Tests for token refresh endpoint."""

    @pytest.mark.asyncio
    async def test_refresh_success(self, client: AsyncClient, regular_user: User):
        """Test successful token refresh."""
        # First login to get tokens
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@test.com", "password": "UserPass123"},
        )
        refresh_token = login_response.json()["refresh_token"]

        # Refresh the token
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    @pytest.mark.asyncio
    async def test_refresh_invalid_token(self, client: AsyncClient):
        """Test refresh with invalid token."""
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid-token"},
        )

        assert response.status_code == 401


class TestInvite:
    """Tests for user invitation endpoint."""

    @pytest.mark.asyncio
    async def test_invite_success(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_token: str,
    ):
        """Test successful user invitation."""
        response = await client.post(
            "/api/v1/auth/invite",
            json={
                "email": "invited@test.com",
                "first_name": "Invited",
                "last_name": "User",
                "roles": ["mentee"],
            },
            headers=auth_header(admin_token),
        )

        assert response.status_code == 201
        assert response.json()["email"] == "invited@test.com"

    @pytest.mark.asyncio
    async def test_invite_unauthorized(self, client: AsyncClient, user_token: str):
        """Test invitation by non-admin user."""
        response = await client.post(
            "/api/v1/auth/invite",
            json={
                "email": "invited@test.com",
                "first_name": "Invited",
                "last_name": "User",
                "roles": ["mentee"],
            },
            headers=auth_header(user_token),
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_invite_existing_user(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_token: str,
        regular_user: User,
    ):
        """Test inviting an existing user."""
        response = await client.post(
            "/api/v1/auth/invite",
            json={
                "email": "user@test.com",  # Already exists
                "first_name": "Test",
                "last_name": "User",
                "roles": ["mentee"],
            },
            headers=auth_header(admin_token),
        )

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_invite_no_auth(self, client: AsyncClient):
        """Test invitation without authentication."""
        response = await client.post(
            "/api/v1/auth/invite",
            json={
                "email": "invited@test.com",
                "first_name": "Invited",
                "last_name": "User",
                "roles": ["mentee"],
            },
        )

        assert response.status_code == 401


class TestLogout:
    """Tests for logout endpoint."""

    @pytest.mark.asyncio
    async def test_logout_success(
        self,
        client: AsyncClient,
        regular_user: User,
    ):
        """Test successful logout."""
        # Login first
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@test.com", "password": "UserPass123"},
        )
        access_token = login_response.json()["access_token"]

        # Logout
        response = await client.post(
            "/api/v1/auth/logout",
            headers=auth_header(access_token),
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_logout_no_auth(self, client: AsyncClient):
        """Test logout without authentication."""
        response = await client.post("/api/v1/auth/logout")

        assert response.status_code == 401


class TestPasswordReset:
    """Tests for password reset endpoints."""

    @pytest.mark.asyncio
    async def test_request_reset_existing_user(
        self,
        client: AsyncClient,
        regular_user: User,
    ):
        """Test password reset request for existing user."""
        response = await client.post(
            "/api/v1/auth/request-reset",
            json={"email": "user@test.com"},
        )

        # Always returns success to prevent email enumeration
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_request_reset_nonexistent_user(self, client: AsyncClient):
        """Test password reset request for non-existent user."""
        response = await client.post(
            "/api/v1/auth/request-reset",
            json={"email": "nobody@test.com"},
        )

        # Still returns success to prevent email enumeration
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_reset_password_invalid_token(self, client: AsyncClient):
        """Test password reset with invalid token."""
        response = await client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": "invalid-reset-token",
                "new_password": "NewSecurePass123",
            },
        )

        assert response.status_code == 400
