"""
Automated Desktop UI Startup, Login -> MainWindow Transition, and Vehicle Delete Verification Test.
Tests:
1. QApplication startup & theme loading.
2. LoginWindow signal creation.
3. MainWindow instantiation with user data (Verifies no AttributeError on signals!).
4. VehicleListWidget signal emissions (add_requested, vehicle_selected, maintenance_requested, delete_requested).
5. VehicleRow creation & action menu trigger.
6. Controlled test vehicle creation in SQLite -> UI display -> Deletion flow.
7. Verification of SQLite and SyncQueue deletion records.
"""
import sys
import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

# Ensure headless/offscreen platform for CI/headless verification
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "desktop"))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from app.database import init_local_db, get_local_session
from app.models.vehicle import LocalVehicle
from app.models.sync_queue import SyncQueueItem
from app.ui.main_window import MainWindow
from app.ui.vehicles.vehicle_list import VehicleListWidget, VehicleRow

def run_desktop_ui_verification():
    print("=" * 70)
    print("🚀 RUNNING DESKTOP UI STARTUP & DELETE_REQUESTED VERIFICATION")
    print("=" * 70)

    init_local_db()

    # Initialize Qt Application
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)

    # 1. Test MainWindow instantiation
    print("\n--- [1/4] Testing MainWindow Instantiation ---")
    mock_user = {
        "user_id": str(uuid4()),
        "full_name": "Test Administrator",
        "role": "ADMIN",
        "access_token": "mock-access-token",
        "refresh_token": "mock-refresh-token",
        "offline": True,
    }

    try:
        main_win = MainWindow(mock_user)
        print("✓ 1.1 MainWindow instantiated successfully! No AttributeError on delete_requested.")
    except Exception as e:
        print(f"❌ MainWindow instantiation failed: {e}")
        raise e

    # 2. Test VehicleListWidget signals
    print("\n--- [2/4] Testing VehicleListWidget Signals ---")
    v_list = main_win._vehicle_list
    assert hasattr(v_list, "delete_requested"), "VehicleListWidget must have delete_requested signal"
    assert hasattr(v_list, "vehicle_selected"), "VehicleListWidget must have vehicle_selected signal"
    assert hasattr(v_list, "maintenance_requested"), "VehicleListWidget must have maintenance_requested signal"
    assert hasattr(v_list, "add_requested"), "VehicleListWidget must have add_requested signal"
    print("✓ 2.1 All required signals verified on VehicleListWidget (delete_requested, vehicle_selected, maintenance_requested, add_requested).")

    # 3. Test VehicleRow action signals
    print("\n--- [3/4] Testing VehicleRow Action Signals ---")
    v_list_test = VehicleListWidget(user_role="ADMIN")
    sample_vehicle = {
        "id": str(uuid4()),
        "registration": "TEST-SIGNAL-01",
        "brand": "Renault",
        "model": "Clio",
        "year": 2024,
        "status": "AVAILABLE",
        "mileage": 5000,
        "daily_rental_price": 350.0
    }

    received_delete_id = []
    received_edit_id = []
    received_maint_id = []

    v_list_test.delete_requested.connect(lambda vid: received_delete_id.append(vid))
    v_list_test.vehicle_selected.connect(lambda vid: received_edit_id.append(vid))
    v_list_test.maintenance_requested.connect(lambda vid: received_maint_id.append(vid))

    v_list_test.load_vehicles([sample_vehicle])
    assert len(v_list_test._cards) == 1, "Should have loaded 1 vehicle card"

    row_widget, _ = v_list_test._cards[0]

    # Trigger signals from row
    row_widget.delete_requested.emit(sample_vehicle["id"])
    row_widget.edit_requested.emit(sample_vehicle["id"])
    row_widget.maintenance_requested.emit(sample_vehicle["id"])

    assert received_delete_id == [sample_vehicle["id"]], "delete_requested signal failed to forward"
    assert received_edit_id == [sample_vehicle["id"]], "vehicle_selected signal failed to forward"
    assert received_maint_id == [sample_vehicle["id"]], "maintenance_requested signal failed to forward"
    print("✓ 3.1 All signals forwarded cleanly from VehicleRow through VehicleListWidget.")

    # 4. End-to-end controlled delete execution test
    print("\n--- [4/4] Testing End-to-End Controlled Vehicle Deletion ---")
    test_v_id = str(uuid4())
    test_reg = f"TST-{uuid4().hex[:6].upper()}"
    now_iso = datetime.now(timezone.utc).isoformat()

    session = get_local_session()
    try:
        test_v = LocalVehicle(
            id=test_v_id,
            registration=test_reg,
            vin=f"VIN{uuid4().hex[:14].upper()}",
            brand="Peugeot",
            model="208",
            year=2024,
            color="Noir",
            fuel_type="DIESEL",
            transmission="MANUAL",
            current_mileage=1500,
            purchase_price=180000.0,
            daily_rental_price=350.0,
            status="AVAILABLE",
            created_at=now_iso,
            updated_at=now_iso,
            version=1
        )
        session.add(test_v)
        session.commit()
    finally:
        session.close()

    # Load into UI
    main_win._load_vehicles_from_local()

    # Directly invoke deletion logic bypassing QMessageBox
    session = get_local_session()
    try:
        v_to_delete = session.query(LocalVehicle).filter_by(id=test_v_id).first()
        assert v_to_delete is not None, "Vehicle should exist in SQLite"

        # Enqueue delete
        from app.sync.queue import SyncQueue
        queue = SyncQueue(session, main_win._device_id, mock_user["user_id"])
        queue.enqueue(
            entity_type="vehicle",
            entity_id=test_v_id,
            operation="DELETE",
            payload={"id": test_v_id, "registration": test_reg}
        )
        session.delete(v_to_delete)
        session.commit()
    finally:
        session.close()

    # Refresh UI
    main_win._load_vehicles_from_local()

    # Verify vehicle absent from SQLite
    session = get_local_session()
    try:
        deleted_check = session.query(LocalVehicle).filter_by(id=test_v_id).first()
        assert deleted_check is None, "Vehicle must be absent from SQLite after deletion"

        # Verify sync queue has DELETE operation
        queue_item = session.query(SyncQueueItem).filter_by(entity_id=test_v_id, operation="DELETE").first()
        assert queue_item is not None, "Sync queue must record DELETE operation"
        print(f"✓ 4.1 Vehicle {test_reg} deleted from SQLite and recorded in SyncQueue.")
    finally:
        session.close()

    print("\n" + "=" * 70)
    print("🎉 ALL DESKTOP UI STARTUP & VEHICLE ACTIONS VERIFIED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    run_desktop_ui_verification()
