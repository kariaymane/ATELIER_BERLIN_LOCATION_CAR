"""CROSS-RUNTIME PARITY — desktop vs the normative spec.

Every scenario in ``shared/fleet_status_cases.json`` is materialised as real
local SQLite rows and pushed through the desktop's canonical
``compute_fleet_sets`` / ``effective_status`` / ``compute_fleet_counts``.
The output must match ``shared/fleet_status_reference.py`` — the same file
the backend and mobile parity tests assert against — so the Vehicles page,
the Dashboard and the server can never disagree.
"""
import json
import os
import pathlib
import sys
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CAR_RENTAL_DB_RESET", "1")

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.utils.fleet_status import (
    compute_fleet_sets,
    effective_status as desktop_effective,
    compute_fleet_counts,
)

_SHARED = pathlib.Path(__file__).resolve().parents[2] / "shared"
sys.path.insert(0, str(_SHARED))
from fleet_status_reference import (  # noqa: E402
    effective_statuses as ref_effective,
    fleet_counts as ref_counts,
)

_CASES = json.loads((_SHARED / "fleet_status_cases.json").read_text())
_NOW = datetime.fromisoformat(_CASES["now"].replace("Z", "+00:00"))
_NOW_ISO = _CASES["now"]


@pytest.fixture(autouse=True)
def _fresh_db():
    init_local_db()


@pytest.mark.parametrize("case", _CASES["cases"], ids=lambda c: c["name"])
def test_desktop_matches_reference(case):
    s = get_local_session()
    try:
        for v in case["vehicles"]:
            s.add(LocalVehicle(
                id=v["id"], brand="T", model="A", registration=f"P-{v['id']}",
                vin=f"{v['id']}xxxxxxxxxxxxxxxx"[:17], year=2026, color="N",
                fuel_type="Diesel", transmission="Manual", status=v["status"],
                daily_rental_price=1, created_at=_NOW_ISO, updated_at=_NOW_ISO,
                version=1,
            ))
        for i, r in enumerate(case["reservations"]):
            s.add(LocalReservation(
                id=f"r{i}-{r['vehicle_id']}", vehicle_id=r["vehicle_id"],
                customer_name="X", start_datetime=r["start"], end_datetime=r["end"],
                daily_price=1, num_days=1, total_price=1, deposit=0,
                status=r["status"], created_at=_NOW_ISO, updated_at=_NOW_ISO, version=1,
            ))
        for i, m in enumerate(case["maintenances"]):
            s.add(LocalMaintenance(
                id=f"m{i}-{m['vehicle_id']}", vehicle_id=m["vehicle_id"], type="X",
                status=m["status"], start_datetime=m["start"],
                expected_end_datetime=m.get("expected_end"),
                actual_end_datetime=m.get("actual_end"),
                created_at=_NOW_ISO, updated_at=_NOW_ISO, version=1,
            ))
        s.commit()

        want_eff = ref_effective(case["vehicles"], case["reservations"],
                                 case["maintenances"], _NOW)
        want_cnt = ref_counts(case["vehicles"], case["reservations"],
                              case["maintenances"], _NOW)
        assert want_eff == case["expected_effective"]

        rented, reserved, maint, _total = compute_fleet_sets(s, now=_NOW)
        got_eff = {
            v["id"]: desktop_effective(v["status"], v["id"], rented, reserved, maint)
            for v in case["vehicles"]
        }
        assert got_eff == want_eff, f"{case['name']}: desktop effective_status drift"

        got_cnt = compute_fleet_counts(s, now=_NOW)
        for k in ("total_vehicles", "available", "reserved", "rented", "maintenance"):
            assert got_cnt[k] == want_cnt[k], (
                f"{case['name']}: desktop count '{k}' {got_cnt[k]} != spec {want_cnt[k]}"
            )
    finally:
        s.close()
