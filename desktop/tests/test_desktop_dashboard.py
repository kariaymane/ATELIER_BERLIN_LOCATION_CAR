import pytest
import sys
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication

from app.ui.dashboard import DashboardWidget, OperationalStatCard, ExecutiveFleetCard


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_dashboard_initialization_and_periods(qapp):
    widget = DashboardWidget()
    assert widget is not None

    # Verify period selector states exist
    combo = widget._period_combo
    assert combo.count() == 3
    assert combo.itemData(0) == "today"
    assert combo.itemData(1) == "week"
    assert combo.itemData(2) == "month"

    # Test callback _on_period_changed does not crash for all 3 states
    sample_overview = {
        "total_vehicles": 10,
        "available": 6,
        "rented": 3,
        "reserved": 1,
        "maintenance": 0,
        "active_maintenances": 0,
        "day_locations": 2,
        "today_revenue": 900.0,
        "week_locations": 7,
        "week_revenue": 3150.0,
        "month_locations": 25,
        "month_revenue": 11250.0,
    }
    sample_top = [
        {"id": "v1", "brand": "Porsche", "model": "Macan", "registration": "12345-A-1", "rental_count": 5},
        {"id": "v2", "brand": "Mercedes", "model": "Classe C", "registration": "67890-B-2", "rental_count": 3},
    ]

    widget.refresh_data(sample_overview, sample_top)

    # 1. Test Today
    combo.setCurrentIndex(0)
    assert widget._current_period == "today"
    assert "900.00 DH" in widget._card_revenue._count_lbl.text()
    assert widget._card_day._count_lbl.text() == "2"

    # 2. Test Week
    combo.setCurrentIndex(1)
    assert widget._current_period == "week"
    assert "3150.00 DH" in widget._card_revenue._count_lbl.text()
    assert widget._card_day._count_lbl.text() == "7"

    # 3. Test Month
    combo.setCurrentIndex(2)
    assert widget._current_period == "month"
    assert "11250.00 DH" in widget._card_revenue._count_lbl.text()
    assert widget._card_day._count_lbl.text() == "25"

    # Verify fleet cards counts
    assert widget._card_available._count_lbl.text() == "6"
    assert widget._card_rented._count_lbl.text() == "3"

    # Test live retranslation
    widget.retranslate_ui()
    assert widget._period_combo.count() == 3
