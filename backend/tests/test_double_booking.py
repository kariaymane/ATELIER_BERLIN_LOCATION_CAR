"""
Tests for double-booking prevention at the PostgreSQL level.
"""
import pytest
from httpx import AsyncClient
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.models.vehicle import Vehicle
from app.models.reservation import Reservation


SAMPLE_VEHICLE = {
    "registration": "DBL-BK-01",
    "vin": "WVWZZZ3CZWEDBLBK1",
    "brand": "Toyota",
    "model": "Yaris",
    "year": 2023,
    "color": "Bleu",
    "fuel_type": "GASOLINE",
    "transmission": "AUTOMATIC",
    "current_mileage": 10000,
    "purchase_mileage": 0,
    "purchase_price": 100000.00,
    "daily_rental_price": 300.00,
}


@pytest.mark.asyncio
class TestDoubleBookingPrevention:
    """Test that PostgreSQL EXCLUSION constraint prevents double booking."""

    async def test_overlapping_reservations_rejected(self, db_session: AsyncSession):
        """Two overlapping reservations for the same vehicle must be rejected by PostgreSQL."""
        vehicle = Vehicle(
            id=uuid4(),
            registration="OVERLAP-01",
            vin="WVWZZZ3CZWEOVRLP1",
            brand="Test", model="Car", year=2024,
            color="Red", fuel_type="DIESEL",
            transmission="MANUAL",
        )
        db_session.add(vehicle)
        await db_session.flush()

        now = datetime.now(timezone.utc)
        res1 = Reservation(
            id=uuid4(),
            vehicle_id=vehicle.id,
            start_datetime=now,
            end_datetime=now + timedelta(days=5),
            daily_price=300, num_days=5,
            total_price=1500, deposit=500,
            status="RESERVED",
        )
        db_session.add(res1)
        await db_session.flush()

        # Overlapping reservation
        res2 = Reservation(
            id=uuid4(),
            vehicle_id=vehicle.id,
            start_datetime=now + timedelta(days=3),
            end_datetime=now + timedelta(days=8),
            daily_price=300, num_days=5,
            total_price=1500, deposit=500,
            status="RESERVED",
        )
        db_session.add(res2)

        with pytest.raises(IntegrityError):
            await db_session.flush()

        await db_session.rollback()

    async def test_non_overlapping_reservations_allowed(self, db_session: AsyncSession):
        """Non-overlapping reservations for the same vehicle must be allowed."""
        vehicle = Vehicle(
            id=uuid4(),
            registration="NOOVRL-01",
            vin="WVWZZZ3CZWENOVRL1",
            brand="Test", model="Car", year=2024,
            color="Red", fuel_type="DIESEL",
            transmission="MANUAL",
        )
        db_session.add(vehicle)
        await db_session.flush()

        now = datetime.now(timezone.utc)
        res1 = Reservation(
            id=uuid4(),
            vehicle_id=vehicle.id,
            start_datetime=now,
            end_datetime=now + timedelta(days=5),
            daily_price=300, num_days=5,
            total_price=1500, deposit=500,
        )
        db_session.add(res1)
        await db_session.flush()

        # Non-overlapping reservation (starts after first ends)
        res2 = Reservation(
            id=uuid4(),
            vehicle_id=vehicle.id,
            start_datetime=now + timedelta(days=5),
            end_datetime=now + timedelta(days=10),
            daily_price=300, num_days=5,
            total_price=1500, deposit=500,
        )
        db_session.add(res2)
        await db_session.flush()  # Should succeed

    async def test_cancelled_reservation_allows_overlap(self, db_session: AsyncSession):
        """Cancelled reservations should not block new bookings."""
        vehicle = Vehicle(
            id=uuid4(),
            registration="CANCEL-01",
            vin="WVWZZZ3CZWECANCL1",
            brand="Test", model="Car", year=2024,
            color="Red", fuel_type="DIESEL",
            transmission="MANUAL",
        )
        db_session.add(vehicle)
        await db_session.flush()

        now = datetime.now(timezone.utc)
        res1 = Reservation(
            id=uuid4(),
            vehicle_id=vehicle.id,
            start_datetime=now,
            end_datetime=now + timedelta(days=5),
            daily_price=300, num_days=5,
            total_price=1500, deposit=500,
            status="CANCELLED",
        )
        db_session.add(res1)
        await db_session.flush()

        # Overlapping but first is cancelled
        res2 = Reservation(
            id=uuid4(),
            vehicle_id=vehicle.id,
            start_datetime=now + timedelta(days=2),
            end_datetime=now + timedelta(days=7),
            daily_price=300, num_days=5,
            total_price=1500, deposit=500,
            status="RESERVED",
        )
        db_session.add(res2)
        await db_session.flush()  # Should succeed

    async def test_different_vehicles_same_period_allowed(self, db_session: AsyncSession):
        """Different vehicles can be reserved for the same period."""
        v1 = Vehicle(
            id=uuid4(), registration="DIFFV-01", vin="WVWZZZ3CZWEDIFFV1",
            brand="Test", model="A", year=2024,
            color="Red", fuel_type="DIESEL", transmission="MANUAL",
        )
        v2 = Vehicle(
            id=uuid4(), registration="DIFFV-02", vin="WVWZZZ3CZWEDIFFV2",
            brand="Test", model="B", year=2024,
            color="Blue", fuel_type="DIESEL", transmission="MANUAL",
        )
        db_session.add_all([v1, v2])
        await db_session.flush()

        now = datetime.now(timezone.utc)
        res1 = Reservation(
            id=uuid4(), vehicle_id=v1.id,
            start_datetime=now, end_datetime=now + timedelta(days=5),
            daily_price=300, num_days=5, total_price=1500, deposit=500,
        )
        res2 = Reservation(
            id=uuid4(), vehicle_id=v2.id,
            start_datetime=now, end_datetime=now + timedelta(days=5),
            daily_price=300, num_days=5, total_price=1500, deposit=500,
        )
        db_session.add_all([res1, res2])
        await db_session.flush()  # Should succeed
