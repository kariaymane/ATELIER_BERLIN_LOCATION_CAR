"""Regression: completing / finishing a maintenance ticket must return the
vehicle to AVAILABLE so it becomes bookable again everywhere.

A regression had left `complete` / `advance-step` no-ops, so a vehicle stayed
flagged MAINTENANCE forever once a ticket was opened.
"""
import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.models.maintenance import Maintenance


async def _mk_vehicle(db, status="AVAILABLE"):
    v_id = uuid4()
    v = Vehicle(
        id=v_id, brand="T", model="A", registration=f"M-{v_id.hex[:5]}",
        vin=f"VIN{v_id.hex[:14]}", year=2026, color="Noir",
        fuel_type="GASOLINE", transmission="AUTOMATIC", daily_rental_price=10,
        status=status,
    )
    db.add(v)
    await db.commit()
    return v_id


@pytest.mark.asyncio
async def test_complete_endpoint_frees_vehicle(client, db_session: AsyncSession, admin_token):
    v_id = await _mk_vehicle(db_session)
    now = datetime.now(timezone.utc)
    m = Maintenance(
        id=uuid4(), vehicle_id=v_id, status="ACTIVE", type="PREVENTIVE",
        start_datetime=now - timedelta(hours=1),
        expected_end_datetime=now + timedelta(hours=1),
    )
    db_session.add(m)
    # mirror production: opening a ticket flags the vehicle
    v = await db_session.get(Vehicle, v_id)
    v.status = "MAINTENANCE"
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/maintenance/{m.id}/complete",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text

    fresh = await db_session.execute(select(Vehicle.status).where(Vehicle.id == v_id))
    assert fresh.scalar_one() == "AVAILABLE"


@pytest.mark.asyncio
async def test_stale_maintenance_flag_does_not_block_booking(db_session: AsyncSession):
    """Root Cause #4: a persisted vehicle.status == 'MAINTENANCE' with NO
    active maintenance record must NOT hard-block availability — the schedule
    check is authoritative."""
    from app.repositories.rental_repository import RentalRepository

    v_id = await _mk_vehicle(db_session, status="MAINTENANCE")  # stale flag, no ticket
    now = datetime.now(timezone.utc)
    repo = RentalRepository(db_session)
    available, reason = await repo.check_availability(v_id, now, now + timedelta(days=1))
    assert available is True and reason is None


@pytest.mark.asyncio
async def test_sold_still_blocks_booking(db_session: AsyncSession):
    from app.repositories.rental_repository import RentalRepository

    v_id = await _mk_vehicle(db_session, status="SOLD")
    now = datetime.now(timezone.utc)
    repo = RentalRepository(db_session)
    available, reason = await repo.check_availability(v_id, now, now + timedelta(days=1))
    assert available is False and reason == "SOLD"


@pytest.mark.asyncio
async def test_complete_preserves_sold_status(client, db_session: AsyncSession, admin_token):
    v_id = await _mk_vehicle(db_session, status="SOLD")
    now = datetime.now(timezone.utc)
    m = Maintenance(
        id=uuid4(), vehicle_id=v_id, status="ACTIVE", type="PREVENTIVE",
        start_datetime=now - timedelta(hours=1),
        expected_end_datetime=now + timedelta(hours=1),
    )
    db_session.add(m)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/maintenance/{m.id}/complete",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text

    fresh = await db_session.execute(select(Vehicle.status).where(Vehicle.id == v_id))
    assert fresh.scalar_one() == "SOLD"
