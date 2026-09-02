"""
Test configuration and fixtures.
Uses a test PostgreSQL database for integration tests.
"""
import os
import asyncio
from typing import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.pool import NullPool, StaticPool
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)

# Hard safety guard: Never use inherited DATABASE_URL in tests
# unless explicitly marked as a test database.
env_url = os.environ.get("DATABASE_URL", "")
if env_url and ("production" in env_url.lower() or "prod" in env_url.lower() or "fly" in env_url.lower() or "supabase" in env_url.lower()):
    raise RuntimeError("DANGER: Tests attempted to use a production DATABASE_URL. Execution aborted.")

# CI runs the suite a SECOND time against a real PostgreSQL (TEST_DATABASE_URL)
# so the prod code path — TIMESTAMP(timezone=True) aware round-trips, tstzrange
# GIST exclusion constraints, NUMERIC summation — is actually exercised. Locally
# and by default, the fast in-memory SQLite path is used.
# (FORENSIC_ROOT_CAUSE_ANALYSIS.md §1.2)
_test_db = os.environ.get("TEST_DATABASE_URL", "").strip()
if _test_db and ("production" in _test_db.lower() or "fly" in _test_db.lower() or "supabase" in _test_db.lower()):
    raise RuntimeError("DANGER: TEST_DATABASE_URL points at production. Aborted.")

if _test_db:
    os.environ["DATABASE_URL"] = _test_db
    os.environ["DATABASE_URL_SYNC"] = os.environ.get(
        "TEST_DATABASE_URL_SYNC",
        _test_db.replace("+asyncpg", "").replace("postgresql", "postgresql+psycopg2", 1)
        if "postgresql" in _test_db else _test_db,
    )
else:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["DATABASE_URL_SYNC"] = "sqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-jwt-secret-not-for-production"
os.environ["JWT_REFRESH_SECRET"] = "test-jwt-refresh-secret-not-for-production"
os.environ["ADMIN_PASSWORD"] = "TestAdmin123!"
os.environ["DEBUG"] = "true"

from app.main import app
from app.database import Base, get_db
from app.auth.password import hash_password
from app.models.user import User


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create test database engine."""
    url = os.environ["DATABASE_URL"]
    pool_cls = StaticPool if "sqlite" in url else NullPool
    engine = create_async_engine(url, echo=False, poolclass=pool_cls)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        if "postgresql" in url:
            await conn.execute(
                __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS btree_gist")
            )
        await conn.run_sync(Base.metadata.create_all)
        
        # Emulate PostgreSQL exclusion constraint for double booking in SQLite tests
        if "sqlite" in url:
            from sqlalchemy import text
            await conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_check_overlap_res
                BEFORE INSERT ON reservations
                FOR EACH ROW
                WHEN NEW.status NOT IN ('CANCELLED', 'COMPLETED')
                BEGIN
                    SELECT RAISE(ABORT, 'IntegrityError: Overlapping reservation exists')
                    WHERE EXISTS (
                        SELECT 1 FROM reservations
                        WHERE vehicle_id = NEW.vehicle_id
                          AND status NOT IN ('CANCELLED', 'COMPLETED')
                          AND start_datetime < NEW.end_datetime
                          AND end_datetime > NEW.start_datetime
                    );
                END;
            """))
            await conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_check_overlap_res_update
                BEFORE UPDATE ON reservations
                FOR EACH ROW
                WHEN NEW.status NOT IN ('CANCELLED', 'COMPLETED')
                BEGIN
                    SELECT RAISE(ABORT, 'IntegrityError: Overlapping reservation exists')
                    WHERE EXISTS (
                        SELECT 1 FROM reservations
                        WHERE vehicle_id = NEW.vehicle_id
                          AND id != NEW.id
                          AND status NOT IN ('CANCELLED', 'COMPLETED')
                          AND start_datetime < NEW.end_datetime
                          AND end_datetime > NEW.start_datetime
                    );
                END;
            """))

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_tables(test_engine):
    """Clean all tables before each test."""
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    yield


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean test database session."""
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP test client."""
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    # The readiness probe (/health/ready, /api/v1/sync/ready) runs `SELECT 1`
    # through app.database's module-level engine — the httpx ASGITransport does
    # not run the lifespan that would normally initialise it, so point it at the
    # test engine for the duration of the fixture.
    import app.database as _database_module
    _saved_engine = _database_module._engine
    _saved_factory = _database_module._async_session_factory
    _database_module._engine = test_engine
    _database_module._async_session_factory = session_factory

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    _database_module._engine = _saved_engine
    _database_module._async_session_factory = _saved_factory
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Create an admin user for testing."""
    user = User(
        id=uuid4(),
        email="testadmin@test.com",
        username="testadmin",
        password_hash=hash_password("TestAdmin123!"),
        full_name="Test Admin",
        role="ADMIN",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def employee_user(db_session: AsyncSession) -> User:
    """Create an employee user for testing."""
    user = User(
        id=uuid4(),
        email="testemp@test.com",
        username="testemp",
        password_hash=hash_password("TestEmp123!"),
        full_name="Test Employee",
        role="EMPLOYEE",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_token(admin_user: User) -> str:
    """Get an auth token for admin user."""
    from app.dependencies import get_jwt_handler
    handler = get_jwt_handler()
    return handler.create_access_token(user_id=str(admin_user.id), role=admin_user.role)


@pytest_asyncio.fixture
async def employee_token(employee_user: User) -> str:
    """Get an auth token for employee user."""
    from app.dependencies import get_jwt_handler
    handler = get_jwt_handler()
    return handler.create_access_token(user_id=str(employee_user.id), role=employee_user.role)
