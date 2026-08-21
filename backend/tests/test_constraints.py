"""
Tests for PostgreSQL constraints — verifying database-level integrity.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from uuid import uuid4

from app.models.user import User
from app.models.vehicle import Vehicle
from app.auth.password import hash_password


@pytest.mark.asyncio
class TestConstraints:
    async def test_user_duplicate_email(self, db_session: AsyncSession):
        u1 = User(id=uuid4(), email="dup@test.com", username="dup1",
                   password_hash=hash_password("Test123!"), full_name="Dup 1", role="EMPLOYEE")
        db_session.add(u1)
        await db_session.flush()

        u2 = User(id=uuid4(), email="dup@test.com", username="dup2",
                   password_hash=hash_password("Test123!"), full_name="Dup 2", role="EMPLOYEE")
        db_session.add(u2)
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_user_invalid_role(self, db_session: AsyncSession):
        u = User(id=uuid4(), email="badrole@test.com", username="badrole",
                 password_hash=hash_password("Test123!"), full_name="Bad Role", role="SUPERUSER")
        db_session.add(u)
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_vehicle_negative_price(self, db_session: AsyncSession):
        v = Vehicle(
            id=uuid4(), registration="NEGP-01", vin="WVWZZZ3CZWENEGP01",
            brand="Test", model="Car", year=2024, color="Red",
            fuel_type="DIESEL", transmission="MANUAL",
            purchase_price=-100, daily_rental_price=300,
        )
        db_session.add(v)
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_vehicle_invalid_year(self, db_session: AsyncSession):
        v = Vehicle(
            id=uuid4(), registration="YEAR-01", vin="WVWZZZ3CZWEYEAR01",
            brand="Test", model="Car", year=1980, color="Red",
            fuel_type="DIESEL", transmission="MANUAL",
        )
        db_session.add(v)
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_vehicle_vin_wrong_length(self, db_session: AsyncSession):
        v = Vehicle(
            id=uuid4(), registration="VINL-01", vin="SHORT",
            brand="Test", model="Car", year=2024, color="Red",
            fuel_type="DIESEL", transmission="MANUAL",
        )
        db_session.add(v)
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()
