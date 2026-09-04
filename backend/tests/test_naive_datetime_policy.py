"""R5 — PERMANENT GUARD: the ONE naive-datetime policy.

A datetime with no UTC offset is BUSINESS-LOCAL wall time (Africa/Casablanca),
never UTC. That rule is written in `shared/money_time.to_utc` and every other
coercion site in the product must agree with it *to the instant*.

WHY THIS FILE EXISTS
--------------------
The rule had been re-typed by hand in eight places and two of them chose
`naive == UTC`. Nothing caught it, because every interval literal in
`shared/fleet_status_cases.json` carried an explicit `Z`, so the cross-runtime
parity vectors could not exercise the one input class where the runtimes
actually disagreed. Backend and Desktop said a car was RENTED while Mobile said
it was RESERVED — same row, same instant.

Two independent guards live here:

  1. `test_naive_datetime_policy_consistency` — every coercion helper reachable
     from Python (backend AND the desktop's dependency-free utils) maps the same
     naive literal to the same instant. Add a helper that disagrees and this
     fails loudly, naming the offending site.
  2. `test_sql_vs_python_boundary_parity` — the backend derivation resolves the
     exact half-open boundaries the same way Python does, for reservations and
     for maintenance. This is the guard against re-introducing a range filter in
     SQL: SQLite drops the offset on write and then compares the bound
     lexically, which reported `ts > now` true for a row where `ts == now`.

The Kotlin side is guarded by `mobile/.../NaiveDatetimePolicyTest.kt`, which
asserts the identical instants, and by `FleetStatusParityTest` running the
`naive_*` vectors added to the shared case file.
"""
import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.models.reservation import Reservation
from app.models.maintenance import Maintenance
from app.services.fleet_status import compute_effective_statuses
from shared.money_time import BUSINESS_TZ, to_business, to_utc

_ROOT = pathlib.Path(__file__).resolve().parents[2]

# A naive literal and the instant the ONE policy says it denotes.
NAIVE_LITERAL = "2026-08-30T13:00:00"
NAIVE_DT = datetime(2026, 8, 30, 13, 0)
EXPECTED_INSTANT = datetime(2026, 8, 30, 13, 0, tzinfo=BUSINESS_TZ).astimezone(timezone.utc)


def _load(name: str, relpath: str):
    """Import a dependency-free module by path (lets a backend test reach the
    desktop's datetime utils without importing the desktop package/Qt)."""
    spec = importlib.util.spec_from_file_location(name, _ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_naive_datetime_policy_consistency():
    """Every Python coercion site must place a naive value at the SAME instant."""
    desktop_dt_utils = _load("_desk_dt", "desktop/app/utils/datetime_utils.py")
    desktop_cache = _load("_desk_cache", "desktop/app/sync/dashboard_cache.py")
    fleet_ref = _load("_fleet_ref", "shared/fleet_status_reference.py")
    revenue_ref = _load("_rev_ref", "shared/revenue_reference.py")

    from app.api.v1.maintenance import _as_utc as maint_as_utc
    from app.services.fleet_status import _coerce as backend_fleet_coerce
    from app.services.sync_service import _as_utc as sync_as_utc

    sites = {
        "shared.money_time.to_utc": to_utc(NAIVE_DT),
        "shared.money_time.to_business": to_business(NAIVE_DT),
        "shared.fleet_status_reference._parse": fleet_ref._parse(NAIVE_LITERAL),
        "shared.revenue_reference._as_datetime": revenue_ref._as_datetime(NAIVE_LITERAL),
        "desktop.utils.datetime_utils.parse_datetime_utc":
            desktop_dt_utils.parse_datetime_utc(NAIVE_LITERAL),
        "desktop.sync.dashboard_cache._to_biz": desktop_cache._to_biz(NAIVE_DT),
        "backend.services.fleet_status._coerce": backend_fleet_coerce(NAIVE_DT),
        "backend.services.sync_service._as_utc": sync_as_utc(NAIVE_DT),
        "backend.api.v1.maintenance._as_utc": maint_as_utc(NAIVE_DT),
    }

    divergent = {
        name: value for name, value in sites.items()
        if value is None or value.astimezone(timezone.utc) != EXPECTED_INSTANT
    }
    assert not divergent, (
        "NAIVE-DATETIME POLICY DIVERGENCE — these sites do not read "
        f"{NAIVE_LITERAL!r} as business-local ({EXPECTED_INSTANT.isoformat()}): "
        + "; ".join(
            f"{n} -> {v.isoformat() if v is not None else None}"
            for n, v in divergent.items()
        )
    )

    # And the policy must be the business zone specifically, not UTC-by-luck:
    # the two readings are one Casablanca offset apart, so they cannot coincide.
    assert EXPECTED_INSTANT != NAIVE_DT.replace(tzinfo=timezone.utc), (
        "test is vacuous: pick a literal where business-local and UTC differ"
    )


def test_string_and_datetime_forms_agree():
    """The ISO-string parsers and the datetime coercers must not disagree."""
    desktop_dt_utils = _load("_desk_dt2", "desktop/app/utils/datetime_utils.py")
    fleet_ref = _load("_fleet_ref2", "shared/fleet_status_reference.py")

    for literal, dt in (
        ("2026-08-30T13:00:00", datetime(2026, 8, 30, 13, 0)),
        ("2026-01-15T08:30:00", datetime(2026, 1, 15, 8, 30)),
        ("2026-08-30 13:00:00", datetime(2026, 8, 30, 13, 0)),   # SQLite form
    ):
        want = to_utc(dt)
        assert desktop_dt_utils.parse_datetime_utc(literal) == want, literal
        assert fleet_ref._parse(literal) == want, literal


async def _mk_vehicle(db):
    v_id = uuid4()
    db.add(Vehicle(
        id=v_id, brand="T", model="A", registration=f"ND-{v_id.hex[:5]}",
        vin=f"VIN{v_id.hex[:14]}", year=2026, color="Noir",
        fuel_type="GASOLINE", transmission="AUTOMATIC", daily_rental_price=10,
        status="AVAILABLE",
    ))
    await db.flush()
    return v_id


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_naive", [True, False], ids=["naive_row", "aware_row"])
async def test_sql_vs_python_boundary_parity_reservation(
    db_session: AsyncSession, stored_naive: bool
):
    """Half-open [start, end) for a reservation, resolved identically whether the
    stored row kept its offset or lost it."""
    start_biz = datetime(2026, 8, 30, 9, 0, tzinfo=BUSINESS_TZ)
    end_biz = datetime(2026, 8, 30, 13, 0, tzinfo=BUSINESS_TZ)
    start_col = start_biz.replace(tzinfo=None) if stored_naive else start_biz
    end_col = end_biz.replace(tzinfo=None) if stored_naive else end_biz

    v_id = await _mk_vehicle(db_session)
    db_session.add(Reservation(
        id=uuid4(), vehicle_id=v_id, status="RESERVED",
        start_datetime=start_col, end_datetime=end_col,
        customer_name="X", customer_phone="1", daily_price=10, num_days=1,
        total_price=10, deposit=0,
    ))
    await db_session.commit()

    start_i = start_biz.astimezone(timezone.utc)
    end_i = end_biz.astimezone(timezone.utc)

    async def eff(now):
        return (await compute_effective_statuses(db_session, [v_id], now=now))[str(v_id)]

    assert await eff(start_i - timedelta(minutes=1)) == "RESERVED", "before start -> upcoming"
    assert await eff(start_i) == "RENTED", "exactly at start -> occupied (inclusive)"
    assert await eff(start_i + timedelta(minutes=1)) == "RENTED", "during -> occupied"
    assert await eff(end_i - timedelta(minutes=1)) == "RENTED", "just before end -> occupied"
    assert await eff(end_i) == "AVAILABLE", "exactly at end -> free (exclusive)"
    assert await eff(end_i + timedelta(minutes=1)) == "AVAILABLE", "after end -> free"


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_naive", [True, False], ids=["naive_row", "aware_row"])
async def test_sql_vs_python_boundary_parity_maintenance(
    db_session: AsyncSession, stored_naive: bool
):
    """Same half-open guarantee for a maintenance ticket."""
    start_biz = datetime(2026, 8, 30, 9, 0, tzinfo=BUSINESS_TZ)
    end_biz = datetime(2026, 8, 30, 13, 0, tzinfo=BUSINESS_TZ)
    start_col = start_biz.replace(tzinfo=None) if stored_naive else start_biz
    end_col = end_biz.replace(tzinfo=None) if stored_naive else end_biz

    v_id = await _mk_vehicle(db_session)
    db_session.add(Maintenance(
        id=uuid4(), vehicle_id=v_id, status="ACTIVE", type="Entretien",
        start_datetime=start_col, expected_end_datetime=end_col,
    ))
    await db_session.commit()

    start_i = start_biz.astimezone(timezone.utc)
    end_i = end_biz.astimezone(timezone.utc)

    async def eff(now):
        return (await compute_effective_statuses(db_session, [v_id], now=now))[str(v_id)]

    assert await eff(start_i - timedelta(minutes=1)) == "AVAILABLE"
    assert await eff(start_i) == "MAINTENANCE", "exactly at start -> occupied"
    assert await eff(end_i - timedelta(minutes=1)) == "MAINTENANCE"
    assert await eff(end_i) == "AVAILABLE", "exactly at end -> free"


@pytest.mark.asyncio
async def test_maintenance_actual_end_wins_over_expected_end(db_session: AsyncSession):
    """COALESCE(actual_end, expected_end) — a ticket closed early frees its
    vehicle immediately, even with a later expected_end still on the row.
    Two helpers had these operands reversed."""
    from app.services.sync_service import _maintenance_active_now

    start = datetime(2026, 8, 30, 8, 0, tzinfo=BUSINESS_TZ)
    now_i = datetime(2026, 8, 30, 12, 0, tzinfo=BUSINESS_TZ).astimezone(timezone.utc)

    v_id = await _mk_vehicle(db_session)
    m = Maintenance(
        id=uuid4(), vehicle_id=v_id, status="ACTIVE", type="Entretien",
        start_datetime=start,
        actual_end_datetime=datetime(2026, 8, 30, 10, 0, tzinfo=BUSINESS_TZ),   # closed
        expected_end_datetime=datetime(2026, 9, 5, 10, 0, tzinfo=BUSINESS_TZ),  # stale estimate
    )
    db_session.add(m)
    await db_session.commit()

    eff = await compute_effective_statuses(db_session, [v_id], now=now_i)
    assert eff[str(v_id)] == "AVAILABLE", "actual_end must win over expected_end"
    assert _maintenance_active_now(m) is False
