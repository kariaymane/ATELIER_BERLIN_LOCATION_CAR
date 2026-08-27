import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.rental_repository import RentalRepository
from app.models.reservation import Reservation
from app.models.maintenance import Maintenance
from app.models.vehicle import Vehicle

@pytest.mark.asyncio
async def test_check_availability_distinguishes_reasons(db_session: AsyncSession):
    # Setup vehicle
    v_id = uuid4()
    v = Vehicle(id=v_id, brand="Test", model="A", registration=f"TEST-{v_id.hex[:4]}", vin=f"VIN{v_id.hex[:14]}", year=2026, color="Noir", fuel_type="GASOLINE", transmission="AUTOMATIC", daily_rental_price=10)
    db_session.add(v)
    await db_session.flush()

    repo = RentalRepository(db_session)
    now = datetime.now(timezone.utc)

    # 1. No overlapping = True, None
    avail, reason = await repo.check_availability(v_id, now, now + timedelta(days=1))
    assert avail is True
    assert reason is None

    # 2. Overlapping Reservation = False, "RESERVATION"
    r = Reservation(
        id=uuid4(), vehicle_id=v_id, status="ACTIVE",
        start_datetime=now, end_datetime=now + timedelta(days=1),
        customer_name="Test", customer_phone="123", customer_email="test@test.com",
        identity_card_image="", driving_license_image="", daily_price=10, num_days=1, total_price=10, deposit=0
    )
    db_session.add(r)
    await db_session.flush()

    avail, reason = await repo.check_availability(v_id, now, now + timedelta(days=1))
    assert avail is False
    assert reason == "RESERVATION"

    # Cleanup reservation
    await db_session.delete(r)
    await db_session.flush()

    # 3. Overlapping Maintenance = False, "MAINTENANCE"
    m = Maintenance(
        id=uuid4(), vehicle_id=v_id, status="IN_PROGRESS",
        start_datetime=now - timedelta(days=1),
        expected_end_datetime=now + timedelta(days=1),
        type="PREVENTIVE"
    )
    db_session.add(m)
    await db_session.flush()

    avail, reason = await repo.check_availability(v_id, now, now + timedelta(days=1))
    assert avail is False
    assert reason == "MAINTENANCE"

    # 4. Exclude ID functionality
    # First verify it blocks when not excluded
    r2 = Reservation(
        id=uuid4(), vehicle_id=v_id, status="RESERVED",
        start_datetime=now + timedelta(days=5), end_datetime=now + timedelta(days=6),
        customer_name="Test", customer_phone="123", customer_email="test@test.com",
        identity_card_image="", driving_license_image="", daily_price=10, num_days=1, total_price=10, deposit=0
    )
    db_session.add(r2)
    await db_session.flush()

    avail, reason = await repo.check_availability(v_id, now + timedelta(days=5), now + timedelta(days=6))
    assert avail is False
    assert reason == "RESERVATION"

    avail, reason = await repo.check_availability(v_id, now + timedelta(days=5), now + timedelta(days=6), exclude_id=r2.id)
    assert avail is True
    assert reason is None

