"""
Client rental report — canonical business rule tests.

Controlled dataset (from the release spec):

  Client A:
    Rental 1: Vehicle A, 3 days, 300  (COMPLETED)
    Rental 2: Vehicle B, 5 days, 500  (ACTIVE)
    Rental 3: Vehicle A, 2 days, 200  (COMPLETED)

  Expected under the project business rule:
    Total rentals = 3
    Total days    = 10
    Total amount  = 1000
    Vehicles      = 2
    Vehicle A     = 2 rentals / 5 days
    Vehicle B     = 1 rental / 5 days

Plus boundary rules:
  - CANCELLED rentals are reported but excluded from totals
  - same-day rental counts as num_days >= 1 (server-stored duration)
  - zero-rental client -> all-zero summary
  - unauthorized access rejected
"""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.client import Client
from app.models.reservation import Reservation
from app.models.vehicle import Vehicle


async def _seed(db_session):
    client = Client(
        id=uuid4(), first_name="Amina", last_name="Rachidi",
        phone="+212600000001", email="amina@example.test",
        cin_number="BE100001",
    )
    va = Vehicle(
        registration="AAA-1-A-1", vin="1M8GDM9AXKP042788", brand="Dacia",
        model="Logan", year=2024, color="Blanc", fuel_type="DIESEL",
        transmission="MANUAL", current_mileage=1000,
        daily_rental_price=100.0, status="AVAILABLE",
    )
    vb = Vehicle(
        registration="BBB-2-B-2", vin="1M8GDM9AXKP042789", brand="Renault",
        model="Clio", year=2023, color="Gris", fuel_type="ESSENCE" if False else "GASOLINE",
        transmission="MANUAL", current_mileage=2000,
        daily_rental_price=100.0, status="AVAILABLE",
    )
    db_session.add_all([client, va, vb])
    await db_session.commit()
    for o in (client, va, vb):
        await db_session.refresh(o)

    base = datetime(2026, 6, 1, 10, 0, 0)
    rows = [
        # (vehicle, start, num_days, total, status)
        (va.id, base, 3, 300.00, "COMPLETED"),
        (vb.id, base + timedelta(days=10), 5, 500.00, "ACTIVE"),
        (va.id, base + timedelta(days=30), 2, 200.00, "COMPLETED"),
        (va.id, base + timedelta(days=40), 4, 400.00, "CANCELLED"),  # excluded
    ]
    for vid, start, days, total, status in rows:
        db_session.add(Reservation(
            vehicle_id=vid, customer_id=client.id,
            customer_name="Amina Rachidi", customer_phone="+212600000001",
            start_datetime=start, end_datetime=start + timedelta(days=days),
            daily_price=100.0, num_days=days, total_price=total,
            deposit=0, status=status, payment_status="PENDING",
        ))
    await db_session.commit()
    return client


@pytest.mark.asyncio
class TestClientRentalsReport:
    async def test_canonical_summary_and_breakdown(self, client: AsyncClient, admin_token, db_session):
        c = await _seed(db_session)
        resp = await client.get(
            f"/api/v1/clients/{c.id}/rentals",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()

        s = data["summary"]
        assert s["total_rentals"] == 3
        assert s["total_days"] == 10
        assert s["total_amount"] == pytest.approx(1000.0)
        assert s["active_rentals"] == 1
        assert s["completed_rentals"] == 2
        assert s["cancelled_rentals"] == 1
        assert s["vehicles_rented"] == 2

        by_reg = {v["registration"]: v for v in data["vehicles"]}
        assert by_reg["AAA-1-A-1"]["rentals"] == 2
        assert by_reg["AAA-1-A-1"]["days"] == 5
        assert by_reg["BBB-2-B-2"]["rentals"] == 1
        assert by_reg["BBB-2-B-2"]["days"] == 5

        assert len(data["rentals"]) == 4  # cancelled still listed as history row
        first = data["rentals"][0]  # ordered by start desc
        assert first["status"] == "CANCELLED"
        assert first["vehicle_registration"] == "AAA-1-A-1"
        assert first["num_days"] == 4

    async def test_same_day_rental_counts_one_day(self, client: AsyncClient, admin_token, db_session):
        c = Client(first_name="Same", last_name="Day", phone="+212600000002")
        v = Vehicle(
            registration="SAME-1-A-1", vin="1M8GDM9AXKP042790", brand="Kia",
            model="Rio", year=2024, color="Rouge", fuel_type="GASOLINE",
            transmission="MANUAL", current_mileage=500,
            daily_rental_price=200.0, status="AVAILABLE",
        )
        db_session.add_all([c, v])
        await db_session.commit()
        await db_session.refresh(c)
        await db_session.refresh(v)
        start = datetime(2026, 7, 1, 9, 0, 0)
        db_session.add(Reservation(
            vehicle_id=v.id, customer_id=c.id, customer_name="Same Day",
            start_datetime=start, end_datetime=start.replace(hour=18),
            daily_price=200.0, num_days=1, total_price=200.0,
            deposit=0, status="COMPLETED", payment_status="PAID",
        ))
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/clients/{c.id}/rentals",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        s = resp.json()["summary"]
        assert s["total_rentals"] == 1
        assert s["total_days"] == 1
        assert s["total_amount"] == pytest.approx(200.0)

    async def test_zero_rental_client_all_zero(self, client: AsyncClient, admin_token, db_session):
        c = Client(first_name="Zero", last_name="Rent", phone="+212600000003")
        db_session.add(c)
        await db_session.commit()
        await db_session.refresh(c)
        resp = await client.get(
            f"/api/v1/clients/{c.id}/rentals",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        s = resp.json()["summary"]
        assert s == {
            "total_rentals": 0, "total_days": 0, "total_amount": 0.0,
            "active_rentals": 0, "completed_rentals": 0,
            "cancelled_rentals": 0, "vehicles_rented": 0,
        }

    async def test_nonexistent_client_404(self, client: AsyncClient, admin_token):
        resp = await client.get(
            f"/api/v1/clients/{uuid4()}/rentals",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    async def test_unauthorized_rejected(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/clients/{uuid4()}/rentals")
        assert resp.status_code in (401, 403)

    async def test_invalid_uuid_rejected(self, client: AsyncClient, admin_token):
        resp = await client.get(
            "/api/v1/clients/not-a-uuid/rentals",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422
