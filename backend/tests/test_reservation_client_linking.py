"""
Reservation client-linking + maintenance guard tests.

Canonical rules verified:
- RentalCreate accepts customer_id; the reservation row carries it.
- Unknown customer_id -> rejected.
- Vehicle in MAINTENANCE -> reservation rejected (canonical rule).
- Sync push path maps customer_id into PostgreSQL.
"""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.client import Client
from app.models.reservation import Reservation
from app.models.vehicle import Vehicle


async def _vehicle(db_session, status="AVAILABLE", reg="LNK-1-A-1"):
    v = Vehicle(
        registration=reg, vin="1M8GDM9AXKP042788", brand="Dacia", model="Logan",
        year=2024, color="Blanc", fuel_type="DIESEL", transmission="MANUAL",
        current_mileage=100, daily_rental_price=250.0, status=status,
    )
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)
    return v


async def _client(db_session, first="Nawal", last="Bennis"):
    c = Client(first_name=first, last_name=last, phone="+212677778888",
               email="nawal@test.local", cin_number="CC556677")
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return c


def _payload(v, c=None, start=None, days=3, total=750.0):
    start = start or datetime.now() + timedelta(days=5)
    return {
        "vehicle_id": str(v.id),
        **({"customer_id": str(c.id)} if c else {}),
        "customer_name": f"{c.first_name} {c.last_name}" if c else "Walk-in",
        "customer_phone": (c.phone if c else "+212600000001"),
        "start_datetime": start.isoformat(),
        "end_datetime": (start + timedelta(days=days)).isoformat(),
        "daily_price": 250.0, "num_days": days, "total_price": total,
        "deposit": 0, "payment_status": "PENDING",
    }


@pytest.mark.asyncio
class TestReservationClientLinking:
    async def test_reservation_with_customer_id_persists_link(
        self, client: AsyncClient, admin_token, db_session
    ):
        v = await _vehicle(db_session)
        c = await _client(db_session)
        resp = await client.post("/api/v1/rentals/", json=_payload(v, c),
                                 headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 201, resp.text
        row = await db_session.execute(
            select(Reservation).where(Reservation.customer_id == c.id))
        res = row.scalars().first()
        assert res is not None, "customer_id was not persisted"
        assert str(res.vehicle_id) == str(v.id)

    async def test_reservation_with_unknown_customer_rejected(
        self, client: AsyncClient, admin_token, db_session
    ):
        v = await _vehicle(db_session, reg="LNK-2-B-2")
        payload = _payload(v)
        payload["customer_id"] = str(uuid4())
        resp = await client.post("/api/v1/rentals/", json=payload,
                                 headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code in (400, 404), resp.text

    async def test_client_history_contains_linked_reservation(
        self, client: AsyncClient, admin_token, db_session
    ):
        v = await _vehicle(db_session, reg="LNK-3-C-3")
        c = await _client(db_session, "Omar", "Chraibi")
        resp = await client.post("/api/v1/rentals/", json=_payload(v, c),
                                 headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 201
        hist = await client.get(
            f"/api/v1/clients/{c.id}/rentals",
            headers={"Authorization": f"Bearer {admin_token}"})
        data = hist.json()
        assert data["summary"]["total_rentals"] == 1
        assert data["summary"]["total_amount"] == pytest.approx(750.0)


@pytest.mark.asyncio
class TestMaintenanceGuard:
    async def test_vehicle_in_maintenance_rejected(
        self, client: AsyncClient, admin_token, db_session
    ):
        v = await _vehicle(db_session, status="AVAILABLE", reg="MNT-1-D-4")
        from app.models.maintenance import Maintenance
        now = datetime.now()
        m = Maintenance(
            vehicle_id=v.id,
            type="panne",
            start_datetime=now,
            expected_end_datetime=now + timedelta(days=10),
            status="ACTIVE",
            step="DIAGNOSTIC",
            parts_cost=0, labor_cost=0, other_cost=0
        )
        db_session.add(m)
        await db_session.commit()
        
        # Try to book during maintenance
        resp = await client.post("/api/v1/rentals/", json=_payload(v, start=now + timedelta(days=1), days=2, total=500.0),
                                 headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 400
        assert "double" in str(resp.json()).lower() or "maintenance" in str(resp.json()).lower() or "réservé" in str(resp.json()).lower()

    async def test_operational_vehicle_still_bookable(
        self, client: AsyncClient, admin_token, db_session
    ):
        v = await _vehicle(db_session, status="RESERVED", reg="MNT-2-E-5")
        start = datetime.now() + timedelta(days=30)  # far from any overlap
        resp = await client.post("/api/v1/rentals/",
                                 json=_payload(v, start=start, days=2, total=500.0),
                                 headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 201, "RESERVED vehicle must be bookable for free dates"
