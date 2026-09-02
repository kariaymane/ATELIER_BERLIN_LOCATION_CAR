"""
Dashboard forensic — year-to-date revenue + "Top véhicules les plus loués".

Root cause this covers: the dashboard's today/week/month revenue cards are
legitimately 0 when nothing STARTED in that period (canonical
recognition-at-start rule), even though real rental turnover exists. The
`/dashboard/stats` response now also carries `year_revenue` / `year_rentals`
(same canonical `get_revenue_between` window) so the real figure is visible,
and `/dashboard/vehicle-performance` ranks vehicles by that same eligibility.

Isolated DB only (conftest forbids a prod DATABASE_URL). Explicit seeds:

  A  1 active rental                       -> rented == 1
  B  1 started non-cancelled rental        -> year_revenue > 0
  C  vehicle with rental history           -> appears in vehicle-performance
  D  cancelled rental                      -> excluded from revenue AND ranking
  F  several vehicles                      -> ranking sorted by revenue desc
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import uuid

import pytest
from httpx import AsyncClient

from app.models.reservation import Reservation
from app.models.vehicle import Vehicle

TZ = ZoneInfo("Africa/Casablanca")


async def _veh(db, reg):
    vin = f"WF0XXXGCD{uuid.uuid4().hex[:6]}XX"  # 17 chars, satisfies ck_vehicles_vin_length
    v = Vehicle(registration=reg, vin=vin, brand="Dacia", model="Logan",
                year=2024, color="Gris", fuel_type="DIESEL", transmission="MANUAL",
                current_mileage=100, daily_rental_price=200.0, status="AVAILABLE")
    db.add(v); await db.commit(); await db.refresh(v)
    return v


async def _res(db, veh, start, total, status="COMPLETED", days=2):
    r = Reservation(vehicle_id=veh.id, customer_name="T", start_datetime=start,
                    end_datetime=start + timedelta(days=days), daily_price=100.0,
                    num_days=days, total_price=total, deposit=0, status=status,
                    payment_status="PAID", created_by=None)
    db.add(r); await db.commit(); await db.refresh(r)
    return r


@pytest.mark.asyncio
class TestDashboardYearAndTop:

    async def test_year_revenue_present_and_canonical(self, client: AsyncClient, admin_token, db_session):
        now = datetime.now(TZ).replace(tzinfo=None)
        v1 = await _veh(db_session, "YR-1")
        v2 = await _veh(db_session, "YR-2")
        # earlier THIS year, started -> counts for the year, not this month
        await _res(db_session, v1, now.replace(month=1, day=15, hour=9), 5000.0, "COMPLETED")
        await _res(db_session, v2, now.replace(month=1, day=20, hour=9), 3000.0, "ACTIVE")
        # cancelled -> excluded (CASE D)
        await _res(db_session, v1, now.replace(month=1, day=25, hour=9), 9999.0, "CANCELLED")
        # next year -> outside the year window entirely
        await _res(db_session, v2, now.replace(year=now.year + 1, month=1, day=15, hour=9), 7777.0, "RESERVED")

        data = (await client.get("/api/v1/dashboard/stats",
                                 headers={"Authorization": f"Bearer {admin_token}"})).json()
        assert "year_revenue" in data and "year_rentals" in data
        assert data["year_revenue"] == pytest.approx(8000.0)   # 5000 + 3000
        assert data["year_rentals"] == 2
        # month card is 0 for a January-only dataset viewed later in the year
        if now.month != 1:
            assert data["month_revenue"] == pytest.approx(0.0)

    async def test_case_C_vehicle_history_appears_in_top(self, client: AsyncClient, admin_token, db_session):
        now = datetime.now(TZ).replace(tzinfo=None)
        v = await _veh(db_session, "TOP-C")
        await _res(db_session, v, now.replace(month=1, day=10, hour=9), 2500.0, "COMPLETED")

        perf = (await client.get("/api/v1/dashboard/vehicle-performance",
                                 headers={"Authorization": f"Bearer {admin_token}"})).json()
        ids = {p["vehicle_id"] for p in perf}
        assert str(v.id) in ids
        row = next(p for p in perf if p["vehicle_id"] == str(v.id))
        assert row["rental_count"] == 1
        assert row["total_revenue"] == pytest.approx(2500.0)

    async def test_case_D_cancelled_excluded_from_top(self, client: AsyncClient, admin_token, db_session):
        now = datetime.now(TZ).replace(tzinfo=None)
        v = await _veh(db_session, "TOP-D")
        await _res(db_session, v, now.replace(month=1, day=10, hour=9), 4000.0, "CANCELLED")

        perf = (await client.get("/api/v1/dashboard/vehicle-performance",
                                 headers={"Authorization": f"Bearer {admin_token}"})).json()
        assert str(v.id) not in {p["vehicle_id"] for p in perf}

    async def test_case_F_top_sorted_by_revenue_desc(self, client: AsyncClient, admin_token, db_session):
        now = datetime.now(TZ).replace(tzinfo=None)
        base = now.replace(month=1, day=5, hour=9)
        big = await _veh(db_session, "TOP-BIG")
        mid = await _veh(db_session, "TOP-MID")
        small = await _veh(db_session, "TOP-SML")
        await _res(db_session, small, base, 1000.0, "COMPLETED")
        await _res(db_session, mid, base, 3000.0, "COMPLETED")
        await _res(db_session, big, base, 9000.0, "COMPLETED")
        await _res(db_session, big, base + timedelta(days=3), 500.0, "COMPLETED")

        perf = (await client.get("/api/v1/dashboard/vehicle-performance",
                                 headers={"Authorization": f"Bearer {admin_token}"})).json()
        ordered = [p["vehicle_id"] for p in perf]
        assert ordered.index(str(big.id)) < ordered.index(str(mid.id)) < ordered.index(str(small.id))
        assert next(p for p in perf if p["vehicle_id"] == str(big.id))["rental_count"] == 2

    async def test_case_A_active_rental_counts(self, client: AsyncClient, admin_token, db_session):
        now = datetime.now(TZ).replace(tzinfo=None)
        v = await _veh(db_session, "ACT-A")
        # window covers now -> effective RENTED
        await _res(db_session, v, now - timedelta(days=1), 800.0, "ACTIVE", days=5)
        data = (await client.get("/api/v1/dashboard/stats",
                                 headers={"Authorization": f"Bearer {admin_token}"})).json()
        assert data["rented"] == 1
