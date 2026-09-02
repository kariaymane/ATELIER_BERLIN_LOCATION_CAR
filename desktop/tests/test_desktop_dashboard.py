import pytest
import sys
import os
from datetime import datetime, timedelta, timezone
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("CAR_RENTAL_DB_RESET", "1")
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
    assert combo.count() == 4
    assert combo.itemData(0) == "today"
    assert combo.itemData(1) == "week"
    assert combo.itemData(2) == "month"
    assert combo.itemData(3) == "year"

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
    assert widget._period_combo.count() == 4   # today / week / month / year


def test_vehicules_en_location_shows_only_the_count_no_denominator(qapp):
    """USER SCENARIO: 5 total vehicles, 2 reservations covering now (both still
    stored as RESERVED) -> the 'Véhicules en location' card must read exactly
    "2" — NO "/5", NO "2 sur 5", NO capacity ratio, NO progress bar.
    Future / cancelled / ended reservations must NOT inflate the count.
    """
    from app.database import get_local_session, init_local_db
    from app.models.vehicle import LocalVehicle
    from app.models.reservation import LocalReservation
    from app.sync.dashboard_cache import compute_local_overview

    init_local_db()
    s = get_local_session()
    now = datetime.now(timezone.utc)
    for i in range(5):
        s.add(LocalVehicle(
            id=f"envloc-v{i}", registration=f"EL-{i}", vin=f"EL{i}0000000000000",
            brand="B", model="M", year=2024, color="N", fuel_type="D",
            transmission="M", status="AVAILABLE", daily_rental_price=100,
            created_at=now.isoformat(), updated_at=now.isoformat(), version=1))

    def _res(rid, vid, start, end, status="RESERVED"):
        s.add(LocalReservation(
            id=rid, vehicle_id=vid, customer_name="X",
            start_datetime=start.isoformat(), end_datetime=end.isoformat(),
            daily_price=100, num_days=1, total_price=500, deposit=0, status=status,
            created_at=now.isoformat(), updated_at=now.isoformat(), version=1))

    # 2 covering now, still RESERVED status
    _res("r0", "envloc-v0", now - timedelta(days=1), now + timedelta(days=2))
    _res("r1", "envloc-v1", now - timedelta(hours=2), now + timedelta(days=1))
    # future -> RESERVED bucket, NOT en location
    _res("r2", "envloc-v2", now + timedelta(days=3), now + timedelta(days=5))
    # ended -> nothing
    _res("r3", "envloc-v3", now - timedelta(days=5), now - timedelta(days=1))
    # cancelled covering now -> nothing
    _res("r4", "envloc-v4", now - timedelta(days=1), now + timedelta(days=2), status="CANCELLED")
    s.commit(); s.close()

    ov = compute_local_overview()
    assert ov["total_vehicles"] == 5
    assert ov["rented"] == 2
    assert ov["reserved"] == 1          # only the future one
    assert ov["available"] == 2         # ended + cancelled vehicles are free

    widget = DashboardWidget()
    widget.refresh_data(ov, [])
    total = ov["available"] + ov["rented"] + ov["reserved"] + ov["maintenance"]
    assert total == 5
    # ONLY the number — the card no longer carries a denominator or a gauge.
    assert widget._card_rented._count_lbl.text() == "2"
    assert not hasattr(widget._card_rented, "_ratio_lbl")
    assert not hasattr(widget._card_rented, "_prog_bar")
    # and nothing anywhere on the card renders a "/5"-style ratio
    from PySide6.QtWidgets import QLabel
    for lbl in widget._card_rented.findChildren(QLabel):
        assert "/" not in lbl.text() and " sur " not in lbl.text()
