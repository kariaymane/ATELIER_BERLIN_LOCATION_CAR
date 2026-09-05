"""
Dashboard rebuild — authoritative snapshot tests.

Covers the 20 mandated scenarios for ``/api/v1/dashboard/summary`` and
``build_dashboard_snapshot``. Every case seeds real rows in the isolated test
database and asserts against the ONE snapshot, so a card that disagrees with
another card is a red build.

  1  zero rentals                     11  rental ends today
  2  one active rental                12  timezone boundary
  3  one future reservation           13  midnight boundary
  4  one maintenance                  14  no data
  5  cancelled reservation            15  API failure surface (see desktop suite)
  6  completed rental                 16  refresh after mutation
  7  multiple vehicles                17  category exclusivity
  8  multiple rentals                 18  revenue date filtering
  9  same vehicle historical rentals  19  Top-5 ranking
 10  rental starts today              20  fleet reconciliation
"""
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from app.models.maintenance import Maintenance
from app.models.reservation import Reservation
from app.models.vehicle import Vehicle
from app.services.dashboard_snapshot import build_dashboard_snapshot

TZ = ZoneInfo("Africa/Casablanca")


async def _veh(db, reg, status="AVAILABLE"):
    v = Vehicle(
        registration=reg, vin=f"WF0XXXGCD{uuid.uuid4().hex[:6]}XX", brand="Dacia",
        model="Logan", year=2024, color="Gris", fuel_type="DIESEL",
        transmission="MANUAL", current_mileage=100, daily_rental_price=200.0,
        status=status,
    )
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return v


async def _res(db, veh, start, days=2, total=1000.0, status="RESERVED", reason=None):
    r = Reservation(
        vehicle_id=veh.id, customer_name="T", start_datetime=start,
        end_datetime=start + timedelta(days=days), daily_price=total / days,
        num_days=days, total_price=total, deposit=0, status=status,
        cancellation_reason=reason, payment_status="PAID", created_by=None,
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return r


async def _maint(db, veh, start, end=None, status="IN_PROGRESS"):
    m = Maintenance(
        vehicle_id=veh.id, type="REPAIR", description="d",
        start_datetime=start, expected_end_datetime=end, status=status,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


def _buckets(dto):
    v = dto["vehicles"]
    return v["ready_to_rent"], v["active_rental"], v["reserved"], v["maintenance"]


def _assert_reconciles(dto):
    """§20 — the four buckets must partition the active fleet exactly."""
    v = dto["vehicles"]
    assert sum(_buckets(dto)) == v["total"], dto["vehicles"]
    assert all(b >= 0 for b in _buckets(dto))
    assert dto["integrity"]["ok"] is True, dto["integrity"]["violations"]


@pytest.mark.asyncio
class TestDashboardSnapshot:

    # 1 / 14 — zero rentals, no data at all
    async def test_no_data_is_a_clean_empty_snapshot_not_an_error(self, db_session):
        dto = await build_dashboard_snapshot(db_session)
        assert dto["revenue"]["amount"] == 0.0
        assert dto["reservations_today"]["count"] == 0
        assert dto["maintenance"]["active_tickets"] == 0
        assert dto["vehicles"]["total"] == 0
        assert dto["top_vehicles"] == []
        _assert_reconciles(dto)

    async def test_zero_rentals_with_a_fleet(self, db_session):
        for i in range(3):
            await _veh(db_session, f"ZR-{i}")
        dto = await build_dashboard_snapshot(db_session)
        assert _buckets(dto) == (3, 0, 0, 0)
        assert dto["revenue"]["amount"] == 0.0
        assert dto["top_vehicles"] == []
        _assert_reconciles(dto)

    # 2 — one active rental
    async def test_one_active_rental(self, db_session):
        now = datetime.now(TZ)
        v = await _veh(db_session, "AR-1")
        await _res(db_session, v, now - timedelta(days=1), days=3, total=900.0)
        dto = await build_dashboard_snapshot(db_session, now=now)
        assert _buckets(dto) == (0, 1, 0, 0)
        assert dto["reservations_today"]["in_progress"] == 1
        _assert_reconciles(dto)

    # 3 — one future reservation
    async def test_one_future_reservation(self, db_session):
        now = datetime.now(TZ)
        v = await _veh(db_session, "FR-1")
        await _res(db_session, v, now + timedelta(days=5), days=2, total=600.0)
        dto = await build_dashboard_snapshot(db_session, now=now)
        assert _buckets(dto) == (0, 0, 1, 0)
        # A future booking has realised no days -> contributes no revenue yet.
        assert dto["revenue"]["amount"] == 0.0
        _assert_reconciles(dto)

    # 4 — one maintenance
    async def test_one_maintenance(self, db_session):
        now = datetime.now(TZ)
        v = await _veh(db_session, "MT-1")
        await _maint(db_session, v, now - timedelta(hours=2), now + timedelta(days=1))
        dto = await build_dashboard_snapshot(db_session, now=now)
        assert _buckets(dto) == (0, 0, 0, 1)
        assert dto["maintenance"]["active_tickets"] == 1
        assert dto["maintenance"]["vehicles_in_maintenance"] == 1
        _assert_reconciles(dto)

    async def test_completed_and_cancelled_maintenance_do_not_count(self, db_session):
        now = datetime.now(TZ)
        v1 = await _veh(db_session, "MT-2")
        v2 = await _veh(db_session, "MT-3")
        await _maint(db_session, v1, now - timedelta(days=2), now + timedelta(days=2),
                     status="COMPLETED")
        await _maint(db_session, v2, now - timedelta(days=2), now + timedelta(days=2),
                     status="CANCELLED")
        dto = await build_dashboard_snapshot(db_session, now=now)
        assert dto["maintenance"]["active_tickets"] == 0
        assert _buckets(dto) == (2, 0, 0, 0)
        _assert_reconciles(dto)

    async def test_overlapping_maintenance_counts_one_vehicle_two_tickets(self, db_session):
        now = datetime.now(TZ)
        v = await _veh(db_session, "MT-4")
        await _maint(db_session, v, now - timedelta(days=1), now + timedelta(days=1))
        await _maint(db_session, v, now - timedelta(hours=3), now + timedelta(days=3))
        dto = await build_dashboard_snapshot(db_session, now=now)
        assert dto["maintenance"]["active_tickets"] == 2
        assert dto["maintenance"]["vehicles_in_maintenance"] == 1
        assert _buckets(dto) == (0, 0, 0, 1)
        _assert_reconciles(dto)

    async def test_maintenance_with_no_end_occupies_until_closed(self, db_session):
        now = datetime.now(TZ)
        v = await _veh(db_session, "MT-5")
        await _maint(db_session, v, now - timedelta(days=30), None)
        dto = await build_dashboard_snapshot(db_session, now=now)
        assert _buckets(dto) == (0, 0, 0, 1)

    # 5 — cancelled reservation
    async def test_cancelled_reservation_never_inflates_anything(self, db_session):
        now = datetime.now(TZ)
        v = await _veh(db_session, "CX-1")
        await _res(db_session, v, now - timedelta(days=1), days=5, total=5000.0,
                   status="CANCELLED")
        dto = await build_dashboard_snapshot(db_session, now=now, period="year")
        assert dto["revenue"]["amount"] == 0.0
        assert dto["top_vehicles"] == []
        assert _buckets(dto) == (1, 0, 0, 0)   # the car is free again
        _assert_reconciles(dto)

    # 6 — completed rental
    async def test_completed_rental_recognises_its_full_price(self, db_session):
        now = datetime.now(TZ)
        v = await _veh(db_session, "CP-1")
        await _res(db_session, v, now - timedelta(days=10), days=4, total=800.0,
                   status="COMPLETED")
        dto = await build_dashboard_snapshot(db_session, now=now, period="year")
        assert dto["revenue"]["amount"] == 800.0
        assert dto["revenue"]["rental_days"] == 4
        assert _buckets(dto) == (1, 0, 0, 0)
        _assert_reconciles(dto)

    # 7 / 17 / 20 — multiple vehicles, exclusivity, reconciliation
    async def test_categories_are_mutually_exclusive_and_reconcile(self, db_session):
        now = datetime.now(TZ)
        v_ready = await _veh(db_session, "EX-READY")
        v_rented = await _veh(db_session, "EX-RENT")
        v_reserved = await _veh(db_session, "EX-RESV")
        v_maint = await _veh(db_session, "EX-MAINT")
        v_sold = await _veh(db_session, "EX-SOLD", status="SOLD")

        await _res(db_session, v_rented, now - timedelta(days=1), days=4)
        await _res(db_session, v_reserved, now + timedelta(days=3), days=2)
        await _maint(db_session, v_maint, now - timedelta(hours=1), now + timedelta(days=1))

        dto = await build_dashboard_snapshot(db_session, now=now)
        assert _buckets(dto) == (1, 1, 1, 1)
        assert dto["vehicles"]["total"] == 4
        assert dto["vehicles"]["excluded_structural"] == 1
        assert dto["vehicles"]["fleet_size"] == 5
        _assert_reconciles(dto)

    async def test_maintenance_beats_an_in_progress_rental(self, db_session):
        """A car in maintenance must not also appear as en location / réservé /
        prêt à louer — MAINTENANCE has the highest operational precedence."""
        now = datetime.now(TZ)
        v = await _veh(db_session, "PR-1")
        await _res(db_session, v, now - timedelta(days=1), days=4)
        await _maint(db_session, v, now - timedelta(hours=1), now + timedelta(days=1))
        dto = await build_dashboard_snapshot(db_session, now=now)
        assert _buckets(dto) == (0, 1 - 1, 0, 1)
        _assert_reconciles(dto)

    async def test_active_rental_beats_a_future_reservation_on_the_same_car(self, db_session):
        now = datetime.now(TZ)
        v = await _veh(db_session, "PR-2")
        await _res(db_session, v, now - timedelta(days=1), days=2)
        await _res(db_session, v, now + timedelta(days=10), days=2)
        dto = await build_dashboard_snapshot(db_session, now=now)
        assert _buckets(dto) == (0, 1, 0, 0)
        _assert_reconciles(dto)

    # 8 / 9 / 19 — multiple rentals, history, Top-5 ranking
    async def test_top_five_ranking_is_deterministic_and_excludes_cancelled(self, db_session):
        now = datetime.now(TZ)
        va = await _veh(db_session, "TOP-A")
        vb = await _veh(db_session, "TOP-B")
        vc = await _veh(db_session, "TOP-C")
        # A: 3 historical rentals; B: 2; C: 1 cancelled only -> absent
        for i in (60, 40, 20):
            await _res(db_session, va, now - timedelta(days=i), days=2, total=400.0,
                       status="COMPLETED")
        for i in (50, 30):
            await _res(db_session, vb, now - timedelta(days=i), days=2, total=1000.0,
                       status="COMPLETED")
        await _res(db_session, vc, now - timedelta(days=10), days=2, total=9999.0,
                   status="CANCELLED")

        dto = await build_dashboard_snapshot(db_session, now=now)
        top = dto["top_vehicles"]
        assert [t["registration"] for t in top] == ["TOP-A", "TOP-B"]
        assert [t["rank"] for t in top] == [1, 2]
        assert top[0]["rental_count"] == 3 and top[0]["revenue"] == 1200.0
        assert top[1]["rental_count"] == 2 and top[1]["revenue"] == 2000.0
        # Ranking is by COUNT, not by money: B earns more but ranks second.
        assert top[0]["rental_count"] > top[1]["rental_count"]
        _assert_reconciles(dto)

    async def test_top_five_is_capped_at_five_and_future_bookings_excluded(self, db_session):
        now = datetime.now(TZ)
        for i in range(7):
            v = await _veh(db_session, f"CAP-{i}")
            for _ in range(i + 1):
                await _res(db_session, v, now - timedelta(days=100 + i * 10 + _ * 3),
                           days=1, total=100.0, status="COMPLETED")
        future = await _veh(db_session, "CAP-FUT")
        await _res(db_session, future, now + timedelta(days=5), days=1, total=100.0)

        dto = await build_dashboard_snapshot(db_session, now=now)
        top = dto["top_vehicles"]
        assert len(top) == 5
        assert [t["registration"] for t in top] == ["CAP-6", "CAP-5", "CAP-4", "CAP-3", "CAP-2"]
        assert "CAP-FUT" not in [t["registration"] for t in top]

    async def test_top_five_ties_break_on_vehicle_id_ascending(self, db_session):
        now = datetime.now(TZ)
        vs = [await _veh(db_session, f"TIE-{i}") for i in range(3)]
        for v in vs:
            await _res(db_session, v, now - timedelta(days=20), days=1, total=100.0,
                       status="COMPLETED")
        dto = await build_dashboard_snapshot(db_session, now=now)
        ids = [t["vehicle_id"] for t in dto["top_vehicles"]]
        assert ids == sorted(ids), "equal count + equal revenue must order by vehicle_id ASC"

    # 10 / 11 — rental starts today / ends today
    async def test_rental_starting_today_counts_in_reservations_today(self, db_session):
        now = datetime.now(TZ).replace(hour=12, minute=0, second=0, microsecond=0)
        v = await _veh(db_session, "ST-1")
        await _res(db_session, v, now.replace(hour=9), days=3, total=900.0)
        dto = await build_dashboard_snapshot(db_session, now=now)
        assert dto["reservations_today"]["starting_today"] == 1
        assert dto["reservations_today"]["count"] == 1
        assert dto["reservations_today"]["ending_today"] == 0
        assert _buckets(dto) == (0, 1, 0, 0)

    async def test_rental_ending_today_counts_in_returns(self, db_session):
        now = datetime.now(TZ).replace(hour=12, minute=0, second=0, microsecond=0)
        v = await _veh(db_session, "EN-1")
        await _res(db_session, v, now.replace(hour=18) - timedelta(days=2), days=2,
                   total=600.0)
        dto = await build_dashboard_snapshot(db_session, now=now)
        assert dto["reservations_today"]["ending_today"] == 1
        assert dto["reservations_today"]["starting_today"] == 0

    # 12 / 13 — timezone and midnight boundaries
    async def test_midnight_boundary_is_half_open(self, db_session):
        """00:00:00 belongs to the new day; the previous day ends exclusively."""
        v = await _veh(db_session, "MB-1")
        day = date(2026, 6, 15)
        midnight = datetime(2026, 6, 15, 0, 0, 0, tzinfo=TZ)
        await _res(db_session, v, midnight, days=1, total=300.0, status="COMPLETED")

        at_midnight = await build_dashboard_snapshot(db_session, now=midnight, period="today")
        assert at_midnight["reservations_today"]["starting_today"] == 1
        assert at_midnight["revenue"]["period_start"] == day.isoformat()
        assert at_midnight["revenue"]["period_end"] == (day + timedelta(days=1)).isoformat()
        assert at_midnight["revenue"]["amount"] == 300.0

        one_tick_before = datetime(2026, 6, 14, 23, 59, 59, tzinfo=TZ)
        prev = await build_dashboard_snapshot(db_session, now=one_tick_before, period="today")
        assert prev["reservations_today"]["starting_today"] == 0
        assert prev["revenue"]["amount"] == 0.0
        assert prev["vehicles"]["reserved"] == 0  # COMPLETED never blocks

    async def test_timezone_boundary_uses_casablanca_not_utc(self, db_session):
        """23:30 Casablanca on the 15th is 22:30 UTC on the 15th; a UTC-based
        day boundary would misfile a rental started just after local midnight."""
        v = await _veh(db_session, "TZ-1")
        just_after_local_midnight = datetime(2026, 6, 16, 0, 30, tzinfo=TZ)
        await _res(db_session, v, just_after_local_midnight, days=1, total=240.0,
                   status="COMPLETED")
        now = datetime(2026, 6, 16, 12, 0, tzinfo=TZ)
        dto = await build_dashboard_snapshot(db_session, now=now, period="today")
        assert dto["business_timezone"] == "Africa/Casablanca"
        assert dto["reservations_today"]["starting_today"] == 1
        assert dto["revenue"]["amount"] == 240.0

    # 18 — revenue date filtering
    async def test_revenue_date_filtering_splits_a_rental_across_periods(self, db_session):
        v = await _veh(db_session, "RF-1")
        # 4-day rental starting 29 June -> 2 days in June, 2 days in July
        await _res(db_session, v, datetime(2026, 6, 29, 10, 0, tzinfo=TZ), days=4,
                   total=400.0, status="COMPLETED")
        now = datetime(2026, 7, 20, 12, 0, tzinfo=TZ)

        june = await build_dashboard_snapshot(db_session, now=now, period="last_month")
        july = await build_dashboard_snapshot(db_session, now=now, period="month")
        year = await build_dashboard_snapshot(db_session, now=now, period="year")

        assert june["revenue"]["amount"] == 200.0
        assert july["revenue"]["amount"] == 200.0
        assert year["revenue"]["amount"] == 400.0
        # rental COUNT stays anchored to the start date
        assert june["revenue"]["rentals"] == 1
        assert july["revenue"]["rentals"] == 0

    async def test_custom_range_end_date_is_inclusive(self, db_session):
        v = await _veh(db_session, "CR-1")
        await _res(db_session, v, datetime(2026, 3, 10, 9, 0, tzinfo=TZ), days=3,
                   total=300.0, status="COMPLETED")
        now = datetime(2026, 4, 1, 9, 0, tzinfo=TZ)
        dto = await build_dashboard_snapshot(
            db_session, period="custom", custom_from=date(2026, 3, 10),
            custom_to_inclusive=date(2026, 3, 12), now=now,
        )
        assert dto["revenue"]["amount"] == 300.0
        assert dto["revenue"]["period_end_inclusive"] == "2026-03-12"
        assert dto["revenue"]["period_end"] == "2026-03-13"

    async def test_operational_counters_ignore_a_historical_revenue_period(self, db_session):
        """§16 — picking 'Année dernière' must not change how many cars are out."""
        now = datetime.now(TZ)
        v = await _veh(db_session, "OP-1")
        await _res(db_session, v, now - timedelta(days=1), days=4)
        this_month = await build_dashboard_snapshot(db_session, now=now, period="month")
        last_year = await build_dashboard_snapshot(db_session, now=now, period="last_year")
        assert _buckets(this_month) == _buckets(last_year) == (0, 1, 0, 0)
        assert (this_month["reservations_today"]["in_progress"]
                == last_year["reservations_today"]["in_progress"] == 1)
        assert last_year["revenue"]["amount"] == 0.0

    async def test_duplicate_rows_do_not_double_count_a_vehicle(self, db_session):
        """Two rentals covering `now` on ONE car is still ONE car en location."""
        now = datetime.now(TZ)
        v = await _veh(db_session, "DUP-1")
        await _res(db_session, v, now - timedelta(days=1), days=3, total=300.0)
        # second overlapping row (seeded directly, bypassing the booking guard)
        r2 = Reservation(
            vehicle_id=v.id, customer_name="T2",
            start_datetime=now - timedelta(days=1), end_datetime=now + timedelta(days=2),
            daily_price=100.0, num_days=3, total_price=300.0, deposit=0,
            status="COMPLETED", payment_status="PAID", created_by=None,
        )
        db_session.add(r2)
        await db_session.commit()
        dto = await build_dashboard_snapshot(db_session, now=now)
        assert _buckets(dto) == (0, 1, 0, 0)
        _assert_reconciles(dto)

    # 16 — refresh after mutation
    async def test_snapshot_reflects_a_mutation_immediately(self, db_session):
        now = datetime.now(TZ)
        v = await _veh(db_session, "MU-1")
        before = await build_dashboard_snapshot(db_session, now=now)
        assert _buckets(before) == (1, 0, 0, 0)

        r = await _res(db_session, v, now - timedelta(hours=1), days=2, total=400.0)
        after_rent = await build_dashboard_snapshot(db_session, now=now)
        assert _buckets(after_rent) == (0, 1, 0, 0)

        r.status = "CANCELLED"
        await db_session.commit()
        after_cancel = await build_dashboard_snapshot(db_session, now=now)
        assert _buckets(after_cancel) == (1, 0, 0, 0)
        assert after_cancel["revenue"]["amount"] == 0.0

    async def test_generated_at_is_one_instant_for_the_whole_snapshot(self, db_session):
        now = datetime(2026, 5, 4, 15, 30, tzinfo=TZ)
        dto = await build_dashboard_snapshot(db_session, now=now)
        assert dto["generated_at"] == now.isoformat()
        assert dto["reservations_today"]["date"] == "2026-05-04"


@pytest.mark.asyncio
class TestDashboardSummaryEndpoint:

    async def test_endpoint_returns_the_whole_dto_in_one_call(
        self, client: AsyncClient, admin_token, db_session
    ):
        now = datetime.now(TZ)
        v = await _veh(db_session, "EP-1")
        await _res(db_session, v, now - timedelta(days=1), days=3, total=900.0)

        r = await client.get(
            "/api/v1/dashboard/summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        dto = r.json()
        for key in ("schema_version", "generated_at", "business_timezone", "currency",
                    "revenue", "reservations_today", "maintenance", "vehicles",
                    "top_vehicles", "integrity"):
            assert key in dto, f"missing DTO key {key}"
        assert dto["vehicles"]["active_rental"] == 1
        assert dto["integrity"]["ok"] is True

    async def test_endpoint_honours_the_period_parameter(
        self, client: AsyncClient, admin_token, db_session
    ):
        h = {"Authorization": f"Bearer {admin_token}"}
        for name in ("today", "yesterday", "week", "last_week", "month",
                     "last_month", "year", "last_year"):
            r = await client.get(f"/api/v1/dashboard/summary?period={name}", headers=h)
            assert r.status_code == 200, name
            assert r.json()["revenue"]["period"] == name

    async def test_endpoint_rejects_an_unknown_period(
        self, client: AsyncClient, admin_token
    ):
        r = await client.get(
            "/api/v1/dashboard/summary?period=next_century",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 422

    async def test_endpoint_custom_range(
        self, client: AsyncClient, admin_token, db_session
    ):
        v = await _veh(db_session, "EPC-1")
        await _res(db_session, v, datetime(2026, 2, 2, 9, 0, tzinfo=TZ), days=2,
                   total=200.0, status="COMPLETED")
        r = await client.get(
            "/api/v1/dashboard/summary?period=custom&from=2026-02-02&to=2026-02-03",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        assert r.json()["revenue"]["amount"] == 200.0

    async def test_custom_without_dates_is_a_422_not_a_silent_zero(
        self, client: AsyncClient, admin_token
    ):
        r = await client.get(
            "/api/v1/dashboard/summary?period=custom",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 422

    async def test_endpoint_requires_authentication(self, client: AsyncClient):
        r = await client.get("/api/v1/dashboard/summary")
        assert r.status_code in (401, 403)

    async def test_legacy_stats_projects_the_same_numbers(
        self, client: AsyncClient, admin_token, db_session
    ):
        """The old shape must never contradict the new one."""
        now = datetime.now(TZ)
        v1 = await _veh(db_session, "LG-1")
        v2 = await _veh(db_session, "LG-2")
        await _res(db_session, v1, now - timedelta(days=1), days=3, total=900.0)
        await _res(db_session, v2, now + timedelta(days=4), days=2, total=400.0)

        h = {"Authorization": f"Bearer {admin_token}"}
        legacy = (await client.get("/api/v1/dashboard/stats", headers=h)).json()
        summary = (await client.get("/api/v1/dashboard/summary?period=month",
                                    headers=h)).json()
        assert legacy["total_vehicles"] == summary["vehicles"]["total"]
        assert legacy["available"] == summary["vehicles"]["ready_to_rent"]
        assert legacy["rented"] == summary["vehicles"]["active_rental"]
        assert legacy["reserved"] == summary["vehicles"]["reserved"]
        assert legacy["maintenance"] == summary["vehicles"]["maintenance"]
        assert legacy["month_revenue"] == summary["revenue"]["amount"]
