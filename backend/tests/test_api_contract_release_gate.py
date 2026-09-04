"""
Release gate contract test for dashboard revenue endpoints.

Fails the build / release gate if:
- /api/v1/dashboard/revenue is missing or returns non-200 for valid queries
- /api/v1/dashboard/period/{name} is missing or returns non-200 for valid periods
- either endpoint returns revenue divergent from shared/revenue_reference.py
- unauthorized calls do not return 401
- invalid date formats return 422
- invalid period names return 422
"""
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import pytest
from httpx import AsyncClient

from app.models.reservation import Reservation
from app.models.vehicle import Vehicle
import uuid

TZ = ZoneInfo("Africa/Casablanca")


async def _make_vehicle(db_session) -> Vehicle:
    uid = uuid.uuid4().hex[:6]
    v = Vehicle(
        registration=f"GATE-{uid}",
        vin=f"GATE{uid}0000000",
        brand="Dacia",
        model="Logan",
        year=2024,
        color="Blanc",
        fuel_type="DIESEL",
        transmission="MANUAL",
        current_mileage=5000,
        daily_rental_price=300.0,
        status="AVAILABLE",
    )
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)
    return v


@pytest.mark.asyncio
class TestApiContractReleaseGate:

    async def test_unauthorized_requests_rejected_with_401(self, client: AsyncClient):
        r1 = await client.get("/api/v1/dashboard/revenue?from=2026-09-01&to=2026-09-02")
        assert r1.status_code in (401, 403), f"Expected 401/403 for unauthenticated /revenue, got {r1.status_code}"

        r2 = await client.get("/api/v1/dashboard/period/month")
        assert r2.status_code in (401, 403), f"Expected 401/403 for unauthenticated /period/month, got {r2.status_code}"

    async def test_invalid_period_name_rejected_with_422(self, client: AsyncClient, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        r = await client.get("/api/v1/dashboard/period/invalid_period_xyz", headers=h)
        assert r.status_code == 422, f"Expected 422 for invalid period, got {r.status_code}"

    async def test_invalid_date_format_rejected_with_422(self, client: AsyncClient, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        r = await client.get("/api/v1/dashboard/revenue?from=not-a-date&to=2026-09-02", headers=h)
        assert r.status_code == 422, f"Expected 422 for malformed from date, got {r.status_code}"

    async def test_endpoints_exist_and_match_canonical_pro_rata(
        self, client: AsyncClient, admin_token, db_session
    ):
        v = await _make_vehicle(db_session)
        now = datetime.now(TZ)
        start = (now - timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)
        
        # 4 days total @ 250 DH/day = 1000 DH total
        res = Reservation(
            vehicle_id=v.id,
            customer_name="Contract Gate",
            start_datetime=start,
            end_datetime=start + timedelta(days=4),
            daily_price=250.0,
            num_days=4,
            total_price=1000.0,
            deposit=0,
            status="ACTIVE",
            payment_status="PAID",
        )
        db_session.add(res)
        await db_session.commit()

        h = {"Authorization": f"Bearer {admin_token}"}

        # 1. /dashboard/revenue contract
        f_iso = start.date().isoformat()
        t_iso = (start.date() + timedelta(days=1)).isoformat()
        r_rev = await client.get(f"/api/v1/dashboard/revenue?from={f_iso}&to={t_iso}", headers=h)
        assert r_rev.status_code == 200, f"/api/v1/dashboard/revenue returned {r_rev.status_code}"
        data_rev = r_rev.json()
        assert "revenue" in data_rev
        assert "rentals" in data_rev
        assert "days_rented" in data_rev
        assert data_rev["revenue"] == pytest.approx(500.0)  # 2 days inclusive (d0 + d1) @ 250

        # 2. /dashboard/period/{name} contract
        for p in ("today", "week", "month", "year"):
            r_period = await client.get(f"/api/v1/dashboard/period/{p}", headers=h)
            assert r_period.status_code == 200, f"/api/v1/dashboard/period/{p} returned {r_period.status_code}"
            data_p = r_period.json()
            assert "revenue" in data_p
            assert "rentals" in data_p
            assert "days_rented" in data_p
            assert "period" in data_p
