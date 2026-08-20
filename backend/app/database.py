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


def init_engine(database_url: str, echo: bool = False):
    """Initialize the async database engine."""
    global _engine, _async_session_factory
    _engine = create_async_engine(
        database_url,
        echo=echo,
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    _async_session_factory = async_sessionmaker(
        _engine, class_=AsyncSession, expire_on_commit=False
    )
    logger.info("Database engine initialized")


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
