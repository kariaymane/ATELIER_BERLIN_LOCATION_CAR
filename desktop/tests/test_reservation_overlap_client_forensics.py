"""
Regression tests for reservation false overlap and client creation forensic repair.
Tests 1-8 from forensic specification.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import uuid
from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.models.client import LocalClient
from app.sync.queue import SyncQueue
from app.ui.reservations.reservation_list import parse_datetime_utc, ReservationWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture(autouse=True)
def setup_db(qapp):
    init_local_db()
    session = get_local_session()
    v1 = LocalVehicle(
        id="veh-test-1",
        registration="TEST-001",
        vin="VINTEST0000000001",
        brand="ForensicBrand",
        model="ProofModel",
        year=2024,
        color="Noir",
        fuel_type="GASOLINE",
        transmission="AUTOMATIC",
        current_mileage=1000,
        purchase_mileage=0,
        purchase_price=200000,
        daily_rental_price=250.0,
        status="AVAILABLE",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    v2 = LocalVehicle(
        id="veh-test-2",
        registration="TEST-002",
        vin="VINTEST0000000002",
        brand="ForensicBrand",
        model="OtherModel",
        year=2024,
        color="Blanc",
        fuel_type="DIESEL",
        transmission="MANUAL",
        current_mileage=5000,
        purchase_mileage=0,
        purchase_price=180000,
        daily_rental_price=200.0,
        status="AVAILABLE",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    session.add_all([v1, v2])
    session.commit()
    session.close()


def test_1_no_overlap_adjacent_dates(qapp):
    """Test 1 — No overlap: Adjacent dates allowed.
    Existing: 01/09/2026 10:00 -> 03/09/2026 10:00
    New:      03/09/2026 10:00 -> 06/09/2026 10:00
    Expected: PASS (Accepted)
    """
    session = get_local_session()
    res1 = LocalReservation(
        id="res-1",
        vehicle_id="veh-test-1",
        customer_name="Existing Client",
        start_datetime="2026-09-01T10:00:00+00:00",
        end_datetime="2026-09-03T10:00:00+00:00",
        daily_price=250.0,
        num_days=2,
        total_price=500.0,
        status="RESERVED",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    session.add(res1)
    session.commit()
    session.close()

    widget = ReservationWidget(device_id="dev-1", user_id="user-1")
    new_data = {
        "vehicle_id": "veh-test-1",
        "customer_name": "New Client",
        "start_datetime": "2026-09-03T10:00:00+00:00",
        "end_datetime": "2026-09-06T10:00:00+00:00",
        "daily_price": 250.0,
        "num_days": 3,
        "total_price": 750.0,
        "status": "RESERVED",
    }
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        widget._create_reservation_record(new_data)
        assert not mock_warn.called

    session = get_local_session()
    all_res = session.query(LocalReservation).filter_by(vehicle_id="veh-test-1").all()
    assert len(all_res) == 2
    session.close()


def test_2_real_overlap_rejected(qapp):
    """Test 2 — Real overlap:
    Existing: 01/09/2026 10:00 -> 05/09/2026 10:00
    New:      03/09/2026 10:00 -> 06/09/2026 10:00
    Expected: REJECT
    """
    session = get_local_session()
    res1 = LocalReservation(
        id="res-1",
        vehicle_id="veh-test-1",
        customer_name="Existing Client",
        start_datetime="2026-09-01T10:00:00+00:00",
        end_datetime="2026-09-05T10:00:00+00:00",
        daily_price=250.0,
        num_days=4,
        total_price=1000.0,
        status="RESERVED",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    session.add(res1)
    session.commit()
    session.close()

    widget = ReservationWidget(device_id="dev-1", user_id="user-1")
    new_data = {
        "vehicle_id": "veh-test-1",
        "customer_name": "New Client",
        "start_datetime": "2026-09-03T10:00:00+00:00",
        "end_datetime": "2026-09-06T10:00:00+00:00",
        "daily_price": 250.0,
        "num_days": 3,
        "total_price": 750.0,
        "status": "RESERVED",
    }
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        widget._create_reservation_record(new_data)
        assert mock_warn.called

    session = get_local_session()
    all_res = session.query(LocalReservation).filter_by(vehicle_id="veh-test-1").all()
    assert len(all_res) == 1
    session.close()


def test_3_cancelled_does_not_block(qapp):
    """Test 3 — CANCELLED does not block.
    Existing: CANCELLED, Same dates.
    Expected: PASS
    """
    session = get_local_session()
    res1 = LocalReservation(
        id="res-1",
        vehicle_id="veh-test-1",
        customer_name="Cancelled Client",
        start_datetime="2026-09-01T10:00:00+00:00",
        end_datetime="2026-09-05T10:00:00+00:00",
        daily_price=250.0,
        num_days=4,
        total_price=1000.0,
        status="CANCELLED",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    session.add(res1)
    session.commit()
    session.close()

    widget = ReservationWidget(device_id="dev-1", user_id="user-1")
    new_data = {
        "vehicle_id": "veh-test-1",
        "customer_name": "New Client",
        "start_datetime": "2026-09-01T10:00:00+00:00",
        "end_datetime": "2026-09-05T10:00:00+00:00",
        "daily_price": 250.0,
        "num_days": 4,
        "total_price": 1000.0,
        "status": "RESERVED",
    }
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        widget._create_reservation_record(new_data)
        assert not mock_warn.called

    session = get_local_session()
    active_res = session.query(LocalReservation).filter_by(vehicle_id="veh-test-1", status="RESERVED").all()
    assert len(active_res) == 1
    session.close()


def test_4_completed_does_not_block(qapp):
    """Test 4 — COMPLETED does not block.
    Existing: COMPLETED, Same dates.
    Expected: PASS
    """
    session = get_local_session()
    res1 = LocalReservation(
        id="res-1",
        vehicle_id="veh-test-1",
        customer_name="Past Client",
        start_datetime="2026-09-01T10:00:00+00:00",
        end_datetime="2026-09-05T10:00:00+00:00",
        daily_price=250.0,
        num_days=4,
        total_price=1000.0,
        status="COMPLETED",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    session.add(res1)
    session.commit()
    session.close()

    widget = ReservationWidget(device_id="dev-1", user_id="user-1")
    new_data = {
        "vehicle_id": "veh-test-1",
        "customer_name": "New Client",
        "start_datetime": "2026-09-01T10:00:00+00:00",
        "end_datetime": "2026-09-05T10:00:00+00:00",
        "daily_price": 250.0,
        "num_days": 4,
        "total_price": 1000.0,
        "status": "RESERVED",
    }
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        widget._create_reservation_record(new_data)
        assert not mock_warn.called

    session = get_local_session()
    active_res = session.query(LocalReservation).filter_by(vehicle_id="veh-test-1", status="RESERVED").all()
    assert len(active_res) == 1
    session.close()


def test_5_different_vehicle_same_dates_allowed(qapp):
    """Test 5 — Different vehicle with same dates: PASS"""
    session = get_local_session()
    res1 = LocalReservation(
        id="res-1",
        vehicle_id="veh-test-1",
        customer_name="Client A",
        start_datetime="2026-09-01T10:00:00+00:00",
        end_datetime="2026-09-05T10:00:00+00:00",
        daily_price=250.0,
        num_days=4,
        total_price=1000.0,
        status="RESERVED",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    session.add(res1)
    session.commit()
    session.close()

    widget = ReservationWidget(device_id="dev-1", user_id="user-1")
    new_data = {
        "vehicle_id": "veh-test-2",
        "customer_name": "Client B",
        "start_datetime": "2026-09-01T10:00:00+00:00",
        "end_datetime": "2026-09-05T10:00:00+00:00",
        "daily_price": 200.0,
        "num_days": 4,
        "total_price": 800.0,
        "status": "RESERVED",
    }
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        widget._create_reservation_record(new_data)
        assert not mock_warn.called

    session = get_local_session()
    res_v2 = session.query(LocalReservation).filter_by(vehicle_id="veh-test-2").all()
    assert len(res_v2) == 1
    session.close()


def test_6_timezone_equivalence(qapp):
    """Test 6 — Timezone equivalence:
    Same instant represented with different timezone offsets correctly detected.
    Existing: 2026-08-24T20:36:00Z -> 2026-08-28T20:36:00Z
    New:      2026-08-24T21:36:00+01:00 -> 2026-08-28T21:36:00+01:00 (exact same period in UTC)
    Expected: Overlap detected and rejected.
    """
    session = get_local_session()
    res1 = LocalReservation(
        id="res-1",
        vehicle_id="veh-test-1",
        customer_name="Client UTC",
        start_datetime="2026-08-24T20:36:00Z",
        end_datetime="2026-08-28T20:36:00Z",
        daily_price=250.0,
        num_days=4,
        total_price=1000.0,
        status="RESERVED",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    session.add(res1)
    session.commit()
    session.close()

    widget = ReservationWidget(device_id="dev-1", user_id="user-1")
    new_data = {
        "vehicle_id": "veh-test-1",
        "customer_name": "Client Casablanca (+01:00)",
        "start_datetime": "2026-08-24T21:36:00+01:00",
        "end_datetime": "2026-08-28T21:36:00+01:00",
        "daily_price": 250.0,
        "num_days": 4,
        "total_price": 1000.0,
        "status": "RESERVED",
    }
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        widget._create_reservation_record(new_data)
        assert mock_warn.called


def test_7_stale_local_reservation_server_available(qapp):
    """Test 7 — Stale local reservation:
    Local SQLite contains a stale reservation, but server API confirms vehicle is AVAILABLE.
    Expected: Reservation allowed because server is authoritative.
    """
    session = get_local_session()
    stale_res = LocalReservation(
        id="res-stale",
        vehicle_id="veh-test-1",
        customer_name="Stale Ghost Client",
        start_datetime="2026-08-24T20:36:00Z",
        end_datetime="2026-08-28T20:36:00Z",
        daily_price=250.0,
        num_days=4,
        total_price=1000.0,
        status="RESERVED",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    session.add(stale_res)
    session.commit()
    session.close()

    mock_api = MagicMock()
    mock_api._access_token = "valid_token"
    mock_api.check_availability.return_value = {"available": True, "vehicle_id": "veh-test-1"}

    widget = ReservationWidget(device_id="dev-1", user_id="user-1", api_client=mock_api)
    new_data = {
        "vehicle_id": "veh-test-1",
        "customer_name": "Real Fresh Client",
        "start_datetime": "2026-08-24T20:36:00Z",
        "end_datetime": "2026-08-28T20:36:00Z",
        "daily_price": 250.0,
        "num_days": 4,
        "total_price": 1000.0,
        "status": "RESERVED",
    }
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        widget._create_reservation_record(new_data)
        assert not mock_warn.called

    session = get_local_session()
    all_res = session.query(LocalReservation).filter_by(vehicle_id="veh-test-1").all()
    assert len(all_res) == 2
    session.close()


def test_8_new_client_and_reservation_linking(qapp):
    """Test 8 — New client + reservation:
    Create new client + reservation.
    Verify:
    - LocalClient exists.
    - LocalReservation.customer_id == LocalClient.id.
    - SyncQueue contains both 'client' and 'reservation' operations in correct order.
    """
    widget = ReservationWidget(device_id="dev-1", user_id="user-1")
    new_data = {
        "vehicle_id": "veh-test-1",
        "customer_name": "Karim Bennani",
        "customer_phone": "+212600112233",
        "customer_email": "karim@test.ma",
        "start_datetime": "2026-08-24T20:36:00Z",
        "end_datetime": "2026-08-28T20:36:00Z",
        "daily_price": 250.0,
        "num_days": 4,
        "total_price": 1000.0,
        "status": "RESERVED",
    }
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        widget._create_reservation_record(new_data)
        assert not mock_warn.called

    session = get_local_session()
    res = session.query(LocalReservation).filter_by(vehicle_id="veh-test-1").first()
    assert res is not None
    assert res.customer_id is not None

    client = session.query(LocalClient).filter_by(id=res.customer_id).first()
    assert client is not None
    assert client.first_name == "Karim"
    assert client.last_name == "Bennani"
    assert client.phone == "+212600112233"
    assert client.email == "karim@test.ma"

    queue = SyncQueue(session, "dev-1")
    pending = queue.get_pending()
    assert len(pending) >= 2
    entity_types = [p.entity_type for p in pending]
    assert "client" in entity_types
    assert "reservation" in entity_types
    # Client must be enqueued before reservation
    client_idx = entity_types.index("client")
    res_idx = entity_types.index("reservation")
    assert client_idx < res_idx
    session.close()
