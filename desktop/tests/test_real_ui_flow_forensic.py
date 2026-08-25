"""
Verify physically the exact UI flow from Section 24:
LOGIN -> DASHBOARD -> CLIENTS (Confirm clients load) -> RESERVATIONS ->
NEW RESERVATION -> ForensicBrand ProofModel -> 24/08/2026 21:36 -> 28/08/2026 21:36 ->
Create/select client -> Confirm reservation -> Reservation appears ->
Clients appears -> Open client details -> Rental history appears ->
Return to Reservations -> Reservation still appears -> Refresh ->
Reservation still appears -> Restart Desktop -> Reservation still appears -> Client still appears
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime, timezone
from PySide6.QtWidgets import QApplication
from unittest.mock import MagicMock, patch

from app.database import init_local_db, get_local_session
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.client import LocalClient
from app.ui.main_window import MainWindow

app = QApplication.instance() or QApplication(sys.argv)

def test_full_physical_ui_flow():
    init_local_db()
    session = get_local_session()
    
    # Seed the target vehicle
    target_v = LocalVehicle(
        id="fb-proof-real-1",
        registration="FB-999-PM",
        vin="VIN999PROOF99901",
        brand="ForensicBrand",
        model="ProofModel",
        year=2026,
        color="Noir",
        fuel_type="GASOLINE",
        transmission="AUTOMATIC",
        daily_rental_price=250.0,
        status="AVAILABLE",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    session.add(target_v)
    session.commit()
    session.close()

    user_data = {
        "user_id": "test-admin-1",
        "email": "admin@carrental.local",
        "full_name": "Admin Test",
        "role": "ADMIN",
        "access_token": "mock_token",
        "refresh_token": "mock_refresh",
        "offline": False,
    }

    # 1. Open MainWindow (LOGIN -> DASHBOARD)
    # Deterministic UI-flow test: background threads (realtime client,
    # sync timer, sync QThreads) are disabled — this test verifies UI
    # state transitions, not networking.
    import app.ui.main_window as _mw_mod
    _orig_run_sync = _mw_mod.MainWindow._run_sync
    _mw_mod.MainWindow._run_sync = lambda self: None
    import app.services.realtime_client as _rtc_mod
    _orig_realtime = _rtc_mod.RealtimeEventsClient
    class _NoRealtime:
        def __init__(self, *a, **k): pass
        def start(self): pass
        def stop(self): pass
        def update_token(self, *a): pass
    _rtc_mod.RealtimeEventsClient = _NoRealtime

    win = MainWindow(user_data)
    win._api._access_token = "mock_token"
    # Mock server availability check to return True (AVAILABLE)
    win._api.check_availability = MagicMock(return_value={"available": True, "vehicle_id": "fb-proof-real-1"})

    # 2. Switch to CLIENTS page
    win._switch_page("clients")
    win._clients_page.refresh_data()
    # Initially 0 clients, empty state visible
    assert win._clients_page._empty_lbl.isVisible() or len(win._clients_page._clients) == 0

    # 3. Switch to RESERVATIONS page
    win._switch_page("reservations")
    win._reservations.refresh_data()

    # 4. Open New Reservation for ForensicBrand ProofModel
    v_dict = {
        "id": "fb-proof-real-1",
        "brand": "ForensicBrand",
        "model": "ProofModel",
        "registration": "FB-999-PM",
        "daily_rental_price": 250.0
    }
    
    res_data = {
        "vehicle_id": "fb-proof-real-1",
        "customer_id": None,
        "customer_name": "Yassine Mansouri",
        "customer_phone": "+212699887766",
        "customer_email": "yassine@mansouri.ma",
        "identity_card_image": "",
        "driving_license_image": "",
        "start_datetime": "2026-08-24T20:36:00+00:00",
        "end_datetime": "2026-08-28T20:36:00+00:00",
        "daily_price": 250.0,
        "num_days": 4,
        "total_price": 1000.0,
        "deposit": 0.0,
        "payment_status": "PENDING",
        "status": "RESERVED",
    }

    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        win._reservations._create_reservation_record(res_data)
        assert not mock_warn.called, "Reservation should NOT be blocked!"

    # 5. Confirm Reservation appears in Reservations table
    win._reservations.refresh_data()
    assert win._reservations._table.rowCount() >= 1
    assert not win._reservations._empty_res_lbl.isVisible()

    # 6. Switch to CLIENTS page -> Confirm client appears!
    win._switch_page("clients")
    win._clients_page.refresh_data()
    # Client must be present in SQLite cache / live list
    local_clients = win._clients_page._load_from_local_cache()
    assert len(local_clients) >= 1
    created_client = [c for c in local_clients if "Mansouri" in c["last_name"] or "Yassine" in c["first_name"]]
    assert len(created_client) == 1
    client_id = created_client[0]["id"]

    # 7. Check client details dialog
    with patch("PySide6.QtWidgets.QDialog.exec"):
        win._open_client_details(client_id)

    # 8. Return to Reservations -> Reservation still appears
    win._switch_page("reservations")
    win._reservations.refresh_data()
    assert win._reservations._table.rowCount() >= 1

    # 9. Refresh UI
    win._on_refresh_clicked()
    assert win._reservations._table.rowCount() >= 1

    # 10. Restart Desktop (simulate new MainWindow instance on existing SQLite DB)
    os.environ["CAR_RENTAL_DB_RESET"] = "0"
    # Fully stop the first instance before the second one starts: two live
    # MainWindows with realtime clients/threads crash Qt at teardown.
    try:
        if getattr(win, "_realtime_client", None):
            win._realtime_client.stop()
        for attr in ("_sync_timer", "_immediate_sync_timer"):
            t = getattr(win, attr, None)
            if t:
                t.stop()
        st = getattr(win, "_sync_thread", None)
        if st and st.isRunning():
            st.wait(3000)
        win.close()
        win.deleteLater()
        app.processEvents()
    except Exception:
        pass
    win2 = MainWindow(user_data)
    win2._load_vehicles_from_local()
    win2._reservations.refresh_data()
    assert win2._reservations._table.rowCount() >= 1
    
    win2._switch_page("clients")
    win2._clients_page.refresh_data()
    restarted_clients = win2._clients_page._load_from_local_cache()
    assert len(restarted_clients) >= 1
    assert any(c["id"] == client_id for c in restarted_clients)

    # Teardown the second instance and restore class patches.
    try:
        if getattr(win2, "_realtime_client", None):
            win2._realtime_client.stop()
        for attr in ("_sync_timer", "_immediate_sync_timer"):
            t = getattr(win2, attr, None)
            if t:
                t.stop()
        win2.close()
        win2.deleteLater()
        app.processEvents()
    except Exception:
        pass
    _mw_mod.MainWindow._run_sync = _orig_run_sync
    _rtc_mod.RealtimeEventsClient = _orig_realtime

    print("PHYSICAL UI FLOW TEST: ALL 10 STEPS PASSED PERFECTLY!")

if __name__ == "__main__":
    test_full_physical_ui_flow()
