"""Regression: effective vehicle status must be DERIVED live and never
"stick" after a maintenance / reservation is finished or cancelled.

Root cause covered: a vehicle row whose persisted ``status`` was pulled back
from the server as ``MAINTENANCE`` / ``RENTED`` / ``RESERVED`` used to remain
in that state in the Vehicles view even once the underlying maintenance or
reservation ended, until a full sync round-trip corrected the base column.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from PySide6.QtWidgets import QApplication

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.maintenance import LocalMaintenance
from app.models.reservation import LocalReservation
from app.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def clean_db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _iso(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _mk_vehicle(session, vid, status):
    now = datetime.now(timezone.utc).isoformat()
    session.add(LocalVehicle(
        id=vid, registration=f"REG-{vid}", vin=f"VIN{vid}", brand="T", model="C",
        year=2024, color="Noir", fuel_type="Diesel", transmission="Auto",
        status=status, created_at=now, updated_at=now, version=1,
    ))


def _statuses(window):
    window._load_vehicles_from_local()
    return {v["id"]: v["status"] for v in window._vehicle_list._vehicles_data}


def test_stale_maintenance_base_status_does_not_stick(qapp):
    session = get_local_session()
    _mk_vehicle(session, "v1", "MAINTENANCE")  # stale flag pulled from server
    # maintenance already completed -> nothing active
    now = datetime.now(timezone.utc).isoformat()
    session.add(LocalMaintenance(
        id="m1", vehicle_id="v1", type="Entretien",
        start_datetime=_iso(-5), expected_end_datetime=_iso(-4),
        actual_end_datetime=_iso(-4), status="COMPLETED", step="TERMINE",
        created_at=now, updated_at=now, version=1,
    ))
    session.commit()
    session.close()

    window = MainWindow(user_data={"user_id": "u1", "access_token": "x", "offline": True})
    assert _statuses(window)["v1"] == "AVAILABLE"
    window.deleteLater()


def test_active_maintenance_still_shows_maintenance(qapp):
    session = get_local_session()
    _mk_vehicle(session, "v2", "AVAILABLE")
    now = datetime.now(timezone.utc).isoformat()
    session.add(LocalMaintenance(
        id="m2", vehicle_id="v2", type="Entretien",
        start_datetime=_iso(-1), expected_end_datetime=_iso(1),
        status="ACTIVE", step="REPARATION",
        created_at=now, updated_at=now, version=1,
    ))
    session.commit()
    session.close()

    window = MainWindow(user_data={"user_id": "u1", "access_token": "x", "offline": True})
    assert _statuses(window)["v2"] == "MAINTENANCE"
    window.deleteLater()


def test_structural_status_preserved(qapp):
    session = get_local_session()
    _mk_vehicle(session, "v3", "SOLD")
    _mk_vehicle(session, "v4", "INACTIVE")
    session.commit()
    session.close()

    window = MainWindow(user_data={"user_id": "u1", "access_token": "x", "offline": True})
    st = _statuses(window)
    assert st["v3"] == "SOLD"
    assert st["v4"] == "INACTIVE"
    window.deleteLater()


def test_cancelled_reservation_frees_vehicle_immediately(qapp):
    session = get_local_session()
    _mk_vehicle(session, "v5", "RESERVED")  # stale server flag
    now = datetime.now(timezone.utc).isoformat()
    session.add(LocalReservation(
        id="r5", vehicle_id="v5", customer_name="X",
        start_datetime=_iso(-1), end_datetime=_iso(2),
        daily_price=100.0, num_days=3, total_price=300.0, deposit=0,
        status="CANCELLED", payment_status="PENDING",
        created_at=now, updated_at=now, version=1,
    ))
    session.commit()
    session.close()

    window = MainWindow(user_data={"user_id": "u1", "access_token": "x", "offline": True})
    assert _statuses(window)["v5"] == "AVAILABLE"
    window.deleteLater()
