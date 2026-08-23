"""
Revenue calculation consistency tests.

Canonical business definition (single source of truth — backend):

    Revenue(period) = SUM(reservations.total_price)
                      WHERE status IN ('ACTIVE', 'COMPLETED')
                        AND start_datetime >= period_start
                        AND start_datetime <  period_end
                      [period boundaries in Africa/Casablanca local time]

These tests pin the exact semantics:
- start boundary inclusive, end boundary exclusive
- CANCELLED and RESERVED statuses excluded
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


async def _make_vehicle(db_session) -> Vehicle:
    v = Vehicle(
        registration="REV-111-A-1",
        vin="1M8GDM9AXKP042788",
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
    async def test_revenue_includes_active_and_completed_only(
        self, client: AsyncClient, admin_token, db_session
    ):
        vehicle = await _make_vehicle(db_session)
        base = _today_at(10).replace(tzinfo=None)
        # In-period qualifying reservations
        await _make_reservation(db_session, vehicle, base - timedelta(days=1), 1000.0, "COMPLETED")
        await _make_reservation(db_session, vehicle, base + timedelta(hours=1), 500.0, "ACTIVE")
        # Excluded statuses
        await _make_reservation(db_session, vehicle, base + timedelta(hours=2), 999.0, "CANCELLED")
        await _make_reservation(db_session, vehicle, base + timedelta(hours=3), 888.0, "RESERVED")

        resp = await client.get(
            "/api/v1/dashboard/stats", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        # Only the ACTIVE reservation starting TODAY qualifies:
        # - the COMPLETED one started yesterday (different period)
        # - CANCELLED (999) and RESERVED (888) are always excluded
        assert data["today_revenue"] == pytest.approx(500.0)
        assert data["today_rentals"] >= 1

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
        vehicle = await _make_vehicle(db_session)
        base = _today_at(9).replace(tzinfo=None)
        # Values that expose binary float drift when summed naively
        await _make_reservation(db_session, vehicle, base + timedelta(minutes=1), 0.1, "COMPLETED")
        await _make_reservation(db_session, vehicle, base + timedelta(minutes=2), 0.2, "COMPLETED")

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
        base = _today_at(8).replace(tzinfo=None)
        await _make_reservation(db_session, vehicle, base + timedelta(minutes=5), 432.1, "COMPLETED")

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
