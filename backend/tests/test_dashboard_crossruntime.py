"""
Dashboard cross-runtime parity — the backend DTO and the desktop offline DTO
must be the SAME payload for the same data at the same instant.

Both runtimes are thin ports over ``shared/dashboard_reference.build_snapshot``;
this test proves the ports themselves agree, so "the desktop shows a different
number than the server" cannot come back as a silent regression. It is the
dashboard-level companion to ``test_revenue_crossruntime`` and
``test_fleet_status_crossruntime``.
"""
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.maintenance import Maintenance
from app.models.reservation import Reservation
from app.models.vehicle import Vehicle
from app.services.dashboard_snapshot import _load_rows, build_dashboard_snapshot
from shared.dashboard_reference import build_snapshot

TZ = ZoneInfo("Africa/Casablanca")
NOW = datetime(2026, 9, 5, 14, 0, tzinfo=TZ)


def _desktop_rows(vehicles, reservations, maintenances):
    """Re-shape the backend's rows the way ``DomainStore`` hands them to the
    desktop port: the vehicle dict carries the DERIVED status in ``status``
    and the persisted column in ``raw_status``."""
    return (
        [{"id": v["id"], "status": "RENTED", "raw_status": v["status"],
          "registration": v["registration"], "brand": v["brand"], "model": v["model"]}
         for v in vehicles],
        [dict(r) for r in reservations],
        [dict(m) for m in maintenances],
    )


def _desktop_module():
    """Load the desktop port by path.

    It cannot be imported as ``app.sync.dashboard_snapshot`` here: the name
    ``app`` is already bound to the BACKEND package in this process. Loading it
    under a private name proves the two ports really are separate modules that
    nonetheless produce the same DTO. The module only depends on ``shared``, so
    no desktop package machinery is needed.
    """
    import importlib.util
    import pathlib
    import sys

    name = "_desktop_dashboard_snapshot"
    if name in sys.modules:
        return sys.modules[name]
    path = (pathlib.Path(__file__).resolve().parents[2]
            / "desktop" / "app" / "sync" / "dashboard_snapshot.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Snap:
    def __init__(self, vehicles, reservations, maintenances):
        self.vehicles = tuple(vehicles)
        self.reservations = tuple(reservations)
        self.maintenances = tuple(maintenances)


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


async def _res(db, veh, start, days, total, status="RESERVED"):
    r = Reservation(
        vehicle_id=veh.id, customer_name="T", start_datetime=start,
        end_datetime=start + timedelta(days=days), daily_price=total / days,
        num_days=days, total_price=total, deposit=0, status=status,
        payment_status="PAID", created_by=None,
    )
    db.add(r)
    await db.commit()
    return r


@pytest.mark.asyncio
async def test_backend_and_desktop_snapshots_are_identical(db_session):
    """A mixed fleet: rented, reserved, in maintenance, free, sold, plus
    completed and cancelled history."""
    build_local_snapshot = _desktop_module().build_local_snapshot

    v_ready = await _veh(db_session, "PAR-READY")
    v_rented = await _veh(db_session, "PAR-RENT")
    v_reserved = await _veh(db_session, "PAR-RESV")
    v_maint = await _veh(db_session, "PAR-MAINT")
    await _veh(db_session, "PAR-SOLD", status="SOLD")

    await _res(db_session, v_rented, NOW - timedelta(days=2), 5, 1500.0)
    await _res(db_session, v_reserved, NOW + timedelta(days=4), 3, 900.0)
    await _res(db_session, v_ready, NOW - timedelta(days=30), 4, 800.0, "COMPLETED")
    await _res(db_session, v_ready, NOW - timedelta(days=20), 2, 400.0, "CANCELLED")
    db_session.add(Maintenance(
        vehicle_id=v_maint.id, type="REPAIR", description="d",
        start_datetime=NOW - timedelta(hours=6),
        expected_end_datetime=NOW + timedelta(days=2), status="IN_PROGRESS",
    ))
    await db_session.commit()

    backend_dto = await build_dashboard_snapshot(db_session, period="month", now=NOW)

    vehicles, reservations, maintenances = await _load_rows(db_session)
    snap = _Snap(*_desktop_rows(vehicles, reservations, maintenances))
    desktop_dto = build_local_snapshot(snap, period="month", now=NOW)

    # The only legitimate difference is the provenance stamp.
    assert desktop_dto.pop("source") == "local"
    assert backend_dto.pop("source") == "server"
    assert desktop_dto == backend_dto

    # And the picture itself is the expected one.
    assert backend_dto["vehicles"]["ready_to_rent"] == 2
    assert backend_dto["vehicles"]["active_rental"] == 1
    assert backend_dto["vehicles"]["maintenance"] == 1
    assert backend_dto["vehicles"]["excluded_structural"] == 1
    assert backend_dto["integrity"]["ok"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("period", ["today", "yesterday", "week", "last_week",
                                    "month", "last_month", "year", "last_year"])
async def test_every_period_agrees_across_runtimes(db_session, period):
    build_local_snapshot = _desktop_module().build_local_snapshot

    v = await _veh(db_session, f"PER-{period[:5]}")
    await _res(db_session, v, NOW - timedelta(days=200), 300, 60000.0, "COMPLETED")

    backend_dto = await build_dashboard_snapshot(db_session, period=period, now=NOW)
    vehicles, reservations, maintenances = await _load_rows(db_session)
    snap = _Snap(*_desktop_rows(vehicles, reservations, maintenances))
    desktop_dto = build_local_snapshot(snap, period=period, now=NOW)

    assert desktop_dto["revenue"] == backend_dto["revenue"], period
    assert desktop_dto["periods"] == backend_dto["periods"], period
    assert desktop_dto["vehicles"] == backend_dto["vehicles"], period
    assert desktop_dto["top_vehicles"] == backend_dto["top_vehicles"], period


@pytest.mark.asyncio
async def test_the_shared_spec_is_the_only_implementation(db_session):
    """The backend port must add nothing of its own: feeding its rows straight
    to the spec produces the identical DTO."""
    v = await _veh(db_session, "SPEC-1")
    await _res(db_session, v, NOW - timedelta(days=1), 3, 900.0)

    via_port = await build_dashboard_snapshot(db_session, period="week", now=NOW)
    vehicles, reservations, maintenances = await _load_rows(db_session)
    via_spec = build_snapshot(vehicles, reservations, maintenances,
                              period="week", now=NOW, source="server")
    assert via_port == via_spec
