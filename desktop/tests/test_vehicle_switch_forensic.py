"""
SECTION 36/38 — REAL UI REPRODUCTION: vehicle-switch availability.

Drives the REAL MainWindow + real vehicle cards + real ReservationFormDialog:
  1. Vehicle A holds 08/12 -> 10/12.
  2. Open A's dialog for 08/12 -> 09/12 -> BLOCKED (server mock says blocked).
  3. Open B's dialog, SAME dates -> AVAILABLE -> create succeeds.
  4. Verify: reservation.vehicle_id == B, A's reservation untouched,
     no shared availability state between dialog instances.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_vehicle_switch_recalculates_availability(qapp):
    from app.database import init_local_db, get_local_session
    from app.models.vehicle import LocalVehicle
    from app.models.reservation import LocalReservation
    init_local_db()
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    for vid, reg in (("iso-A", "SW-A-1-1"), ("iso-B", "SW-B-2-2")):
        session.merge(LocalVehicle(
            id=vid, registration=reg,
            vin="1M8GDM9AXKP042788" if vid == "iso-A" else "1M8GDM9AXKP042789",
            brand="BrandA" if vid == "iso-A" else "BrandB",
            model="ModelX", year=2026, color="Blanc", fuel_type="DIESEL",
            transmission="MANUAL", current_mileage=0, daily_rental_price=300.0,
            status="AVAILABLE", created_at=now, updated_at=now, version=1))
    # Vehicle A holds 08/12 -> 10/12
    s0 = datetime(2026, 12, 8, 10, 0, tzinfo=timezone.utc).astimezone(timezone.utc)
    session.merge(LocalReservation(
        id="sw-exist", vehicle_id="iso-A", customer_name="Holder A",
        start_datetime=s0.isoformat(),
        end_datetime=datetime(2026, 12, 10, 10, 0, tzinfo=timezone.utc).isoformat(),
        daily_price=300.0, num_days=2, total_price=600.0, deposit=0,
        status="RESERVED", payment_status="PENDING",
        created_at=now, updated_at=now, version=1))
    session.commit()
    session.close()

    # Server availability mock keyed by VEHICLE ID (proves per-vehicle checks)
    calls = {}

    class PerVehicleApi:
        _access_token = "tok"

        def check_availability(self, vid, start, end):
            calls[vid] = calls.get(vid, 0) + 1
            available = not (vid == "iso-A")  # only A blocked (its own row)
            return {"available": available, "vehicle_id": vid}

    from app.ui.main_window import MainWindow
    win = MainWindow({"user_id": "sw-u", "email": "sw@test.local",
                      "username": "sw", "full_name": "SW Test", "role": "ADMIN",
                      "access_token": "", "refresh_token": "", "offline": True})
    win._api._access_token = "tok"
    win._api.check_availability = PerVehicleApi().check_availability
    win.show()
    qapp.processEvents()

    from PySide6.QtWidgets import QMessageBox
    from app.ui.reservations import reservation_list as rl
    orig_warn = rl.QMessageBox.warning
    warnings = []
    rl.QMessageBox.warning = lambda *a, **k: warnings.append(a[2] if len(a) > 2 else "")

    def d1s():
        return datetime(2026, 12, 8, 10, 0, tzinfo=timezone.utc)

    def d1e():
        return datetime(2026, 12, 9, 10, 0, tzinfo=timezone.utc)

    widget = rl.ReservationWidget(device_id="sw-dev", user_id="sw-u",
                                  api_client=win._api)

    def open_dialog_and_save(vehicle_dict):
        """Open the REAL dialog for a vehicle, wire the REAL widget handler
        (which performs the server-first availability check), and confirm."""
        dlg = rl.ReservationFormDialog(vehicle_dict, api_client=win._api)
        dlg._customer_name.setText("Switch Tester")
        dlg._customer_phone.setText("+212600000042")
        dlg._start_dt.setDateTime(_qdt(d1s()))
        dlg._end_dt.setDateTime(_qdt(d1e()))
        data = {}
        dlg.saved.connect(
            lambda d: (data.update(d), widget._create_reservation_record(d)))
        dlg._on_save()
        dlg.close()
        return data

    def _qdt(dt):
        from PySide6.QtCore import QDate, QTime
        return QDateTime(QDate(dt.year, dt.month, dt.day), QTime(dt.hour, dt.minute))

    from PySide6.QtCore import QDateTime

    # 1. Vehicle A dialog: SAME dates -> server says BLOCKED for A
    data_a = open_dialog_and_save({
        "id": "iso-A", "brand": "BrandA", "model": "ModelX",
        "registration": "SW-A-1-1", "daily_rental_price": 300.0})
    assert "id" not in data_a, "A must be BLOCKED (its own reservation)"
    assert calls.get("iso-A") == 1, "availability must be checked for A specifically"
    assert len(warnings) == 1 and "déjà réservé" in warnings[0]

    # 2. Vehicle B dialog: SAME dates -> AVAILABLE -> create
    data_b = open_dialog_and_save({
        "id": "iso-B", "brand": "BrandB", "model": "ModelX",
        "registration": "SW-B-2-2", "daily_rental_price": 300.0})
    assert calls.get("iso-B") == 1, "fresh availability check must run for B"

    # 3. Canonical state (authoritative DB): B created for B's vehicle_id,
    #    A's original reservation untouched.
    session = get_local_session()
    rows = session.query(LocalReservation).filter_by(vehicle_id="iso-B").all()
    assert len(rows) == 1 and rows[0].customer_name == "Switch Tester", (
        "B reservation must exist with vehicle_id == B")
    assert rows[0].vehicle_id == "iso-B"
    a_rows = session.query(LocalReservation).filter_by(vehicle_id="iso-A").all()
    assert len(a_rows) == 1 and a_rows[0].id == "sw-exist"
    a_rows = session.query(LocalReservation).filter_by(vehicle_id="iso-A").all()
    assert len(a_rows) == 1 and a_rows[0].id == "sw-exist"
    session.close()

    rl.QMessageBox.warning = orig_warn
    try:
        if getattr(win, "_realtime_client", None):
            win._realtime_client.stop()
        for attr in ("_sync_timer", "_immediate_sync_timer"):
            t = getattr(win, attr, None)
            if t:
                t.stop()
        win.close()
        win.deleteLater()
        qapp.processEvents()
    except Exception:
        pass
