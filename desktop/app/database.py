"""
Local SQLite database for offline-first Desktop operation.
Mirrors the PostgreSQL schema with SQLite-compatible types.
"""
from sqlalchemy import create_engine, Column, String, Integer, Float, Text, Boolean
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.config import SQLITE_URL
import logging

logger = logging.getLogger(__name__)


class LocalBase(DeclarativeBase):
    pass


_engine = None
_session_factory = None


def init_local_db():
    """Initialize the local SQLite database."""
    global _engine, _session_factory
    _engine = create_engine(SQLITE_URL, echo=False)
    _session_factory = sessionmaker(bind=_engine)
    # Import all models here to ensure they are registered with LocalBase
    import app.models.user
    import app.models.vehicle
    import app.models.vehicle_image
    import app.models.sync_queue
    import app.models.reservation
    import app.models.maintenance

    # Create all tables
    LocalBase.metadata.create_all(_engine)

    # Auto-migration for newly added columns if SQLite database existed
    with _engine.connect() as conn:
        try:
            from sqlalchemy import text
            result = conn.execute(text("PRAGMA table_info(vehicles)")).fetchall()
            col_names = [row[1] for row in result]
            if "image_url" not in col_names:
                conn.execute(text("ALTER TABLE vehicles ADD COLUMN image_url VARCHAR(500)"))
                conn.commit()
                logger.info("Migrated SQLite schema: added image_url to vehicles")
        except Exception as e:
            logger.warning("Auto-migration check notice: %s", e)

    logger.info("Local SQLite database initialized at %s", SQLITE_URL)


def get_local_session() -> Session:
    """Get a local database session."""
    if _session_factory is None:
        init_local_db()
    return _session_factory()
