import pytest
import sys
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication

from app.ui.vehicles.vehicle_list import VehicleListWidget, VehicleRow


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_vehicle_list_filters_and_price_buttons(qapp):
    widget = VehicleListWidget(user_role="ADMIN")
    widget.show()
    qapp.processEvents()

    # Verify price options exist
    assert None in widget._price_buttons
    assert 250 in widget._price_buttons
    assert 300 in widget._price_buttons
    assert 400 in widget._price_buttons
    assert 450 in widget._price_buttons
    assert 500 in widget._price_buttons

    sample_vehicles = [
        {"id": "v1", "brand": "Renault", "model": "Clio", "registration": "11111-A-1", "daily_rental_price": 250.0, "status": "AVAILABLE", "year": 2023},
        {"id": "v2", "brand": "Dacia", "model": "Logan", "registration": "22222-A-1", "daily_rental_price": 300.0, "status": "AVAILABLE", "year": 2024},
        {"id": "v3", "brand": "Volkswagen", "model": "Golf 8", "registration": "33333-A-1", "daily_rental_price": 400.0, "status": "RENTED", "year": 2024},
        {"id": "v4", "brand": "Audi", "model": "A3", "registration": "44444-A-1", "daily_rental_price": 450.0, "status": "AVAILABLE", "year": 2024},
        {"id": "v5", "brand": "Mercedes", "model": "Classe A", "registration": "55555-A-1", "daily_rental_price": 500.0, "status": "MAINTENANCE", "year": 2024},
    ]

    widget.load_vehicles(sample_vehicles)
    qapp.processEvents()
    assert len(widget._cards) == 5

    # 1. Test All (default)
    widget._on_price_filter_clicked(None)
    visible = [c for c, _ in widget._cards if not c.isHidden()]
    assert len(visible) == 5

    # 2. Test 250 DH filter
    widget._on_price_filter_clicked(250)
    visible = [c for c, _ in widget._cards if not c.isHidden()]
    assert len(visible) == 1
    assert visible[0]._data["daily_rental_price"] == 250.0

    # 3. Test 450 DH filter
    widget._on_price_filter_clicked(450)
    visible = [c for c, _ in widget._cards if not c.isHidden()]
    assert len(visible) == 1
    assert visible[0]._data["brand"] == "Audi"

    # 4. Test Search filter
    widget._on_price_filter_clicked(None)
    widget.set_filter("Logan")
    visible = [c for c, _ in widget._cards if not c.isHidden()]
    assert len(visible) == 1
    assert visible[0]._data["model"] == "Logan"
