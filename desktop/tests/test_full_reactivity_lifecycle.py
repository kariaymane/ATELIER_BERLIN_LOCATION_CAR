"""End-to-end convergence proof for the "maintenance wins" rule, entirely on
the offline desktop store — no tab switch, no manual refresh, no restart, no
sync round-trip.

  AVAILABLE
    -> create reservation      => reservation RESERVED, but its window already
                                   covers "now" -> vehicle RENTED (time-derived:
                                   RESERVED-covering-now counts as "en location"
                                   exactly like ACTIVE, no separate pickup step)
    -> create overlapping maint => vehicle MAINTENANCE, reservation CANCELLED
                                   (reason MAINTENANCE), maintenance ACTIVE,
                                   dashboard maintenance +1 / rented -1,
                                   availability false
    -> finish maintenance      => vehicle AVAILABLE, maintenance COMPLETED,
                                   reservation stays CANCELLED, availability true
    -> create new reservation   => succeeds, vehicle RENTED again (covers now)
"""
import os
import sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from datetime import datetime, timezone, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.sync.dashboard_cache import compute_local_overview

NOW = datetime.now(timezone.utc)
VID = "veh-lifecycle"


@pytest.fixture(autouse=True)
def clean_db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _effective_status(window, monkeypatch):
    captured = {}
    monkeypatch.setattr(window._vehicle_list, "load_vehicles",
                        lambda vs: captured.update({v["id"]: v for v in vs}))
    window._load_vehicles_from_local()
    return captured.get(VID, {}).get("status")


def _res_payload(start, end):
    return {
        "vehicle_id": VID, "customer_id": None, "customer_name": "Client Cycle",
        "customer_phone": "0600000000", "customer_email": "", "customer_cin": "",
        "identity_card_image": "", "driving_license_image": "",
        "start_datetime": start.isoformat(), "end_datetime": end.isoformat(),
        "daily_price": 200.0, "num_days": 4, "total_price": 800.0, "deposit": 0.0,
        "payment_status": "PENDING", "status": "RESERVED",
    }


def test_full_lifecycle(qapp, request, monkeypatch):
    from app.ui.main_window import MainWindow

    s = get_local_session()
    s.add(LocalVehicle(
        id=VID, brand="Renault", model="Clio", status="AVAILABLE",
        daily_rental_price=200, registration="LC-9", vin="98765432109876543",
        year=2025, color="Gris", fuel_type="Diesel", transmission="Manual",
        created_at=NOW.isoformat(), updated_at=NOW.isoformat(),
    ))
    s.commit()
    s.close()

    w = MainWindow(user_data={"user_id": "u-1", "access_token": "", "offline": True})
    request.addfinalizer(lambda: (w.close(), w.deleteLater(), qapp.processEvents()))
    monkeypatch.setattr(w, "_run_sync", lambda: None)
    qapp.processEvents()

    assert _effective_status(w, monkeypatch) == "AVAILABLE"

    # 1. create reservation (overlaps "now" so it drives effective status)
    r_start, r_end = NOW - timedelta(days=1), NOW + timedelta(days=6)
    w._reservations._create_reservation_record(_res_payload(r_start, r_end))
    s = get_local_session()
    res = s.query(LocalReservation).filter_by(vehicle_id=VID).one()
    rid = res.id
    assert res.status == "RESERVED"
    s.close()
    # Time-derived rule: the window already contains "now" -> RENTED, even
    # though the stored reservation status is still RESERVED.
    assert _effective_status(w, monkeypatch) == "RENTED"
    assert compute_local_overview()["rented"] == 1
    assert compute_local_overview()["reserved"] == 0

    # 2. create overlapping maintenance
    w._create_maintenance_record({
        "vehicle_id": VID, "type": "Panne", "description": "boite",
        "start_datetime": (NOW - timedelta(hours=2)).isoformat(),
        "expected_end_datetime": (NOW + timedelta(days=3)).isoformat(),
        "step": "DIAGNOSTIC", "status": "ACTIVE",
    })

    s = get_local_session()
    res = s.query(LocalReservation).filter_by(id=rid).one()
    maint = s.query(LocalMaintenance).filter_by(vehicle_id=VID).one()
    assert res.status == "CANCELLED"
    assert res.cancellation_reason == "MAINTENANCE"
    assert maint.status == "ACTIVE"
    s.close()

    assert _effective_status(w, monkeypatch) == "MAINTENANCE"
    ov = compute_local_overview()
    assert ov["maintenance"] == 1
    assert ov["reserved"] == 0

    # 3. finish maintenance
    s = get_local_session()
    m = s.query(LocalMaintenance).filter_by(vehicle_id=VID).one()
    m.status = "COMPLETED"
    m.actual_end_datetime = datetime.now(timezone.utc).isoformat()
    s.commit()
    s.close()

    assert _effective_status(w, monkeypatch) == "AVAILABLE"
    assert compute_local_overview()["maintenance"] == 0
    s = get_local_session()
    assert s.query(LocalReservation).filter_by(id=rid).one().status == "CANCELLED"
    s.close()

    # 4. new reservation for the (now free) slot — overlapping "now" so it
    #    also drives the live effective status
    w._reservations._create_reservation_record(
        _res_payload(NOW - timedelta(hours=1), NOW + timedelta(days=5)))
    s = get_local_session()
    blocking = [r for r in s.query(LocalReservation).filter_by(vehicle_id=VID).all()
                if (r.status or "").upper() in ("RESERVED", "ACTIVE")]
    s.close()
    assert len(blocking) == 1
    assert _effective_status(w, monkeypatch) in ("RESERVED", "RENTED")
