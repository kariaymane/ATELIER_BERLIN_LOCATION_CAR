"""
PostgreSQL async database session management.
"""
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase
import logging

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


# Engine and session factory are initialized at startup
_engine = None
_async_session_factory = None


class UnsafePoolConfigError(RuntimeError):
    """Raised when the configured connection pool could exhaust the database."""


def init_engine(database_url: str, echo: bool = False, settings=None):
    """Initialize the async database engine.

    PostgreSQL uses an explicit, env-configurable pool (see ``Settings.DB_POOL_*``)
    that is deliberately sized for a small production database VM. SQLite (used
    for local/test runs) gets a compatible setup since it does not accept
    pool_size/max_overflow with StaticPool.

    Raises :class:`UnsafePoolConfigError` if ``pool_size + max_overflow`` exceeds
    ``DB_MAX_CONNECTIONS_HARD_CAP`` — better a loud failure at boot than a
    database that silently runs out of connections under load.
    """
    global _engine, _async_session_factory
    if database_url.startswith("sqlite"):
        engine_kwargs = {"echo": echo, "connect_args": {"check_same_thread": False}}
        if ":memory:" in database_url:
            from sqlalchemy.pool import StaticPool
            engine_kwargs["poolclass"] = StaticPool
    else:
        if settings is None:
            from app.config import get_settings
            settings = get_settings()

        pool_size = settings.DB_POOL_SIZE
        max_overflow = settings.DB_MAX_OVERFLOW
        ceiling = pool_size + max_overflow
        if ceiling > settings.DB_MAX_CONNECTIONS_HARD_CAP:
            raise UnsafePoolConfigError(
                f"DB pool too large: pool_size={pool_size} + max_overflow={max_overflow} "
                f"= {ceiling} > DB_MAX_CONNECTIONS_HARD_CAP={settings.DB_MAX_CONNECTIONS_HARD_CAP}. "
                "Lower DB_POOL_SIZE / DB_MAX_OVERFLOW or raise the cap deliberately."
            )

        engine_kwargs = {
            "echo": echo,
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "pool_timeout": settings.DB_POOL_TIMEOUT,
            "pool_pre_ping": settings.DB_POOL_PRE_PING,
            "pool_recycle": settings.DB_POOL_RECYCLE,
            "connect_args": {"ssl": False} if "postgresql" in database_url else {},
        }
        logger.info(
            "DB pool: size=%s overflow=%s timeout=%ss recycle=%ss pre_ping=%s "
            "(ceiling %s connections/worker)",
            pool_size, max_overflow, settings.DB_POOL_TIMEOUT,
            settings.DB_POOL_RECYCLE, settings.DB_POOL_PRE_PING, ceiling,
        )

    _engine = create_async_engine(database_url, **engine_kwargs)
    _async_session_factory = async_sessionmaker(
        _engine, class_=AsyncSession, expire_on_commit=False
    )
    logger.info("Database engine initialized")


async def check_database_connection() -> tuple[bool, str | None]:
    """Readiness probe — run a trivial ``SELECT 1``.

    Returns ``(True, None)`` when the database answers, otherwise
    ``(False, "<ExceptionClassName>")``. The error is reduced to the exception
    class name on purpose: it is safe to expose over an unauthenticated
    ``/health/ready`` endpoint (no DSN, host, credentials, or SQL).
    """
    if _engine is None:
        return False, "EngineNotInitialized"
    try:
        from sqlalchemy import text
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # noqa: BLE001 — deliberately broad; category only
        logger.warning("Database readiness check failed: %s", type(exc).__name__)
        return False, type(exc).__name__


def get_pool_status() -> dict:
    """Best-effort pool telemetry for diagnostics. Never raises, never leaks secrets."""
    if _engine is None:
        return {"initialized": False}
    pool = _engine.pool
    status: dict = {"initialized": True, "class": type(pool).__name__}
    for attr in ("size", "checkedin", "checkedout", "overflow"):
        fn = getattr(pool, attr, None)
        if callable(fn):
            try:
                status[attr] = fn()
            except Exception:
                pass
    return status


async def get_db() -> AsyncSession:
    """Dependency that provides a database session."""
    if _async_session_factory is None:
        raise RuntimeError("Database engine not initialized. Call init_engine first.")
    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def dispose_engine():
    """Dispose the engine on shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        logger.info("Database engine disposed")
