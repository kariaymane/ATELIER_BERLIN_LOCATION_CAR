"""Mandatory tests for Phase 3 (P1-2): Maintenance over Active Rental & Revenue Protection.

Verifies:
1. ACTIVE rental + overlapping maintenance without confirmation yields 409 Conflict.
2. ACTIVE rental + overlapping maintenance with confirmation preserves realised revenue for days elapsed.
3. RESERVED rental + overlapping maintenance cancels without error (and yields 0 revenue).
4. Future maintenance + future reservation cancels correctly without affecting past revenue.
5. Maintenance ending before rental starts does not touch the rental.
6. Maintenance starting after rental ends does not touch the rental.
"""
from datetime import datetime, timedelta
from decimal import Decimal
import pytest
from httpx import AsyncClient
from zoneinfo import ZoneInfo

from app.models.vehicle import Vehicle
from app.models.reservation import Reservation
from app.services.revenue_service import revenue_between

TZ = ZoneInfo("Africa/Casablanca")


async def _make_vehicle(db, status="AVAILABLE"):
    import uuid
    v = Vehicle(
        id=uuid.uuid4(),
        brand="Dacia",
        model="Logan",
        year=2023,
        color="Blanc",
        fuel_type="DIESEL",
        transmission="MANUAL",
        registration=f"MA-{uuid.uuid4().hex[:6]}",
        vin=f"VIN{uuid.uuid4().hex[:14].upper()}",
        status=status,
        daily_rental_price=Decimal("300.00"),
    )
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return v


@pytest.mark.asyncio
async def test_active_rental_overlapping_maintenance_requires_confirmation(client: AsyncClient, admin_token, db_session):
    """An operator scheduling maintenance that overlaps an active rental must confirm interruption."""
    now = datetime.now(TZ)
    v = await _make_vehicle(db_session, status="RENTED")

    # Active rental: started 2 days ago, ends 3 days in future (5 days total)
    res = Reservation(
        vehicle_id=v.id,
        customer_name="Client Actif",
        start_datetime=now - timedelta(days=2),
        end_datetime=now + timedelta(days=3),
        daily_price=Decimal("300.00"),
        num_days=5,
        total_price=Decimal("1500.00"),
        deposit=0,
        status="ACTIVE",
        payment_status="PAID",
    )
    db_session.add(res)
    await db_session.commit()

    headers = {"Authorization": f"Bearer {admin_token}"}
    maint_payload = {
        "vehicle_id": str(v.id),
        "type": "MÉCANIQUE",
        "title": "Panne Moteur",
        "start_datetime": now.isoformat(),
        "expected_end_datetime": (now + timedelta(days=2)).isoformat(),
        "confirm_interruption": False,
    }

    # Should raise 409 Conflict because rental is active
    resp = await client.post("/api/v1/maintenance", json=maint_payload, headers=headers)
    assert resp.status_code == 409
    assert "active in-progress rental" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_active_rental_overlapping_maintenance_preserves_realised_revenue(client: AsyncClient, admin_token, db_session):
    """When confirmed, active rental is interrupted, but revenue for days already elapsed is PRESERVED."""
    now = datetime.now(TZ)
    v = await _make_vehicle(db_session, status="RENTED")

    # Started 3 days ago (elapsed 3 days), scheduled for 10 days @ 300 = 3000
    start = now - timedelta(days=3)
    res = Reservation(
        vehicle_id=v.id,
        customer_name="Client Protégé",
        start_datetime=start,
        end_datetime=now + timedelta(days=7),
        daily_price=Decimal("300.00"),
        num_days=10,
        total_price=Decimal("3000.00"),
        deposit=0,
        status="ACTIVE",
        payment_status="PAID",
    )
    db_session.add(res)
    await db_session.commit()

    # Pre-check revenue before maintenance
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = month_start + timedelta(days=32)
    pre_rev = await revenue_between(db_session, month_start, month_end, now=now)
    assert pre_rev["revenue"] >= 900.0  # At least 3 days realised @ 300 = 900

    headers = {"Authorization": f"Bearer {admin_token}"}
    maint_payload = {
        "vehicle_id": str(v.id),
        "type": "RÉVISION",
        "title": "Révision Urgente",
        "start_datetime": now.isoformat(),
        "expected_end_datetime": (now + timedelta(days=2)).isoformat(),
        "confirm_interruption": True,
    }

    resp = await client.post("/api/v1/maintenance", json=maint_payload, headers=headers)
    assert resp.status_code in (200, 201)

    # Re-fetch reservation
    await db_session.refresh(res)
    assert res.status == "CANCELLED"
    assert res.cancellation_reason == "MAINTENANCE"

    # Post-check revenue: MUST NOT DROP TO ZERO!
    post_rev = await revenue_between(db_session, month_start, month_end, now=now)
    assert post_rev["revenue"] >= 900.0, "Revenue for elapsed days MUST be preserved upon maintenance cancellation!"


@pytest.mark.asyncio
async def test_reserved_rental_cancelled_by_maintenance_contributes_zero(client: AsyncClient, admin_token, db_session):
    """A future RESERVED rental overlapping maintenance is cancelled and contributes zero revenue."""
    now = datetime.now(TZ)
    v = await _make_vehicle(db_session, status="AVAILABLE")

    future_start = now + timedelta(days=2)
    res = Reservation(
        vehicle_id=v.id,
        customer_name="Client Futur",
        start_datetime=future_start,
        end_datetime=future_start + timedelta(days=5),
        daily_price=Decimal("400.00"),
        num_days=5,
        total_price=Decimal("2000.00"),
        deposit=0,
        status="RESERVED",
        payment_status="PENDING",
    )
    db_session.add(res)
    await db_session.commit()

    headers = {"Authorization": f"Bearer {admin_token}"}
    maint_payload = {
        "vehicle_id": str(v.id),
        "type": "ENTRETIEN",
        "start_datetime": (now + timedelta(days=1)).isoformat(),
        "expected_end_datetime": (now + timedelta(days=4)).isoformat(),
    }

    resp = await client.post("/api/v1/maintenance", json=maint_payload, headers=headers)
    assert resp.status_code in (200, 201)

    await db_session.refresh(res)
    assert res.status == "CANCELLED"
    assert res.cancellation_reason == "MAINTENANCE"

    # Revenue for future cancelled booking is 0
    post_rev = await revenue_between(db_session, now, now + timedelta(days=10), now=now)
    assert post_rev["revenue"] == 0.0


@pytest.mark.asyncio
async def test_non_overlapping_maintenance_boundaries_preserve_rental(client: AsyncClient, admin_token, db_session):
    """Maintenance ending before or starting after a rental does NOT touch the rental."""
    now = datetime.now(TZ)
    v = await _make_vehicle(db_session, status="AVAILABLE")

    r_start = now + timedelta(days=5)
    r_end = now + timedelta(days=10)
    res = Reservation(
        vehicle_id=v.id,
        customer_name="Client Non Affecté",
        start_datetime=r_start,
        end_datetime=r_end,
        daily_price=Decimal("250.00"),
        num_days=5,
        total_price=Decimal("1250.00"),
        deposit=0,
        status="RESERVED",
        payment_status="PAID",
    )
    db_session.add(res)
    await db_session.commit()

    headers = {"Authorization": f"Bearer {admin_token}"}

    # Case A: Maintenance ends before rental starts [now+1, now+3) vs [now+5, now+10)
    maint1 = {
        "vehicle_id": str(v.id),
        "type": "VIDANGE",
        "start_datetime": (now + timedelta(days=1)).isoformat(),
        "expected_end_datetime": (now + timedelta(days=3)).isoformat(),
    }
    resp1 = await client.post("/api/v1/maintenance", json=maint1, headers=headers)
    assert resp1.status_code in (200, 201)

    await db_session.refresh(res)
    assert res.status == "RESERVED"  # untouched

    # Case B: Maintenance starts after rental ends [now+12, now+15)
    maint2 = {
        "vehicle_id": str(v.id),
        "type": "PNEUS",
        "start_datetime": (now + timedelta(days=12)).isoformat(),
        "expected_end_datetime": (now + timedelta(days=15)).isoformat(),
    }
    resp2 = await client.post("/api/v1/maintenance", json=maint2, headers=headers)
    assert resp2.status_code in (200, 201)

    await db_session.refresh(res)
    assert res.status == "RESERVED"  # untouched
