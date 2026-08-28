import pytest
import sys
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from unittest.mock import MagicMock
from datetime import datetime, timezone
import uuid

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

def get_valid_vehicle_dict(idx: int):
    return {
        "registration": f"REACT-{idx}",
        "brand": "Test",
        "model": "Car",
        "vin": f"VINREACT123{idx}",
        "fuel_type": "Diesel",
        "transmission": "Auto",
        "status": "ACTIVE",
        "year": 2024,
        "color": "Red",
        "current_mileage": 0,
        "purchase_mileage": 0,
        "purchase_price": 0.0,
        "daily_rental_price": 0.0,
    }

def test_gap_c_vehicle_creation_refreshes_reservations(qapp):
    user_data = {"user_id": "u1", "role": "ADMIN", "full_name": "Admin", "access_token": "mock", "refresh_token": "mock"}
    window = MainWindow(user_data=user_data)
    
    window._reservations.refresh_data = MagicMock(side_effect=window._reservations.refresh_data)
    window._reservations.refresh_data.reset_mock()
    
    data = get_valid_vehicle_dict(1)
    window._save_vehicle(data)
    
    window._reservations.refresh_data.assert_called()

def test_gap_a_maintenance_creation_refreshes_dashboard(qapp):
    user_data = {"user_id": "u1", "role": "ADMIN", "full_name": "Admin", "access_token": "mock", "refresh_token": "mock"}
    
    session = get_local_session()
    v_data = get_valid_vehicle_dict(2)
    now = datetime.now(timezone.utc).isoformat()
    v = LocalVehicle(
        id=str(uuid.uuid4()), 
        registration=v_data["registration"], 
        brand=v_data["brand"], 
        model=v_data["model"], 
        vin=v_data["vin"], 
        fuel_type=v_data["fuel_type"], 
        transmission=v_data["transmission"],
        year=v_data["year"],
        color=v_data["color"],
        created_at=now,
        updated_at=now,
        status="ACTIVE"
    )
    session.add(v)
    session.commit()
    v_id = v.id
    session.close()
    
    window = MainWindow(user_data=user_data)
    
    bus_spy = MagicMock()
    get_event_bus().data_refreshed.connect(bus_spy)
    
    data = {
        "vehicle_id": v_id,
        "type": "Entretien",
        "start_datetime": now,
        "status": "ACTIVE",
        "parts": []
    }
    
    window._create_maintenance_record(data)
    bus_spy.assert_called()

def test_async_race_dashboard_stats(qapp):
    user_data = {"user_id": "u1", "role": "ADMIN", "full_name": "Admin", "access_token": "mock", "refresh_token": "mock"}
    window = MainWindow(user_data=user_data)
    
    window._dashboard_generation = 2
    window._dashboard.refresh_data = MagicMock()
    
    window._on_dashboard_stats({"total_vehicles": 99}, [], generation=1)
    window._dashboard.refresh_data.assert_not_called()
    
    window._on_dashboard_stats({"total_vehicles": 100}, [], generation=2)
    window._dashboard.refresh_data.assert_called_once()
