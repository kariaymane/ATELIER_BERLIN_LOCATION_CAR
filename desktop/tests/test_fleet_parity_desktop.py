"""Desktop single source of truth: the Dashboard fleet counts
(compute_local_overview) are computed by the SAME helper as the Vehicles page
(MainWindow._load_vehicles_from_local), so they can never disagree.
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
from app.utils.fleet_status import compute_fleet_counts

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def clean_db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _seed():
    s = get_local_session()
    def v(vid, status="AVAILABLE"):
        s.add(LocalVehicle(
            id=vid, brand="T", model="A", registration=f"P-{vid}", vin=f"{vid}xxxxxxxxxxxxx"[:17],
            year=2026, color="N", fuel_type="Diesel", transmission="Manual",
            status=status, daily_rental_price=1,
            created_at=NOW.isoformat(), updated_at=NOW.isoformat(), version=1))
    def r(vid, status, s0, e0):
        s.add(LocalReservation(
            id=f"r-{vid}-{status}", vehicle_id=vid, customer_name="X",
            start_datetime=s0.isoformat(), end_datetime=e0.isoformat(),
            daily_price=1, num_days=1, total_price=1, deposit=0, status=status,
            created_at=NOW.isoformat(), updated_at=NOW.isoformat(), version=1))
    def m(vid, s0, e0):
        s.add(LocalMaintenance(
            id=f"m-{vid}", vehicle_id=vid, type="X", status="ACTIVE",
            start_datetime=s0.isoformat(),
            expected_end_datetime=e0.isoformat() if e0 else None,
            created_at=NOW.isoformat(), updated_at=NOW.isoformat(), version=1))
    v("av")
    v("rs"); r("rs", "RESERVED", NOW - timedelta(hours=1), NOW + timedelta(days=2))
    v("rt"); r("rt", "ACTIVE", NOW - timedelta(hours=1), NOW + timedelta(days=2))
    v("mt"); m("mt", NOW - timedelta(hours=1), NOW + timedelta(days=2))
    v("open"); m("open", NOW - timedelta(hours=1), None)         # open-ended
    v("both"); r("both", "ACTIVE", NOW - timedelta(hours=1), NOW + timedelta(days=2)); m("both", NOW - timedelta(hours=1), NOW + timedelta(days=2))
    v("sold", status="SOLD")
    v("future"); r("future", "RESERVED", NOW + timedelta(days=5), NOW + timedelta(days=7))
    s.commit()
    s.close()


def test_dashboard_counts_equal_vehicle_effective_tally(qapp, request):
    _seed()
    from app.ui.main_window import MainWindow
    w = MainWindow(user_data={"user_id": "u", "access_token": "", "offline": True})
    request.addfinalizer(lambda: (w.close(), w.deleteLater(), qapp.processEvents()))

    captured = []
    w._vehicle_list.load_vehicles = lambda vs: captured.extend(vs)
    w._load_vehicles_from_local()

    tally = {"AVAILABLE": 0, "RESERVED": 0, "RENTED": 0, "MAINTENANCE": 0}
    for v in captured:
        if v["status"] in tally:
            tally[v["status"]] += 1

    ov = compute_local_overview()
    assert ov["available"] == tally["AVAILABLE"]
    assert ov["reserved"] == tally["RESERVED"]
    assert ov["rented"] == tally["RENTED"]
    assert ov["maintenance"] == tally["MAINTENANCE"]
    assert ov["active_maintenances"] == ov["maintenance"]
    assert ov["available"] + ov["reserved"] + ov["rented"] + ov["maintenance"] == ov["total_vehicles"]


def test_expected_bucket_values(qapp):
    _seed()
    s = get_local_session()
    try:
        c = compute_fleet_counts(s)
    finally:
        s.close()
    assert c["total_vehicles"] == 7          # 8 minus SOLD
    assert c["available"] == 1               # av
    assert c["reserved"] == 1                # future (starts in 5 days)
    assert c["rented"] == 2                  # rs (RESERVED status, started) + rt (ACTIVE)
    assert c["maintenance"] == 3             # mt + open + both (maintenance wins)
