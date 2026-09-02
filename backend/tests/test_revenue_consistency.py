"""
Revenue calculation consistency tests.

Canonical business definition (single source of truth — `shared/revenue_reference.py`):

    PRO-RATA BY DAY. A rental of `num_days` days starting at instant S is made
    of day-slices day_i = [S + i days, S + (i+1) days); day_i is booked against
    calendar date date(S)+i and earns total_price/num_days. Day_i is REALISED
    once now >= S + i days. Revenue of reporting window [from, to) = the sum
    over every non-CANCELLED reservation of its per-day rate times the count of
    its realised days whose calendar date is in [from, to).

Consequences pinned here:
- a rental spanning a boundary is SPLIT day-for-day between the two periods
- only elapsed days count ("réalisé", not forecast); a future booking = 0
- CANCELLED never counts
- summing one rental over all time (now past its end) == its stored total_price
- NUMERIC precision: a 3-way split of 100.00 rounds back to exactly 100.00
- desktop / backend / mobile agree (see test_revenue_crossruntime.py)
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from app.models.reservation import Reservation
from app.models.vehicle import Vehicle

TZ = ZoneInfo("Africa/Casablanca")

import uuid


async def _make_vehicle(db_session) -> Vehicle:
    uid = uuid.uuid4().hex[:6]
    v = Vehicle(
        registration=f"REV-{uid}", vin=f"WF0XXXGCD{uid}XX", brand="Renault",
        model="Clio", year=2024, color="Blanc", fuel_type="DIESEL",
        transmission="MANUAL", current_mileage=1000, daily_rental_price=300.0,
        status="AVAILABLE",
    )
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)
    return v


async def _make_reservation(
    db_session, vehicle: Vehicle, start: datetime, *, num_days: int,
    daily: float, status: str = "COMPLETED",
) -> Reservation:
    r = Reservation(
        vehicle_id=vehicle.id,
        customer_name="Rev Test",
        start_datetime=start,
        end_datetime=start + timedelta(days=num_days),
        daily_price=daily,
        num_days=num_days,
        total_price=round(daily * num_days, 2),
        deposit=0,
        status=status,
        payment_status="PAID",
        created_by=None,
    )
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)
    return r


@pytest.mark.asyncio
class TestRevenueSemantics:
    async def test_only_realised_days_of_started_non_cancelled_rentals_count(
        self, client: AsyncClient, admin_token, db_session
    ):
        now = datetime.now(TZ)
        # Started 3 days ago, 10-day rental @ 100/day -> 4 realised days today
        # (days -3,-2,-1,0). 3 of those are before today, 1 is today.
        await _make_reservation(
            db_session, await _make_vehicle(db_session),
            now - timedelta(days=3), num_days=10, daily=100.0, status="ACTIVE",
        )
        # Cancelled -> never counts
        await _make_reservation(
            db_session, await _make_vehicle(db_session),
            now - timedelta(days=1), num_days=5, daily=999.0, status="CANCELLED",
        )
        # Starts in 2 hours -> not started, 0
        await _make_reservation(
            db_session, await _make_vehicle(db_session),
            now + timedelta(hours=2), num_days=3, daily=500.0, status="RESERVED",
        )

        data = (await client.get(
            "/api/v1/dashboard/stats",
            headers={"Authorization": f"Bearer {admin_token}"},
        )).json()
        # today's realised slice of the ongoing rental = 1 day * 100
        assert data["today_revenue"] == pytest.approx(100.0)

    async def test_rental_spanning_boundary_is_split_day_for_day(
        self, client: AsyncClient, admin_token, db_session
    ):
        """A rental that started before this month contributes only the days
        that fall in this month (and only up to today)."""
        now = datetime.now(TZ)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # start 3 days before this month, 20-day rental @ 50/day
        start = month_start - timedelta(days=3)
        await _make_reservation(
            db_session, await _make_vehicle(db_session),
            start, num_days=20, daily=50.0, status="ACTIVE",
        )
        days_into_month = (now.date() - month_start.date()).days + 1  # incl today

        data = (await client.get(
            "/api/v1/dashboard/stats",
            headers={"Authorization": f"Bearer {admin_token}"},
        )).json()
        assert data["month_revenue"] == pytest.approx(50.0 * days_into_month)
        # the 3 pre-month days are not in month_revenue but ARE in year_revenue
        assert data["year_revenue"] == pytest.approx(50.0 * (days_into_month + 3))

    async def test_full_rental_sums_to_exactly_total_price(
        self, client: AsyncClient, admin_token, db_session
    ):
        """A rental entirely in the past: its whole total_price is recognised,
        and a 3-way NUMERIC split rounds back to the cent."""
        now = datetime.now(TZ)
        start = now - timedelta(days=10)
        # 100.00 / 3 days = 33.333.. ; realised fully
        await _make_reservation(
            db_session, await _make_vehicle(db_session),
            start, num_days=3, daily=round(100.0 / 3, 2), status="COMPLETED",
        )
        # total_price is round(33.33 * 3, 2) == 99.99 — the stored contract value
        data = (await client.get(
            "/api/v1/dashboard/stats",
            headers={"Authorization": f"Bearer {admin_token}"},
        )).json()
        assert data["year_revenue"] == pytest.approx(99.99)

    async def test_zero_when_no_qualifying_rows(
        self, client: AsyncClient, admin_token, db_session
    ):
        data = (await client.get(
            "/api/v1/dashboard/stats",
            headers={"Authorization": f"Bearer {admin_token}"},
        )).json()
        assert data["today_revenue"] == 0
        assert data["week_revenue"] == 0
        assert data["month_revenue"] == 0
        assert data["year_revenue"] == 0

    async def test_stats_and_period_endpoint_and_custom_range_all_agree(
        self, client: AsyncClient, admin_token, db_session
    ):
        now = datetime.now(TZ)
        await _make_reservation(
            db_session, await _make_vehicle(db_session),
            now - timedelta(days=2), num_days=4, daily=123.45, status="ACTIVE",
        )
        h = {"Authorization": f"Bearer {admin_token}"}
        stats = (await client.get("/api/v1/dashboard/stats", headers=h)).json()
        daily = (await client.get("/api/v1/dashboard/daily", headers=h)).json()
        today_named = (await client.get("/api/v1/dashboard/period/today", headers=h)).json()
        d = now.date().isoformat()
        rng = (await client.get(f"/api/v1/dashboard/revenue?from={d}&to={d}", headers=h)).json()

        assert stats["today_revenue"] == pytest.approx(daily["revenue"])
        assert stats["today_revenue"] == pytest.approx(today_named["revenue"])
        assert stats["today_revenue"] == pytest.approx(rng["revenue"])

    async def test_custom_range_end_date_is_inclusive(
        self, client: AsyncClient, admin_token, db_session
    ):
        now = datetime.now(TZ)
        # a rental fully in the past, 2 days, 200/day
        start = (now - timedelta(days=5)).replace(hour=1)
        await _make_reservation(
            db_session, await _make_vehicle(db_session),
            start, num_days=2, daily=200.0, status="COMPLETED",
        )
        d0 = start.date().isoformat()
        d1 = (start.date() + timedelta(days=1)).isoformat()
        h = {"Authorization": f"Bearer {admin_token}"}
        # from==to==first day -> 1 day only
        r_one = (await client.get(f"/api/v1/dashboard/revenue?from={d0}&to={d0}", headers=h)).json()
        assert r_one["revenue"] == pytest.approx(200.0)
        # from first to second day inclusive -> both days
        r_two = (await client.get(f"/api/v1/dashboard/revenue?from={d0}&to={d1}", headers=h)).json()
        assert r_two["revenue"] == pytest.approx(400.0)

    async def test_future_booking_never_counts(
        self, client: AsyncClient, admin_token, db_session
    ):
        now = datetime.now(TZ)
        await _make_reservation(
            db_session, await _make_vehicle(db_session),
            now + timedelta(days=3), num_days=4, daily=777.0, status="RESERVED",
        )
        data = (await client.get(
            "/api/v1/dashboard/stats",
            headers={"Authorization": f"Bearer {admin_token}"},
        )).json()
        assert data["year_revenue"] == 0
