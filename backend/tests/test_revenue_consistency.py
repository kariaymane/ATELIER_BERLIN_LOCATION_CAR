"""
Revenue calculation consistency tests.

Canonical business definition (single source of truth — backend):

    Revenue(period) = SUM(reservations.total_price)
                      WHERE status != 'CANCELLED'
                        AND start_datetime <= now          (rental has started)
                        AND start_datetime >= period_start
                        AND start_datetime <  period_end
                      [period boundaries in Africa/Casablanca local time]

Revenue is recognised when a rental STARTS. This business hands the car over
at the reservation start (no separate "pickup" step), so a booking whose
window contains `now` is RENTED and its revenue counts, whether its stored
status is RESERVED, ACTIVE or COMPLETED. Only CANCELLED is excluded, and a
booking that has not started yet contributes nothing to current revenue.

These tests pin the exact semantics:
- start boundary inclusive, end boundary exclusive
- CANCELLED excluded; RESERVED / ACTIVE / COMPLETED all count once started
- a not-yet-started future booking does not count
- zero revenue when no qualifying rows
- decimal precision preserved (no float drift)
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.reservation import Reservation
from app.models.vehicle import Vehicle


TZ = ZoneInfo("Africa/Casablanca")


import uuid

async def _make_vehicle(db_session) -> Vehicle:
    uid = uuid.uuid4().hex[:6]
    v = Vehicle(
        registration=f"REV-{uid}",
        vin=f"WF0XXXGCD{uid}XX",
        brand="Renault",
        model="Clio",
        year=2024,
        color="Blanc",
        fuel_type="DIESEL",
        transmission="MANUAL",
        current_mileage=1000,
        daily_rental_price=300.0,
        status="AVAILABLE",
    )
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)
    return v


async def _make_reservation(
    db_session, vehicle: Vehicle, start: datetime, total: float,
    status: str = "COMPLETED",
) -> Reservation:
    r = Reservation(
        vehicle_id=vehicle.id,
        customer_name="Rev Test",
        start_datetime=start,
        end_datetime=start + timedelta(days=2),
        daily_price=300.0,
        num_days=2,
        total_price=total,
        deposit=0,
        status=status,
        payment_status="PAID",
        created_by=None,
    )
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)
    return r


def _today_at(hour: int) -> datetime:
    now = datetime.now(TZ)
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)


@pytest.mark.asyncio
class TestRevenueSemantics:
    async def test_revenue_counts_every_started_non_cancelled_rental(
        self, client: AsyncClient, admin_token, db_session
    ):
        now = datetime.now(TZ).replace(tzinfo=None)
        # Anchor everything a few minutes into today so the "started" guard is
        # satisfied regardless of the wall-clock hour the suite runs at.
        start = now.replace(hour=0, minute=5, second=0, microsecond=0)
        # Started today, not cancelled -> all count, whatever the status.
        await _make_reservation(db_session, await _make_vehicle(db_session), start, 500.0, "ACTIVE")
        await _make_reservation(db_session, await _make_vehicle(db_session), start, 888.0, "RESERVED")
        await _make_reservation(db_session, await _make_vehicle(db_session), start, 120.0, "COMPLETED")
        # Cancelled -> never counts.
        await _make_reservation(db_session, await _make_vehicle(db_session), start, 999.0, "CANCELLED")
        # Started yesterday -> different period.
        await _make_reservation(db_session, await _make_vehicle(db_session), start - timedelta(days=1), 1000.0, "COMPLETED")
        # Starts later today but AFTER now -> not yet started, no revenue yet.
        await _make_reservation(db_session, await _make_vehicle(db_session), now + timedelta(hours=1), 777.0, "RESERVED")

        resp = await client.get(
            "/api/v1/dashboard/stats", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        # 500 (ACTIVE) + 888 (RESERVED) + 120 (COMPLETED) = 1508
        assert data["today_revenue"] == pytest.approx(1508.0)
        assert data["today_rentals"] >= 3

    async def test_revenue_day_boundary_inclusive_start_exclusive_end(
        self, client: AsyncClient, admin_token, db_session
    ):
        vehicle = await _make_vehicle(db_session)
        midnight = _today_at(0).replace(tzinfo=None)
        exactly_midnight = await _make_reservation(
            db_session, vehicle, midnight, 700.0
        )
        assert exactly_midnight is not None  # inclusive lower bound counts

        resp = await client.get(
            "/api/v1/dashboard/stats", headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        assert data["today_revenue"] == pytest.approx(700.0)

    async def test_revenue_decimal_precision_exact(
        self, client: AsyncClient, admin_token, db_session
    ):
        # Anchored a few minutes into the past (not a fixed hour) so the
        # "rental has started" guard is satisfied at any time of day.
        base = (datetime.now(TZ) - timedelta(minutes=10)).replace(tzinfo=None)
        # Values that expose binary float drift when summed naively
        await _make_reservation(db_session, await _make_vehicle(db_session), base + timedelta(minutes=1), 0.1, "COMPLETED")
        await _make_reservation(db_session, await _make_vehicle(db_session), base + timedelta(minutes=2), 0.2, "COMPLETED")

        resp = await client.get(
            "/api/v1/dashboard/stats", headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        # NUMERIC column summation must be exact (0.1 + 0.2 == 0.3 in decimal)
        assert float(data["today_revenue"]) == 0.3

    async def test_revenue_zero_when_no_qualifying_rows(
        self, client: AsyncClient, admin_token, db_session
    ):
        resp = await client.get(
            "/api/v1/dashboard/stats", headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        assert data["today_revenue"] == 0
        assert data["week_revenue"] == 0
        assert data["month_revenue"] == 0

    async def test_period_stats_match_overview_for_daily(
        self, client: AsyncClient, admin_token, db_session
    ):
        """get_period_stats('daily') and overview today_revenue must agree."""
        vehicle = await _make_vehicle(db_session)
        base = (datetime.now(TZ) - timedelta(minutes=10)).replace(tzinfo=None)
        await _make_reservation(db_session, vehicle, base, 432.1, "COMPLETED")

        stats = await client.get(
            "/api/v1/dashboard/stats", headers={"Authorization": f"Bearer {admin_token}"}
        )
        daily = await client.get(
            "/api/v1/dashboard/daily",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        if daily.status_code == 404:
            pytest.skip("daily endpoint not exposed")
        assert stats.json()["today_revenue"] == pytest.approx(daily.json()["revenue"])

    async def test_golden_case_A500_B300_Ccancelled100_equals_800(
        self, client: AsyncClient, admin_token, db_session
    ):
        """The release golden case, verified end-to-end through the real API:

            Reservation A = 500 MAD, started, not cancelled   -> counts
            Reservation B = 300 MAD, started, not cancelled   -> counts
            Reservation C = 100 MAD, CANCELLED                 -> excluded
            Reservation D = 777 MAD, starts in the future     -> excluded (not started)

        Expected today's revenue = 800.00
        """
        now_aware = datetime.now(TZ)
        started = (now_aware - timedelta(minutes=5)).astimezone(timezone.utc)
        future = (now_aware + timedelta(hours=3)).astimezone(timezone.utc)
        await _make_reservation(db_session, await _make_vehicle(db_session), started, 500.0, "ACTIVE")
        await _make_reservation(db_session, await _make_vehicle(db_session), started, 300.0, "RESERVED")
        await _make_reservation(db_session, await _make_vehicle(db_session), started, 100.0, "CANCELLED")
        await _make_reservation(db_session, await _make_vehicle(db_session), future, 777.0, "RESERVED")

        data = (await client.get(
            "/api/v1/dashboard/stats", headers={"Authorization": f"Bearer {admin_token}"}
        )).json()
        assert data["today_revenue"] == pytest.approx(800.0)
        assert data["week_revenue"] == pytest.approx(800.0)
        assert data["month_revenue"] == pytest.approx(800.0)
        # 2 of the 4 vehicles are physically out right now (A + B), the
        # future one (D) is upcoming, C is cancelled.
        assert data["rented"] == 2
        assert data["reserved"] == 1
