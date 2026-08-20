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
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)

# Set test environment before importing app
os.environ["DATABASE_URL"] = "postgresql+asyncpg://rental_app:changeme_dev_only@localhost:5432/car_rental_test"
os.environ["DATABASE_URL_SYNC"] = "postgresql://rental_app:changeme_dev_only@localhost:5432/car_rental_test"
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
    engine = create_async_engine(url, echo=False, poolclass=NullPool)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(
            __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS btree_gist")
        )
        await conn.run_sync(Base.metadata.create_all)

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
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

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
