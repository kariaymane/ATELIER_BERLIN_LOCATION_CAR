"""
Account-lockout contract tests.

These cover the release-blocking bug where a 15-minute lockout became a
permanent one: ``failed_login_attempts`` stayed at the threshold after
``locked_until`` expired, so the next mistyped password re-locked the account
instantly and the client saw "compte bloqué" forever.

They also pin the HTTP contract the mobile and desktop clients now depend on:
  200 success / 401 invalid credentials / 403 disabled / 429 active lockout.
"""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.user import User
from app.services.auth_service import LOCKOUT_DURATION, MAX_FAILED_ATTEMPTS

EMAIL = "testadmin@test.com"
GOOD = "TestAdmin123!"
BAD = "WrongPassword!"


async def _reload(db_session, user_id) -> User:
    db_session.expire_all()
    result = await db_session.execute(select(User).where(User.id == user_id))
    return result.scalar_one()


async def _fail_until_locked(client: AsyncClient) -> "object":
    """Burn exactly MAX_FAILED_ATTEMPTS bad passwords; return the last response."""
    response = None
    for _ in range(MAX_FAILED_ATTEMPTS):
        response = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": BAD}
        )
    return response


@pytest.mark.asyncio
class TestLockoutHttpContract:
    async def test_correct_credentials_return_200(self, client: AsyncClient, admin_user):
        r = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": GOOD}
        )
        assert r.status_code == 200
        assert r.json()["access_token"]

    async def test_wrong_password_is_401_and_never_reads_as_locked(
        self, client: AsyncClient, admin_user
    ):
        r = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": BAD}
        )
        assert r.status_code == 401
        assert r.json()["error_code"] == "INVALID_CREDENTIALS"
        assert "bloqu" not in r.json()["detail"].lower()

    async def test_unknown_email_is_401_not_lockout(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/auth/login", json={"email": "nobody@test.com", "password": BAD}
        )
        assert r.status_code == 401
        assert r.json()["error_code"] == "INVALID_CREDENTIALS"

    async def test_active_lockout_is_429_with_retry_after(
        self, client: AsyncClient, admin_user
    ):
        last = await _fail_until_locked(client)
        assert last.status_code == 429
        payload = last.json()
        assert payload["error_code"] == "ACCOUNT_LOCKED"
        assert payload["retry_after_seconds"] == int(LOCKOUT_DURATION.total_seconds())
        assert last.headers["Retry-After"] == str(payload["retry_after_seconds"])

        # A subsequent attempt while locked stays 429 and reports the REMAINING
        # time, not a constant 15 minutes.
        again = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": GOOD}
        )
        assert again.status_code == 429
        assert again.json()["error_code"] == "ACCOUNT_LOCKED"
        assert 0 < again.json()["retry_after_seconds"] <= int(
            LOCKOUT_DURATION.total_seconds()
        )

    async def test_disabled_account_is_403_not_401_or_429(
        self, client: AsyncClient, admin_user, db_session
    ):
        admin_user.is_active = False
        db_session.add(admin_user)
        await db_session.commit()

        r = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": GOOD}
        )
        assert r.status_code == 403
        assert r.json()["error_code"] == "ACCOUNT_DISABLED"


@pytest.mark.asyncio
class TestLockoutExpiry:
    async def test_expired_lockout_accepts_correct_credentials(
        self, client: AsyncClient, admin_user, db_session
    ):
        await _fail_until_locked(client)

        # Move the lockout into the past — the same thing wall-clock time does.
        user = await _reload(db_session, admin_user.id)
        assert user.failed_login_attempts >= MAX_FAILED_ATTEMPTS
        user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.add(user)
        await db_session.commit()

        r = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": GOOD}
        )
        assert r.status_code == 200

        user = await _reload(db_session, admin_user.id)
        assert user.failed_login_attempts == 0
        assert user.locked_until is None

    async def test_expired_lockout_restores_a_full_attempt_budget(
        self, client: AsyncClient, admin_user, db_session
    ):
        """THE REGRESSION: one wrong password after expiry must NOT re-lock.

        Before the fix the counter stayed at the threshold, so attempt #6
        re-armed a fresh 15-minute lockout — a permanent lockout in practice.
        """
        await _fail_until_locked(client)

        user = await _reload(db_session, admin_user.id)
        user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.add(user)
        await db_session.commit()

        r = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": BAD}
        )
        assert r.status_code == 401, "a single post-expiry mistake must not re-lock"
        assert r.json()["error_code"] == "INVALID_CREDENTIALS"

        user = await _reload(db_session, admin_user.id)
        assert user.failed_login_attempts == 1
        assert user.locked_until is None

        # ...and the correct password still works right after that mistake.
        ok = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": GOOD}
        )
        assert ok.status_code == 200

    async def test_exact_expiry_boundary(self, client: AsyncClient, admin_user, db_session):
        """locked_until == now is expired (the check is strictly `> now`)."""
        await _fail_until_locked(client)
        user = await _reload(db_session, admin_user.id)
        user.locked_until = datetime.now(timezone.utc)
        db_session.add(user)
        await db_session.commit()

        r = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": GOOD}
        )
        assert r.status_code == 200

    async def test_naive_locked_until_is_treated_as_utc_not_a_crash(
        self, client: AsyncClient, admin_user, db_session
    ):
        """A naive stored value must compare cleanly, never raise a 500."""
        user = await _reload(db_session, admin_user.id)
        user.failed_login_attempts = MAX_FAILED_ATTEMPTS
        user.locked_until = (datetime.now(timezone.utc) + timedelta(minutes=10)).replace(
            tzinfo=None
        )
        db_session.add(user)
        await db_session.commit()

        r = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": GOOD}
        )
        assert r.status_code == 429
        assert r.json()["error_code"] == "ACCOUNT_LOCKED"

    async def test_server_state_survives_client_restart(
        self, client: AsyncClient, admin_user, db_session
    ):
        """The lockout lives in PostgreSQL, not in any client. A brand-new
        client (fresh connection, no local state) sees the same verdict."""
        await _fail_until_locked(client)

        from httpx import ASGITransport
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://restarted"
        ) as fresh:
            r = await fresh.post(
                "/api/v1/auth/login", json={"email": EMAIL, "password": GOOD}
            )
        assert r.status_code == 429
        assert r.json()["error_code"] == "ACCOUNT_LOCKED"


@pytest.mark.asyncio
class TestLockoutSecurityInvariants:
    async def test_lockout_is_still_armed_after_the_configured_failures(
        self, client: AsyncClient, admin_user, db_session
    ):
        """Security must not be traded away for availability."""
        for i in range(MAX_FAILED_ATTEMPTS - 1):
            r = await client.post(
                "/api/v1/auth/login", json={"email": EMAIL, "password": BAD}
            )
            assert r.status_code == 401, f"attempt {i + 1} must not lock yet"

        r = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": BAD}
        )
        assert r.status_code == 429

        user = await _reload(db_session, admin_user.id)
        assert user.locked_until is not None

    async def test_wrong_password_never_succeeds_after_expiry(
        self, client: AsyncClient, admin_user, db_session
    ):
        await _fail_until_locked(client)
        user = await _reload(db_session, admin_user.id)
        user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.add(user)
        await db_session.commit()

        r = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": BAD}
        )
        assert r.status_code == 401

    async def test_successful_login_clears_failed_attempts(
        self, client: AsyncClient, admin_user, db_session
    ):
        for _ in range(MAX_FAILED_ATTEMPTS - 1):
            await client.post(
                "/api/v1/auth/login", json={"email": EMAIL, "password": BAD}
            )
        user = await _reload(db_session, admin_user.id)
        assert user.failed_login_attempts == MAX_FAILED_ATTEMPTS - 1

        r = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": GOOD}
        )
        assert r.status_code == 200

        user = await _reload(db_session, admin_user.id)
        assert user.failed_login_attempts == 0
        assert user.locked_until is None


@pytest.mark.asyncio
class TestEmailNormalization:
    @pytest.mark.parametrize(
        "variant",
        ["TESTADMIN@TEST.COM", "TestAdmin@Test.Com", "  testadmin@test.com  "],
    )
    async def test_case_and_whitespace_resolve_to_the_same_account(
        self, client: AsyncClient, admin_user, variant
    ):
        r = await client.post(
            "/api/v1/auth/login", json={"email": variant, "password": GOOD}
        )
        assert r.status_code == 200
        assert r.json()["user_id"] == str(admin_user.id)

    async def test_uppercase_failures_lock_the_same_account(
        self, client: AsyncClient, admin_user, db_session
    ):
        """Normalization must not create a second identity with its own counter."""
        for _ in range(MAX_FAILED_ATTEMPTS):
            await client.post(
                "/api/v1/auth/login",
                json={"email": EMAIL.upper(), "password": BAD},
            )
        user = await _reload(db_session, admin_user.id)
        assert user.failed_login_attempts == MAX_FAILED_ATTEMPTS
        assert user.locked_until is not None

        count = await db_session.execute(select(User))
        assert len(list(count.scalars().all())) == 1, "no duplicate identity created"


@pytest.mark.asyncio
class TestJwtAfterLogin:
    async def test_issued_token_authorizes_a_real_api_call(
        self, client: AsyncClient, admin_user
    ):
        login = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": GOOD}
        )
        assert login.status_code == 200
        token = login.json()["access_token"]

        r = await client.get(
            "/api/v1/vehicles/", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200
