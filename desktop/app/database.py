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
    """Initialize the local SQLite database.
    In **test mode** (environment variable ``CAR_RENTAL_DB_RESET=1``) the existing SQLite file is deleted to provide a clean database.
    In normal production runs the database file is preserved; tables are created if they do not yet exist.
    """
    global _engine, _session_factory
    import os
    reset_mode = os.getenv("CAR_RENTAL_DB_RESET", "0") == "1"
    db_path = SQLITE_URL.replace('sqlite:///', '')
    if reset_mode:
        try:
            if os.path.exists(db_path):
                os.remove(db_path)
                logger.info("[RESET] SQLite database reset because CAR_RENTAL_DB_RESET=1.")
        except Exception as e:
            logger.warning("Failed to remove existing SQLite file %s: %s", db_path, e)
    else:
        logger.info("[PRESERVE] Existing SQLite database preserved.")
    # Create engine (will create file if missing)
    _engine = create_engine(SQLITE_URL, echo=False)
    _session_factory = sessionmaker(bind=_engine)
    # Import all models to ensure they are registered with LocalBase
    import app.models.user
    import app.models.vehicle
    import app.models.vehicle_image
    import app.models.sync_queue
    import app.models.reservation
    import app.models.maintenance
    import app.models.client
    import app.models.pending_upload

    # Ensure tables exist (does not drop existing data)
    LocalBase.metadata.create_all(_engine)

    # Auto-migration for newly added columns if SQLite database existed (now redundant but kept)
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

        try:
            result = conn.execute(text("PRAGMA table_info(reservations)")).fetchall()
            col_names = [row[1] for row in result]
            if "customer_email" not in col_names:
                conn.execute(text("ALTER TABLE reservations ADD COLUMN customer_email VARCHAR(255)"))
            if "identity_card_image" not in col_names:
                conn.execute(text("ALTER TABLE reservations ADD COLUMN identity_card_image TEXT"))
            if "driving_license_image" not in col_names:
                conn.execute(text("ALTER TABLE reservations ADD COLUMN driving_license_image TEXT"))
            conn.commit()
        except Exception as e:
            logger.warning("Auto-migration check notice (reservations): %s", e)


    logger.info("Local SQLite database initialized at %s", SQLITE_URL)


def get_local_session() -> Session:
    """Get a local database session."""
    if _session_factory is None:
        init_local_db()
    return _session_factory()
