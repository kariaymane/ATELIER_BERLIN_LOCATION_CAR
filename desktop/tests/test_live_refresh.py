import pytest
import sys
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"
from datetime import datetime, timezone, timedelta
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QDateTime, Qt
from app.ui.reservations.reservation_list import ReservationWidget
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.database import get_local_session, init_local_db

@pytest.fixture(autouse=True)
def clean_db():
    init_local_db()

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

def test_reservation_overlap_excludes_vehicle(qapp):
    """Test that an overlapping reservation removes the vehicle from the grid."""
    db_session = get_local_session()
    # 1. Setup Data
    v = LocalVehicle(
        id="v-test-overlap",
        brand="Toyota", model="Yaris",
        status="AVAILABLE",
        daily_rental_price=300,
        registration="11111-A-1",
        vin="12345678901234567",
        year=2024,
        color="Black",
        fuel_type="Diesel",
        transmission="Manual",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z"
    )
    db_session.add(v)
    
    now = datetime.now(timezone.utc)
    res_start = now + timedelta(days=1)
    res_end = now + timedelta(days=6)
    
    r = LocalReservation(
        id="r-overlap",
        vehicle_id="v-test-overlap",
        status="ACTIVE",
        start_datetime=res_start.isoformat(),
        end_datetime=res_end.isoformat(),
        daily_price=300.0,
        num_days=5,
        total_price=1500,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        version=1
    )
    db_session.add(r)
    db_session.commit()

    # 2. Init Widget
    widget = ReservationWidget(device_id="test-dev", user_id="test-user")
    qapp.processEvents()

    # 3. Request completely overlapping interval
    req_start = QDateTime(res_start.astimezone())
    req_end = QDateTime(res_end.astimezone())
    
    widget._filter_start_dt.setDateTime(req_start)
    widget._filter_end_dt.setDateTime(req_end)
    
    # 4. Verify the vehicle is excluded
    cards_count = widget._grid.count()
    assert cards_count == 0

def test_maintenance_overlap_excludes_vehicle(qapp):
    """Test that an overlapping maintenance removes the vehicle from the grid."""
    db_session = get_local_session()
    v = LocalVehicle(
        id="v-test-maint",
        brand="Kia", model="Picanto",
        status="AVAILABLE",
        daily_rental_price=250,
        registration="22222-B-2",
        vin="12345678901234568",
        year=2024,
        color="Black",
        fuel_type="Diesel",
        transmission="Manual",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z"
    )
    db_session.add(v)
    
    now = datetime.now(timezone.utc)
    m_start = now + timedelta(days=1)
    m_end = now + timedelta(days=3)
    
    m = LocalMaintenance(
        id="m-overlap",
        vehicle_id="v-test-maint",
        type="Entretien",
        title="Test",
        status="ACTIVE",
        start_datetime=m_start.isoformat(),
        expected_end_datetime=m_end.isoformat(),
        actual_end_datetime=None,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        version=1
    )
    db_session.add(m)
    db_session.commit()

    widget = ReservationWidget(device_id="test-dev", user_id="test-user")
    qapp.processEvents()

    req_start = QDateTime(m_start.astimezone())
    req_end = QDateTime(m_end.astimezone())
    
    widget._filter_start_dt.setDateTime(req_start)
    widget._filter_end_dt.setDateTime(req_end)
    
    assert widget._grid.count() == 0

def test_exact_boundary_allows_vehicle(qapp):
    """Test that adjacent non-overlapping intervals do NOT exclude the vehicle."""
    db_session = get_local_session()
    v = LocalVehicle(
        id="v-test-boundary",
        brand="Dacia", model="Logan",
        status="AVAILABLE",
        daily_rental_price=200,
        registration="33333-C-3",
        vin="12345678901234569",
        year=2024,
        color="Black",
        fuel_type="Diesel",
        transmission="Manual",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z"
    )
    db_session.add(v)
    
    now = datetime.now(timezone.utc)
    res_start = now + timedelta(days=1)
    res_end = now + timedelta(days=3)
    
    r = LocalReservation(
        id="r-boundary",
        vehicle_id="v-test-boundary",
        status="ACTIVE",
        start_datetime=res_start.isoformat(),
        end_datetime=res_end.isoformat(),
        daily_price=200.0,
        num_days=2,
        total_price=400,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        version=1
    )
    db_session.add(r)
    db_session.commit()

    widget = ReservationWidget(device_id="test-dev", user_id="test-user")
    qapp.processEvents()

    # Request start EXACTLY at the end of the previous reservation
    req_start = QDateTime(res_end.astimezone())
    req_end = QDateTime((res_end + timedelta(days=2)).astimezone())
    
    widget._filter_start_dt.setDateTime(req_start)
    widget._filter_end_dt.setDateTime(req_end)
    
    assert widget._grid.count() == 1
