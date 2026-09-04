"""CROSS-RUNTIME PARITY — backend vs the normative spec.

Every scenario in ``shared/fleet_status_cases.json`` is materialised as real
PostgreSQL/SQLite rows and pushed through the backend's canonical
``compute_effective_statuses`` / ``compute_fleet_counts``. The output must
match ``shared/fleet_status_reference.py`` (the same file the desktop and
mobile parity tests assert against), so the three runtimes cannot drift.
"""
import json
import pathlib
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.models.reservation import Reservation
from app.models.maintenance import Maintenance
from app.services.fleet_status import compute_effective_statuses, compute_fleet_counts

import sys
_SHARED = pathlib.Path(__file__).resolve().parents[2] / "shared"
sys.path.insert(0, str(_SHARED))
from fleet_status_reference import (  # noqa: E402
    effective_statuses as ref_effective,
    fleet_counts as ref_counts,
    next_boundary as ref_next_boundary,
)

_CASES = json.loads((_SHARED / "fleet_status_cases.json").read_text())
_NOW = datetime.fromisoformat(_CASES["now"].replace("Z", "+00:00"))


def _dt(v):
    return None if v is None else datetime.fromisoformat(str(v).replace("Z", "+00:00"))


async def _seed_without_triggers(db_session: AsyncSession):
    """Suppress the reservation<->maintenance overlap trigger while seeding.

    These vectors exercise the effective-status DERIVATION over arbitrary
    coexisting rows (e.g. an ACTIVE reservation AND an ACTIVE maintenance on the
    same vehicle — the "maintenance wins" precedence case). PostgreSQL's
    `check_reservation_maintenance_overlap` trigger legitimately blocks BOOKING
    over maintenance in production, but here we need the raw state to test the
    derivation, so bypass it for the fixture only (no-op on SQLite)."""
    from sqlalchemy import text
    try:
        await db_session.execute(text("SET session_replication_role = replica"))
    except Exception:
        pass


async def _restore_triggers(db_session: AsyncSession):
    from sqlalchemy import text
    try:
        await db_session.execute(text("SET session_replication_role = origin"))
    except Exception:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _CASES["cases"], ids=lambda c: c["name"])
async def test_backend_matches_reference(case, db_session: AsyncSession):
    await _seed_without_triggers(db_session)
    idmap: dict[str, object] = {}
    for v in case["vehicles"]:
        vid = uuid4()
        idmap[v["id"]] = vid
        db_session.add(Vehicle(
            id=vid, brand="T", model="A", registration=f"X-{vid.hex[:8]}",
            vin=f"VIN{vid.hex[:14]}", year=2026, color="Noir",
            fuel_type="GASOLINE", transmission="AUTOMATIC",
            daily_rental_price=10, status=v["status"],
        ))
    await db_session.flush()

    for r in case["reservations"]:
        db_session.add(Reservation(
            id=uuid4(), vehicle_id=idmap[r["vehicle_id"]], status=r["status"],
            start_datetime=_dt(r["start"]), end_datetime=_dt(r["end"]),
            customer_name="X", customer_phone="1", daily_price=10, num_days=1,
            total_price=10, deposit=0,
        ))
    for m in case["maintenances"]:
        db_session.add(Maintenance(
            id=uuid4(), vehicle_id=idmap[m["vehicle_id"]], type="X",
            status=m["status"], start_datetime=_dt(m["start"]),
            expected_end_datetime=_dt(m.get("expected_end")),
            actual_end_datetime=_dt(m.get("actual_end")),
        ))
    await db_session.commit()
    await _restore_triggers(db_session)

    want_eff = ref_effective(case["vehicles"], case["reservations"],
                             case["maintenances"], _NOW)
    want_cnt = ref_counts(case["vehicles"], case["reservations"],
                          case["maintenances"], _NOW)

    # sanity: the JSON's checked-in expectations equal the reference
    assert want_eff == case["expected_effective"]
    for k, v in case["expected_counts"].items():
        assert want_cnt[k] == v

    # sanity: expected_next_boundary in the shared vectors equals the reference
    # (the value Mobile's FleetStatus.nextBoundaryMillis is asserted against).
    want_nb = ref_next_boundary(case["reservations"], case["maintenances"], _NOW)
    want_nb_iso = None if want_nb is None else want_nb.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert want_nb_iso == case.get("expected_next_boundary"), (
        f"{case['name']}: expected_next_boundary drift {want_nb_iso} != "
        f"{case.get('expected_next_boundary')}"
    )

    got_eff_raw = await compute_effective_statuses(db_session, now=_NOW)
    got_eff = {src: got_eff_raw[str(uuid)] for src, uuid in idmap.items()}
    assert got_eff == want_eff, f"{case['name']}: backend effective_status drift"

    got_cnt = await compute_fleet_counts(db_session, now=_NOW)
    for k in ("total_vehicles", "available", "reserved", "rented", "maintenance"):
        assert got_cnt[k] == want_cnt[k], (
            f"{case['name']}: backend count '{k}' {got_cnt[k]} != spec {want_cnt[k]}"
        )
