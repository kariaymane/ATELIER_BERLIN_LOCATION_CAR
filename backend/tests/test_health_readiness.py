"""
Liveness vs readiness separation.

Root cause this guards: `/health` was a static stub that returned
`{"status": "healthy"}` without ever touching the database. When the
production PostgreSQL VM fell over, `/health` stayed green, Fly kept the
machine in rotation, and every real (DB-backed) request returned HTTP 500 —
which the mobile app surfaced as "connexion au serveur impossible".

Contract:
  * LIVENESS  (/health, /health/live, /api/v1/sync/health)
        - 200 whenever the ASGI process can answer
        - NEVER runs a query; `database` is reported as "not_checked"
        - must not be readable as a "database is ready" signal
  * READINESS (/health/ready, /api/v1/sync/ready)
        - runs `SELECT 1`
        - 200 + database="connected" when the DB answers
        - 503 + database="unavailable" + error_category when it does not
        - leaks no DSN / host / credential / SQL
"""
import app.database as database_module
import pytest


# ── LIVENESS ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_liveness_is_200_and_does_not_check_db(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "alive"
    assert body["database"] == "not_checked"
    # Liveness must never claim readiness.
    assert body["status"] not in ("ready", "healthy_db", "connected")


@pytest.mark.asyncio
async def test_health_live_alias_matches_health(client):
    a = await client.get("/health")
    b = await client.get("/health/live")
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()


@pytest.mark.asyncio
async def test_sync_health_is_liveness_only(client):
    resp = await client.get("/api/v1/sync/health")
    assert resp.status_code == 200
    # SyncHealthResponse has no `database` field — it is liveness, nothing more.
    assert "database" not in resp.json()


@pytest.mark.asyncio
async def test_liveness_stays_green_even_when_db_is_down(client, monkeypatch):
    """A DB outage must NOT take liveness down (Fly would kill the machine)."""
    async def dead_db():
        return False, "OperationalError"
    monkeypatch.setattr(database_module, "check_database_connection", dead_db)

    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["database"] == "not_checked"


# ── READINESS: DB up ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_readiness_200_when_db_answers(client):
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["database"] == "connected"
    assert "error_category" not in body


@pytest.mark.asyncio
async def test_sync_readiness_200_when_db_answers(client):
    resp = await client.get("/api/v1/sync/ready")
    assert resp.status_code == 200
    assert resp.json()["database"] == "connected"


# ── READINESS: DB down ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_readiness_503_when_db_unavailable(client, monkeypatch):
    async def dead_db():
        return False, "OperationalError"
    monkeypatch.setattr(database_module, "check_database_connection", dead_db)

    resp = await client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["database"] == "unavailable"
    assert body["error_category"] == "OperationalError"


@pytest.mark.asyncio
async def test_sync_readiness_503_when_db_unavailable(client, monkeypatch):
    async def dead_db():
        return False, "TimeoutError"
    monkeypatch.setattr(database_module, "check_database_connection", dead_db)

    resp = await client.get("/api/v1/sync/ready")
    assert resp.status_code == 503
    assert resp.json()["database"] == "unavailable"


@pytest.mark.asyncio
async def test_readiness_failure_body_leaks_no_secrets(client, monkeypatch):
    async def dead_db():
        return False, "OperationalError"
    monkeypatch.setattr(database_module, "check_database_connection", dead_db)

    resp = await client.get("/health/ready")
    raw = resp.text.lower()
    for needle in ("password", "postgres://", "postgresql://", "asyncpg",
                   "@", "secret", "dsn", "5432", "5433", "select 1"):
        assert needle not in raw, f"readiness body leaked {needle!r}"


# ── the real SELECT 1 probe ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_database_connection_true_against_live_engine(client):
    # the `client` fixture points app.database at the in-memory test engine.
    ok, err = await database_module.check_database_connection()
    assert ok is True
    assert err is None


@pytest.mark.asyncio
async def test_check_database_connection_false_when_engine_missing(monkeypatch):
    monkeypatch.setattr(database_module, "_engine", None)
    ok, err = await database_module.check_database_connection()
    assert ok is False
    assert err == "EngineNotInitialized"
