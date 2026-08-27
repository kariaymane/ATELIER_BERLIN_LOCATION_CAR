import pytest
import sys
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"
from PySide6.QtWidgets import QApplication

from datetime import datetime, timezone
from PySide6.QtCore import Qt
from app.ui.main_window import MainWindow
from app.models.vehicle import LocalVehicle
from app.models.maintenance import LocalMaintenance
from app.sync.queue import SyncQueueItem

from app.database import get_local_session, init_local_db

@pytest.fixture(autouse=True)
def clean_db():
    init_local_db()

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

def test_create_maintenance_record_triggers_refresh_and_sync(qapp, monkeypatch):
    """Test that creating a maintenance record updates views and enqueues sync."""
    db_session = get_local_session()
    v = LocalVehicle(
        id="v-test-maint-create",
        brand="Peugeot", model="208",
        status="AVAILABLE",
        daily_rental_price=250,
        registration="44444-D-4",
        vin="12345678901234560",
        year=2024,
        color="Black",
        fuel_type="Diesel",
        transmission="Manual",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z"
    )
    db_session.add(v)
    db_session.commit()

    main_window = MainWindow(user_data={"user_id": "u-1", "access_token": "dummy", "offline": True})
    qapp.processEvents()
    
    # Mock methods to track if they were called
    refreshed_dashboard = False
    refreshed_maintenance = False
    refreshed_reservations = False
    ran_sync = False
    
    def mock_refresh_dashboard(): nonlocal refreshed_dashboard; refreshed_dashboard = True
    def mock_maintenance_refresh(): nonlocal refreshed_maintenance; refreshed_maintenance = True
    def mock_reservations_refresh(): nonlocal refreshed_reservations; refreshed_reservations = True
    def mock_run_sync(): nonlocal ran_sync; ran_sync = True
    
    monkeypatch.setattr(main_window, '_refresh_dashboard', mock_refresh_dashboard)
    monkeypatch.setattr(main_window._maintenance, 'refresh_data', mock_maintenance_refresh)
    monkeypatch.setattr(main_window._reservations, 'refresh_data', mock_reservations_refresh)
    monkeypatch.setattr(main_window, '_run_sync', mock_run_sync)

    now = datetime.now(timezone.utc).isoformat()
    data = {
        "vehicle_id": "v-test-maint-create",
        "type": "Entretien",
        "title": "Vidange",
        "start_datetime": now,
        "parts": []
    }
    
    main_window._create_maintenance_record(data)
    
    # Assert views refreshed and sync ran
    assert refreshed_dashboard is True
    assert refreshed_maintenance is True
    assert refreshed_reservations is True
    assert ran_sync is True
    
    # Assert DB state
    v_updated = db_session.query(LocalVehicle).filter_by(id="v-test-maint-create").first()
    assert v_updated.status == "MAINTENANCE"
    
    m_record = db_session.query(LocalMaintenance).filter_by(vehicle_id="v-test-maint-create").first()
    assert m_record is not None
    assert m_record.title == "Vidange"
    
    # Assert SyncQueue state
    sync_items = db_session.query(SyncQueueItem).all()
    assert len(sync_items) == 2
    types = {item.entity_type for item in sync_items}
    assert "maintenance" in types
    assert "vehicle" in types
