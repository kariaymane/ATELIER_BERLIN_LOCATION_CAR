import pytest
import sys
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from unittest.mock import MagicMock
from datetime import datetime, timezone
import uuid
import gc

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.models.vehicle import LocalVehicle
from app.database import get_local_session, init_local_db
from app.services.event_bus import get_event_bus
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance

@pytest.fixture(autouse=True)
def clean_db():
    init_local_db()

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

def test_gap_c_vehicle_creation_refreshes_reservations(qapp):
    user_data = {"user_id": "u1", "role": "ADMIN", "full_name": "Admin", "access_token": "mock", "refresh_token": "mock"}
    window = MainWindow(user_data=user_data)
    
    window._reservations.refresh_data = MagicMock(side_effect=window._reservations.refresh_data)
    window._reservations.refresh_data.reset_mock()
    
    data = {
        "registration": "REACT-123",
        "brand": "Test",
        "model": "Car",
        "vin": "VINTEXT123",
        "fuel_type": "Diesel",
        "transmission": "Auto",
        "status": "ACTIVE"
    }
    
    window._save_vehicle(data)
    window._reservations.refresh_data.assert_called()
    window.deleteLater()
    
def test_gap_a_maintenance_creation_refreshes_dashboard(qapp):
    user_data = {"user_id": "u1", "role": "ADMIN", "full_name": "Admin", "access_token": "mock", "refresh_token": "mock"}
    
    session = get_local_session()
    v_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    v = LocalVehicle(
        id=v_id, 
        registration="MAINT-1", 
        brand="Test", 
        model="Car", 
        vin="VINMAINT1", 
        year=2024,
        color="Noir",
        fuel_type="Diesel", 
        transmission="Auto",
        status="ACTIVE",
        created_at=now_iso,
        updated_at=now_iso
    )
    session.add(v)
    session.commit()
    session.close()
    
    window = MainWindow(user_data=user_data)

    # Committed mutations now converge through DomainStore.mutate(): one
    # mutation publishes exactly one new revision, whose fan-out refreshes the
    # dashboard (and every other view) with no manual pulse.
    dash_spy = MagicMock(side_effect=window._refresh_dashboard)
    window._refresh_dashboard = dash_spy
    rev_before = window._store.revision

    data = {
        "vehicle_id": v_id,
        "type": "Entretien",
        "start_datetime": datetime.now(timezone.utc).isoformat(),
        "status": "ACTIVE",
        "parts": []
    }

    window._create_maintenance_record(data)
    assert window._store.revision == rev_before + 1
    dash_spy.assert_called()
    window.deleteLater()

def test_async_race_dashboard_stats(qapp):
    user_data = {"user_id": "u1", "role": "ADMIN", "full_name": "Admin", "access_token": "mock", "refresh_token": "mock"}
    window = MainWindow(user_data=user_data)
    
    window._dashboard_generation = 2
    window._dashboard.refresh_data = MagicMock()
    
    window._on_dashboard_stats({"total_vehicles": 99}, [], generation=1)
    window._dashboard.refresh_data.assert_not_called()
    
    window._on_dashboard_stats({"total_vehicles": 100}, [], generation=2)
    window._dashboard.refresh_data.assert_called_once()
    window.deleteLater()
