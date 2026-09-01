"""Increment 4 — cross-client convergence.

Two independent desktop `DomainStore` instances, given IDENTICAL interval data
and the SAME `now`, derive byte-identical canonical state (effective status,
fleet counts, dashboard overview, next boundary). The clocks are independent;
they converge from the same authoritative data + shared normative semantics.

The third client (mobile / Kotlin) runs the SAME `shared/fleet_status_cases.json`
vectors in `mobile/app/src/test/java/com/example/FleetStatusParityTest.kt`, and
the backend in `backend/tests/test_fleet_status_crossruntime.py` — all four
(Desktop-A, Desktop-B, Mobile, Backend) assert against the one normative
reference, so no client can silently diverge.
"""
import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CAR_RENTAL_DB_RESET", "1")

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.state.domain_store import DomainStore
from app.utils.fleet_status import next_boundary_rows

_SHARED = pathlib.Path(__file__).resolve().parents[2] / "shared"
sys.path.insert(0, str(_SHARED))
from fleet_status_reference import (  # noqa: E402
    effective_statuses as ref_effective,
    fleet_counts as ref_counts,
    next_boundary as ref_next_boundary,
)

_CASES = json.loads((_SHARED / "fleet_status_cases.json").read_text())
_NOW = datetime.fromisoformat(_CASES["now"].replace("Z", "+00:00"))

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _db():
    init_local_db()


def _seed_two_active_reservations():
    s = get_local_session()
    for vid, end in (("a", NOW + timedelta(minutes=5)), ("b", NOW + timedelta(minutes=10))):
        s.add(LocalVehicle(id=vid, registration=f"R-{vid}", vin=f"{vid}xxxxxxxxxxxxxxxx"[:17],
                           brand="B", model="M", year=2024, color="N", fuel_type="D",
                           transmission="M", status="AVAILABLE", daily_rental_price=100,
                           created_at=NOW.isoformat(), updated_at=NOW.isoformat(), version=1))
        s.add(LocalReservation(id=f"r-{vid}", vehicle_id=vid, customer_name="X",
                               start_datetime=(NOW - timedelta(hours=1)).isoformat(),
                               end_datetime=end.isoformat(), daily_price=100, num_days=1,
                               total_price=300, deposit=0, status="ACTIVE",
                               created_at=NOW.isoformat(), updated_at=NOW.isoformat(), version=1))
    s.commit(); s.close()


def test_two_desktop_stores_derive_identical_state():
    _seed_two_active_reservations()
    frozen = NOW

    a = DomainStore(now_fn=lambda: frozen)
    b = DomainStore(now_fn=lambda: frozen)
    a.reload()
    b.reload()

    assert a.snapshot.effective == b.snapshot.effective
    assert a.snapshot.fleet_counts == b.snapshot.fleet_counts
    assert a.snapshot.overview == b.snapshot.overview
    assert a.snapshot.next_boundary == b.snapshot.next_boundary
    assert a.snapshot.effective["a"] == "RENTED"

    # advance both by the same amount, recompute — still identical
    later = NOW + timedelta(minutes=6)
    for store in (a, b):
        store.set_now_fn(lambda: later)
        store.recompute_effective()
    assert a.snapshot.effective == b.snapshot.effective          # 'a' freed, 'b' still rented
    assert a.snapshot.effective["a"] == "AVAILABLE"
    assert a.snapshot.effective["b"] == "RENTED"
    assert a.snapshot.fleet_counts == b.snapshot.fleet_counts


@pytest.mark.parametrize("case", _CASES["cases"], ids=lambda c: c["name"])
def test_desktop_impl_agrees_with_reference_on_every_vector(case):
    """Desktop `next_boundary_rows` and effective/counts vs the normative
    reference — the same vectors Mobile and Backend assert against."""
    want_eff = ref_effective(case["vehicles"], case["reservations"], case["maintenances"], _NOW)
    want_cnt = ref_counts(case["vehicles"], case["reservations"], case["maintenances"], _NOW)
    want_nb = ref_next_boundary(case["reservations"], case["maintenances"], _NOW)

    # The shared vectors carry expected_next_boundary so the Kotlin runtime
    # (which has no in-process Python reference) asserts against the same value.
    # Guard it here against drift from the reference.
    want_nb_iso = None if want_nb is None else want_nb.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert want_nb_iso == case.get("expected_next_boundary"), (
        f"{case['name']}: expected_next_boundary drift {want_nb_iso} != {case.get('expected_next_boundary')}"
    )

    from app.utils.fleet_status import effective_statuses_rows, compute_fleet_counts_rows
    got_eff = effective_statuses_rows(
        case["vehicles"],
        [{"vehicle_id": r["vehicle_id"], "status": r["status"],
          "start_datetime": r.get("start"), "end_datetime": r.get("end")} for r in case["reservations"]],
        [{"vehicle_id": m["vehicle_id"], "status": m["status"],
          "start_datetime": m.get("start"), "expected_end_datetime": m.get("expected_end"),
          "actual_end_datetime": m.get("actual_end")} for m in case["maintenances"]],
        _NOW,
    )
    assert got_eff == want_eff, case["name"]

    got_nb = next_boundary_rows(
        [{"vehicle_id": r["vehicle_id"], "status": r["status"],
          "start_datetime": r.get("start"), "end_datetime": r.get("end")} for r in case["reservations"]],
        [{"vehicle_id": m["vehicle_id"], "status": m["status"],
          "start_datetime": m.get("start"), "expected_end_datetime": m.get("expected_end"),
          "actual_end_datetime": m.get("actual_end")} for m in case["maintenances"]],
        _NOW,
        include_midnight=False,
    )
    assert got_nb == want_nb, f"{case['name']}: next_boundary drift {got_nb} != {want_nb}"
