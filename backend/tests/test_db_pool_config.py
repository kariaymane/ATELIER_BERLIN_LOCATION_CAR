"""
Database connection-pool sizing.

Root cause this guards: the async engine was hard-coded to
`pool_size=20, max_overflow=10` — up to 30 server-side PostgreSQL connections
from a single worker. On the small production `postgres-flex` VM that is an
OOM / "too many connections" hazard and is the most likely trigger for the
production database crash.

Contract:
  * pool values are explicit + env-configurable (Settings.DB_POOL_*)
  * the default ceiling (pool_size + max_overflow) is small and <= the hard cap
  * init_engine REFUSES to start if the configured pool exceeds the hard cap
    (loud failure beats a silently exhausted database)
  * the ceiling is per-worker; the container runs one worker
"""
import pytest

from app.config import Settings
from app.database import init_engine, UnsafePoolConfigError


def _settings(**over):
    base = dict(
        DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db",
        JWT_SECRET="x" * 16,
        JWT_REFRESH_SECRET="y" * 16,
    )
    base.update(over)
    return Settings(**base)


def test_defaults_are_explicit_and_small():
    s = _settings()
    assert s.DB_POOL_SIZE == 5
    assert s.DB_MAX_OVERFLOW == 5
    assert s.DB_POOL_TIMEOUT == 30
    assert s.DB_POOL_RECYCLE == 1800
    assert s.DB_POOL_PRE_PING is True


def test_default_ceiling_is_within_hard_cap():
    s = _settings()
    assert s.db_max_connections_per_worker == 10
    assert s.db_max_connections_per_worker <= s.DB_MAX_CONNECTIONS_HARD_CAP


def test_ceiling_property_tracks_config():
    s = _settings(DB_POOL_SIZE=8, DB_MAX_OVERFLOW=4)
    assert s.db_max_connections_per_worker == 12


def test_init_engine_applies_configured_pool_without_connecting():
    s = _settings(DB_POOL_SIZE=5, DB_MAX_OVERFLOW=5)
    init_engine(s.DATABASE_URL, settings=s)
    from app.database import _engine
    # QueuePool.size() reports the configured persistent size; no I/O needed.
    assert _engine.pool.size() == 5
    # SQLAlchemy stores max_overflow on the pool.
    assert _engine.pool._max_overflow == 5


def test_init_engine_rejects_pool_larger_than_hard_cap():
    s = _settings(DB_POOL_SIZE=40, DB_MAX_OVERFLOW=40, DB_MAX_CONNECTIONS_HARD_CAP=40)
    with pytest.raises(UnsafePoolConfigError):
        init_engine(s.DATABASE_URL, settings=s)


def test_init_engine_rejects_the_old_hardcoded_values_against_a_low_cap():
    # The previous hard-coded config (20 + 10 = 30). With a deliberately low
    # cap it must be refused rather than silently accepted.
    s = _settings(DB_POOL_SIZE=20, DB_MAX_OVERFLOW=10, DB_MAX_CONNECTIONS_HARD_CAP=20)
    with pytest.raises(UnsafePoolConfigError):
        init_engine(s.DATABASE_URL, settings=s)


def test_pool_size_bounds_are_enforced_by_settings():
    with pytest.raises(Exception):
        _settings(DB_POOL_SIZE=0)
    with pytest.raises(Exception):
        _settings(DB_POOL_SIZE=999)


@pytest.fixture(autouse=True)
def _restore_engine():
    """Each test here reinitialises the module engine; put the test engine back."""
    import app.database as dbm
    saved_engine = dbm._engine
    saved_factory = dbm._async_session_factory
    yield
    dbm._engine = saved_engine
    dbm._async_session_factory = saved_factory
