"""
Tests for authentication endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestLogin:
    """Test login endpoint."""

    async def test_login_success(self, client: AsyncClient, admin_user):
        """Test successful login returns tokens."""
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "testadmin@test.com", "password": "TestAdmin123!"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["role"] == "ADMIN"

    async def test_login_wrong_password(self, client: AsyncClient, admin_user):
        """Test login with wrong password returns 401."""
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "testadmin@test.com", "password": "WrongPassword!"},
        )
        assert response.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Test login with nonexistent email returns 401."""
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@test.com", "password": "SomePassword!"},
        )
        assert response.status_code == 401

    async def test_login_short_password(self, client: AsyncClient):
        """Test login with short password fails validation."""
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@test.com", "password": "short"},
        )
        assert response.status_code == 422  # Pydantic validation

    async def test_access_protected_route_without_token(self, client: AsyncClient):
        """Test accessing protected route without token returns 403."""
        response = await client.get("/api/v1/vehicles/")
        assert response.status_code in (401, 403)

    async def test_access_with_invalid_token(self, client: AsyncClient):
        """Test accessing protected route with invalid token returns 401."""
        response = await client.get(
            "/api/v1/vehicles/",
            headers={"Authorization": "Bearer invalidtoken123"},
        )
        assert response.status_code == 401


@pytest.mark.asyncio
class TestTokenRefresh:
    """Test token refresh."""

    async def test_refresh_token(self, client: AsyncClient, admin_user):
        """Test refreshing access token with valid refresh token."""
        # Login first
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "testadmin@test.com", "password": "TestAdmin123!"},
        )
        assert login_resp.status_code == 200
        refresh_token = login_resp.json()["refresh_token"]

        # Refresh
        refresh_resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_resp.status_code == 200
        data = refresh_resp.json()
        assert "access_token" in data
        assert "refresh_token" in data


@pytest.mark.asyncio
class TestLogout:
    """Test logout."""

    async def test_logout(self, client: AsyncClient, admin_user):
        """Test logout revokes refresh token."""
        # Login
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "testadmin@test.com", "password": "TestAdmin123!"},
        )
        data = login_resp.json()
        access_token = data["access_token"]
        refresh_token = data["refresh_token"]

        # Logout
        logout_resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert logout_resp.status_code == 200

        # Try to use revoked refresh token
        refresh_resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_resp.status_code == 401
