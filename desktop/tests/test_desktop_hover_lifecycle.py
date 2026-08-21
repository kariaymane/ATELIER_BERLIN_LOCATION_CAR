import pytest
import sys
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication

from app.ui.vehicles.vehicle_hover_preview import get_hover_preview
from app.ui.vehicles.vehicle_list import VehicleRow


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_hover_preview_lifecycle(qapp):
    preview = get_hover_preview()
    preview.cancel_and_hide()

    v_a = {"id": "veh-101", "brand": "Porsche", "model": "Macan", "registration": "23456-A-1", "daily_rental_price": 1500, "status": "AVAILABLE"}
    v_b = {"id": "veh-102", "brand": "Mercedes", "model": "C63", "registration": "78910-B-2", "daily_rental_price": 1800, "status": "RESERVED"}

    row_a = VehicleRow(v_a, user_role="ADMIN")
    row_b = VehicleRow(v_b, user_role="ADMIN")
    row_a.resize(800, 76)
    row_b.resize(800, 76)
    row_a.show()
    row_b.show()
    qapp.processEvents()

    # Reset hover states
    preview.cancel_and_hide()
    row_a._is_hovered = False
    row_b._is_hovered = False

    # 1. Enter row A -> preview appears after timeout
    row_a._on_mouse_enter()
    preview._on_show_timeout()
    qapp.processEvents()
    assert preview._is_visible is True
    assert preview._current_vehicle_id == "veh-101"

    # 2. Leave row A -> preview disappears
    row_a._on_mouse_leave()
    preview._check_and_hide()
    preview.hide_preview(immediate=True)
    qapp.processEvents()
    assert preview._is_visible is False

    # 3. Enter row A then hover action button -> preview cancelled
    row_a._is_hovered = False
    row_a._on_mouse_enter()
    preview._on_show_timeout()
    qapp.processEvents()
    assert preview._is_visible is True
    row_a._on_action_btn = True
    preview.hide_preview(immediate=True)
    assert preview._is_visible is False

    # 4. Move to row B -> switches to row B
    row_a._on_action_btn = False
    row_a._is_hovered = False
    row_b._is_hovered = False
    row_b._on_mouse_enter()
    preview._on_show_timeout()
    qapp.processEvents()
    assert preview._is_visible is True
    assert preview._current_vehicle_id == "veh-102"

    # 5. Details click -> cancelled immediately
    preview.cancel_and_hide()
    assert preview._is_visible is False

    # 6. Edit button click -> cancelled immediately
    row_b._is_hovered = False
    row_b._on_mouse_enter()
    preview._on_show_timeout()
    assert preview._is_visible is True
    row_b._on_edit_clicked()
    assert preview._is_visible is False

    # 7. Scroll event -> cancelled immediately
    row_a._is_hovered = False
    row_a._on_mouse_enter()
    preview._on_show_timeout()
    assert preview._is_visible is True
    preview.cancel_and_hide()
    assert preview._is_visible is False

    # 8. Window deactivation -> cancelled immediately
    row_a._is_hovered = False
    row_a._on_mouse_enter()
    preview._on_show_timeout()
    assert preview._is_visible is True
    preview.cancel_and_hide()
    assert preview._is_visible is False
