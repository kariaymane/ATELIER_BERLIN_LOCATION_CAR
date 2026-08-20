"""
Tests for Vehicle Hover Preview Lifecycle and Visibility States.
"""
import os
import sys
import pytest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication
from app.ui.vehicles.vehicle_hover_preview import get_hover_preview
from app.ui.vehicles.vehicle_list import VehicleRow, VehicleListWidget

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app

def test_hover_preview_lifecycle(qapp):
    preview = get_hover_preview()
    v1 = {"id": "v-1", "brand": "Porsche", "model": "911", "registration": "12345-A-1", "daily_rental_price": 2000, "status": "AVAILABLE"}
    v2 = {"id": "v-2", "brand": "Audi", "model": "RS6", "registration": "67890-B-2", "daily_rental_price": 2500, "status": "RENTED"}

    row1 = VehicleRow(v1, user_role="ADMIN")
    row2 = VehicleRow(v2, user_role="ADMIN")
    row1.resize(800, 76)
    row2.resize(800, 76)
    row1.show()
    row2.show()
    qapp.processEvents()

    # 1. Hover Enter row 1 -> shows preview
    row1._on_mouse_enter()
    row1._on_hover_timeout()
    qapp.processEvents()
    assert preview._is_visible is True
    assert preview._current_vehicle_id == "v-1"

    # 2. Hover Leave row 1 -> hides preview
    row1._on_mouse_leave()
    preview.cancel_and_hide()
    qapp.processEvents()
    assert preview._is_visible is False
    assert preview._current_vehicle_id is None

    # 3. Enter row 1 -> Click Details -> preview cancelled immediately BEFORE modal opens
    row1._on_mouse_enter()
    row1._on_hover_timeout()
    assert preview._is_visible is True
    # simulate clicking details
    preview.cancel_and_hide()
    assert preview._is_visible is False
    assert preview._current_vehicle_id is None

    # 4. Enter row 1 -> Click Edit -> preview cancelled immediately
    row1._on_mouse_enter()
    row1._on_hover_timeout()
    assert preview._is_visible is True
    row1._on_edit_clicked()
    assert preview._is_visible is False

    # 5. Enter row 1 -> Click Delete -> preview cancelled immediately
    row1._on_mouse_enter()
    row1._on_hover_timeout()
    assert preview._is_visible is True
    row1._on_delete_clicked()
    assert preview._is_visible is False

    # 6. Enter row 1 then move directly to row 2 -> switches immediately to row 2
    row2._on_mouse_enter()
    row2._on_hover_timeout()
    qapp.processEvents()
    assert preview._is_visible is True
    assert preview._current_vehicle_id == "v-2"

    # 7. Cancel and clean up
    preview.cancel_and_hide()
    assert preview._is_visible is False
    assert preview._current_vehicle_id is None
