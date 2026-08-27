import pytest
from PySide6.QtWidgets import QApplication
from unittest.mock import patch, MagicMock
from app.services.event_bus import get_event_bus
from app.ui.clients.client_details import ClientDetailsDialog
from app.database import get_local_session, init_local_db
from app.models.client import LocalClient
import datetime
import os

@pytest.fixture(autouse=True)
def setup_db():
    os.environ["CAR_RENTAL_DB_RESET"] = "1"
    init_local_db()

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])

def test_client_details_reloads_on_data_refreshed(qapp):
    session = get_local_session()
    c = LocalClient(
        id="live-client-1",
        first_name="TEST_LIVE_CLIENT",
        last_name="",
        cin_number="TEST_CIN",
        identity_card_image="pending_uploads/front.jpg",
        driving_license_image="pending_uploads/back.jpg",
        status="ACTIVE",
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        version=1,
    )
    session.add(c)
    session.commit()
    session.close()

    dlg = ClientDetailsDialog({"id": "live-client-1"})
    assert dlg._name_lbl.text() == "TEST_LIVE_CLIENT"
    
    # Check that pending_uploads was NOT stripped!
    assert "pending_uploads/front.jpg" in dlg._doc_thumbs["identity_card_image"].property("cache_key")

    session = get_local_session()
    c2 = session.query(LocalClient).filter_by(id="live-client-1").first()
    c2.first_name = "UPDATED_NAME"
    c2.identity_card_image = "pending_uploads/new_front.jpg"
    session.commit()
    session.close()

    get_event_bus().data_refreshed.emit()
    assert dlg._name_lbl.text() == "UPDATED_NAME"
    assert "new_front.jpg" in dlg._doc_thumbs["identity_card_image"].property("cache_key")

def test_vehicle_details_fetches_fresh_data_on_open(qapp):
    from app.ui.vehicles.vehicle_list import VehicleRow
    session = get_local_session()
    from app.models.vehicle import LocalVehicle
    v = LocalVehicle(
        id="live-veh-1",
        brand="BRAND",
        model="MODEL", registration="REG", vin="VIN",
        status="AVAILABLE",
        daily_rental_price=10.0,
        year=2020, color="Red", current_mileage=100, fuel_type="Diesel", transmission="Auto",
        created_at="2026", updated_at="2026"
    )
    session.add(v)
    session.commit()
    session.close()

    row = VehicleRow({"id": "live-veh-1", "brand": "STALE_BRAND", "model": "STALE_MODEL", "status": "AVAILABLE", "daily_rental_price": 10.0})
    
    with patch("app.ui.vehicles.vehicle_list.VehicleDetailModal") as mock_modal:
        mock_modal_instance = MagicMock()
        mock_modal.return_value = mock_modal_instance
        row._show_details()
        args, _ = mock_modal.call_args
        passed_dict = args[0]
        assert passed_dict["brand"] == "BRAND"
        assert passed_dict["model"] == "MODEL"
