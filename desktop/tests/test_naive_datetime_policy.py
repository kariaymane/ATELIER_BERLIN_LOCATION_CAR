"""R5 — PERMANENT GUARD: the ONE naive-datetime policy, desktop side.

Companion to `backend/tests/test_naive_datetime_policy.py` and
`mobile/.../NaiveDatetimePolicyTest.kt`. All three assert the SAME instants for
the SAME literals, so a drift in any single runtime turns at least one of them
red instead of silently putting one screen an hour out from the others.

Also pins the cross-window invariant on NAIVE rows specifically: the Dashboard
fleet cards and the Vehicles page are both rendered from one `DomainSnapshot`,
so `fleet_counts` must equal the tally of per-vehicle effective statuses in that
same snapshot — the property that makes "Dashboard says 0, Vehicles says 2"
structurally impossible on the desktop.
"""
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CAR_RENTAL_DB_RESET", "1")

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.state.domain_store import reset_domain_store
from app.utils.datetime_utils import parse_datetime_utc
from app.utils.fleet_status import compute_fleet_counts, effective_statuses_rows

_SHARED = pathlib.Path(__file__).resolve().parents[2] / "shared"
sys.path.insert(0, str(_SHARED))
import fleet_status_reference as ref  # noqa: E402
import money_time  # noqa: E402
import revenue_reference  # noqa: E402

BUSINESS_TZ = ZoneInfo("Africa/Casablanca")

# Same literal/instant pair the backend and Kotlin guards use.
NAIVE_LITERAL = "2026-08-30T13:00:00"
NAIVE_DT = datetime(2026, 8, 30, 13, 0)
EXPECTED_INSTANT = datetime(2026, 8, 30, 13, 0, tzinfo=BUSINESS_TZ).astimezone(timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_db():
    init_local_db()
    reset_domain_store()


def test_naive_datetime_policy_consistency():
    """Every desktop-reachable coercion site places a naive value identically."""
    from app.sync.dashboard_cache import _to_biz

    sites = {
        "desktop.utils.datetime_utils.parse_datetime_utc(str)":
            parse_datetime_utc(NAIVE_LITERAL),
        "desktop.utils.datetime_utils.parse_datetime_utc(datetime)":
            parse_datetime_utc(NAIVE_DT),
        "desktop.sync.dashboard_cache._to_biz": _to_biz(NAIVE_DT),
        "shared.money_time.to_utc": money_time.to_utc(NAIVE_DT),
        "shared.money_time.to_business": money_time.to_business(NAIVE_DT),
        "shared.fleet_status_reference._parse": ref._parse(NAIVE_LITERAL),
        "shared.revenue_reference._as_datetime": revenue_reference._as_datetime(NAIVE_LITERAL),
    }
    divergent = {
        n: v for n, v in sites.items()
        if v is None or v.astimezone(timezone.utc) != EXPECTED_INSTANT
    }
    assert not divergent, (
        "NAIVE-DATETIME POLICY DIVERGENCE — these sites do not read "
        f"{NAIVE_LITERAL!r} as business-local ({EXPECTED_INSTANT.isoformat()}): "
        + "; ".join(f"{n} -> {v.isoformat() if v else None}" for n, v in divergent.items())
    )
    # Not vacuous: business-local and UTC really do differ for this literal.
    assert EXPECTED_INSTANT != NAIVE_DT.replace(tzinfo=timezone.utc)


@pytest.mark.parametrize("kind", ["reservation", "maintenance"])
def test_naive_row_boundaries_match_the_normative_reference(kind):
    """Desktop must agree with `shared/fleet_status_reference` at every edge of a
    half-open window whose stored bounds are NAIVE."""
    start_biz = datetime(2026, 8, 30, 9, 0, tzinfo=BUSINESS_TZ)
    end_biz = datetime(2026, 8, 30, 13, 0, tzinfo=BUSINESS_TZ)
    start_naive = start_biz.replace(tzinfo=None).isoformat()
    end_naive = end_biz.replace(tzinfo=None).isoformat()

    vehicles = [{"id": "v1", "status": "AVAILABLE"}]
    if kind == "reservation":
        rows_desktop = [{"vehicle_id": "v1", "status": "RESERVED",
                         "start_datetime": start_naive, "end_datetime": end_naive}]
        rows_ref = [{"vehicle_id": "v1", "status": "RESERVED",
                     "start": start_naive, "end": end_naive}]
        desk_args = (vehicles, rows_desktop, [])
        ref_args = (vehicles, rows_ref, [])
    else:
        rows_desktop = [{"vehicle_id": "v1", "status": "ACTIVE",
                         "start_datetime": start_naive,
                         "expected_end_datetime": end_naive}]
        rows_ref = [{"vehicle_id": "v1", "status": "ACTIVE",
                     "start": start_naive, "expected_end": end_naive}]
        desk_args = (vehicles, [], rows_desktop)
        ref_args = (vehicles, [], rows_ref)

    start_i = start_biz.astimezone(timezone.utc)
    end_i = end_biz.astimezone(timezone.utc)
    minute = timedelta(minutes=1)

    for now in (start_i - minute, start_i, start_i + minute,
                end_i - minute, end_i, end_i + minute):
        got = effective_statuses_rows(*desk_args, now)
        want = ref.effective_statuses(*ref_args, now)
        assert got == want, f"{kind} @ {now.isoformat()}: desktop {got} != reference {want}"

    # And the edges are genuinely half-open, not merely equal to each other.
    assert effective_statuses_rows(*desk_args, start_i)["v1"] != "AVAILABLE"
    assert effective_statuses_rows(*desk_args, end_i)["v1"] == "AVAILABLE"


def test_dashboard_and_vehicles_agree_on_naive_rows():
    """RENTED and AVAILABLE are distinct metrics, and each has ONE value: the
    snapshot's fleet_counts must equal the per-vehicle tally the Vehicles page
    renders from the same snapshot."""
    from app.state.domain_store import get_domain_store

    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)   # 13:00 Casablanca
    store = reset_domain_store(now_fn=lambda: now)

    s = get_local_session()
    try:
        for i in (1, 2, 3):
            s.add(LocalVehicle(
                id=f"v{i}", brand="T", model="A", registration=f"NP-{i}",
                vin=f"VIN{i}".ljust(17, "X"), year=2026, color="N",
                fuel_type="Diesel", transmission="Manual", status="AVAILABLE",
                daily_rental_price=1, created_at=now.isoformat(),
                updated_at=now.isoformat(), version=1,
            ))
        # NAIVE window covering `now` only under the business-local reading.
        s.add(LocalReservation(
            id="r1", vehicle_id="v1", customer_name="X",
            start_datetime="2026-08-30T12:30:00", end_datetime="2026-08-30T14:30:00",
            daily_price=1, num_days=1, total_price=1, deposit=0, status="RESERVED",
            created_at=now.isoformat(), updated_at=now.isoformat(), version=1,
        ))
        # NAIVE maintenance covering `now`.
        s.add(LocalMaintenance(
            id="m1", vehicle_id="v2", type="X", status="ACTIVE",
            start_datetime="2026-08-30T12:30:00",
            expected_end_datetime="2026-08-30T20:00:00",
            created_at=now.isoformat(), updated_at=now.isoformat(), version=1,
        ))
        s.commit()
    finally:
        s.close()

    snap = store.reload()
    counts = snap.fleet_counts

    tally = {"AVAILABLE": 0, "RENTED": 0, "RESERVED": 0, "MAINTENANCE": 0}
    for v in snap.vehicles:
        tally[v["status"]] = tally.get(v["status"], 0) + 1

    assert counts["rented"] == tally["RENTED"] == 1, "naive window covering now -> RENTED"
    assert counts["maintenance"] == tally["MAINTENANCE"] == 1
    assert counts["available"] == tally["AVAILABLE"] == 1
    assert counts["reserved"] == tally["RESERVED"] == 0

    # The four buckets partition the fleet exactly...
    assert (counts["available"] + counts["rented"]
            + counts["reserved"] + counts["maintenance"]) == counts["total_vehicles"] == 3

    # ...and RENTED is NOT AVAILABLE: they are different metrics over DISJOINT
    # vehicle sets. (Equal counts are legitimate — here both are 1 — so the
    # invariant is disjointness, never numeric inequality.)
    by_bucket: dict[str, set] = {}
    for v in snap.vehicles:
        by_bucket.setdefault(v["status"], set()).add(str(v["id"]))
    assert by_bucket["RENTED"] == {"v1"}
    assert by_bucket["MAINTENANCE"] == {"v2"}
    assert by_bucket["AVAILABLE"] == {"v3"}
    assert not by_bucket["RENTED"] & by_bucket["AVAILABLE"], "buckets must be disjoint"

    # The dashboard overview publishes exactly those same numbers.
    for key in ("total_vehicles", "available", "rented", "reserved", "maintenance"):
        assert snap.overview[key] == counts[key], f"overview['{key}'] diverged from fleet_counts"
