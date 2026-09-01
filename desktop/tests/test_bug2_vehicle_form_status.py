"""BUG 2 — editing a vehicle and setting a "maintenance" status did nothing.

Root cause: the vehicle form let the user pick RENTED / RESERVED /
MAINTENANCE as a raw `vehicle.status` column value. Those states are
DERIVED from reservation & maintenance records (Phase 4 canonical rule), so
setting the column had no visible effect (and previously produced
cross-view contradictions).

Fix: the vehicle form exposes only the structural states
(AVAILABLE / SOLD / INACTIVE). Sending a vehicle to maintenance is done
through the Maintenance module, which DOES propagate live.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from PySide6.QtWidgets import QApplication

from app.database import init_local_db, get_local_session
from app.models.vehicle import LocalVehicle
from app.models.maintenance import LocalMaintenance
from app.ui.vehicles.vehicle_form import VehicleFormDialog
from app.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def clean_db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _combo_values(dlg):
    return [dlg._status.itemData(i) for i in range(dlg._status.count())]


def test_form_only_offers_structural_statuses(qapp):
    dlg = VehicleFormDialog()
    assert _combo_values(dlg) == ["AVAILABLE", "SOLD", "INACTIVE"]
    assert "MAINTENANCE" not in _combo_values(dlg)
    assert "RESERVED" not in _combo_values(dlg)
    dlg.deleteLater()


def test_editing_reserved_vehicle_shows_available_not_derived(qapp):
    dlg = VehicleFormDialog(vehicle_data={"id": "v1", "registration": "R1",
                                          "brand": "T", "model": "C", "status": "RESERVED"})
    # A derived value collapses to the structural default in the form.
    assert dlg._status.currentData() == "AVAILABLE"
    dlg.deleteLater()


def test_editing_sold_vehicle_keeps_sold(qapp):
    dlg = VehicleFormDialog(vehicle_data={"id": "v1", "registration": "R1",
                                          "brand": "T", "model": "C", "status": "SOLD"})
    assert dlg._status.currentData() == "SOLD"
    dlg.deleteLater()


def test_form_save_payload_cannot_carry_maintenance(qapp):
    dlg = VehicleFormDialog(vehicle_data={
        "id": "v1", "registration": "R1", "vin": "1HGCM82633A004352",
        "brand": "T", "model": "C", "status": "MAINTENANCE"})
    dlg._reg.setText("R1"); dlg._vin.setText("1HGCM82633A004352")
    dlg._brand.setText("T"); dlg._model.setText("C")
    captured = {}
    dlg.saved.connect(lambda d: captured.update(d))
    dlg._save()
    assert captured, "form should have emitted saved"
    assert captured.get("status") in ("AVAILABLE", "SOLD", "INACTIVE")
    assert captured.get("status") != "MAINTENANCE"
    dlg.deleteLater()


def test_maintenance_module_flow_updates_all_views_live(qapp, request):
    """The SUPPORTED way to send a vehicle to maintenance DOES propagate
    immediately to every view with no tab switch / refresh / sync."""
    s = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    s.add(LocalVehicle(id="v9", registration="R9", vin="VIN9", brand="T", model="C",
                       year=2024, color="N", fuel_type="D", transmission="A",
                       status="AVAILABLE", created_at=now, updated_at=now, version=1))
    s.commit(); s.close()

    w = MainWindow(user_data={"user_id": "u", "role": "ADMIN", "full_name": "A",
                              "access_token": "x", "refresh_token": "x", "offline": True})
    request.addfinalizer(lambda: (w.close(), w.deleteLater(), qapp.processEvents()))
    w._run_sync = lambda *a, **k: None

    iso = lambda d: (datetime.now(timezone.utc) + timedelta(days=d)).isoformat()
    w._create_maintenance_record({
        "vehicle_id": "v9", "type": "Entretien",
        "start_datetime": iso(-1), "expected_end_datetime": iso(2),
        "status": "ACTIVE", "parts": [],
    })

    w._load_vehicles_from_local()
    row = next(v for v in w._vehicle_list._vehicles_data if v["id"] == "v9")
    assert row["status"] == "MAINTENANCE"

    from app.sync.dashboard_cache import compute_local_overview
    ov = compute_local_overview()
    assert ov["maintenance"] == 1 and ov["available"] == 0
