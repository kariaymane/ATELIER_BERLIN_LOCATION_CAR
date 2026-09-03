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


def test_dashboard_revenue_panel_periods_and_custom_range(qapp):
    from datetime import date
    widget = DashboardWidget()
    assert widget is not None

    combo = widget._period_combo
    # 8 presets + Personnalisé
    names = [combo.itemData(i) for i in range(combo.count())]
    assert names == ["today", "yesterday", "week", "last_week",
                     "month", "last_month", "year", "last_year", "custom"]

    # provider records the range it was asked for and returns a fixed number
    calls = []
    def provider(frm, to):
        calls.append((frm, to))
        return 4242.0, "server"
    widget.set_revenue_provider(provider)

    # preset "today" -> from == to == today
    combo.setCurrentIndex(names.index("today"))
    widget._revenue_worker.wait(3000)
    qapp.processEvents()
    assert calls[-1][0] == calls[-1][1] == date.today()
    assert "4 242.00 DH" in widget._revenue_value_lbl.text()
    assert widget._custom_row.isHidden() is True

    # preset "last_month" -> a full previous calendar month
    combo.setCurrentIndex(names.index("last_month"))
    widget._revenue_worker.wait(3000)
    f, t_ = calls[-1]
    assert f.day == 1 and t_.month == f.month and (t_ + __import__("datetime").timedelta(days=1)).day == 1

    # Personnalisé -> date pickers appear and drive the query
    combo.setCurrentIndex(names.index("custom"))
    assert widget._custom_row.isHidden() is False
    from PySide6.QtCore import QDate
    widget._date_from.setDate(QDate(2026, 3, 1))
    widget._date_to.setDate(QDate(2026, 3, 15))
    widget._revenue_worker.wait(3000)
    assert calls[-1] == (date(2026, 3, 1), date(2026, 3, 15))

    # error source -> "données indisponibles", not a stale number
    widget._on_revenue_done(-1.0, "error")
    assert "indispon" in widget._revenue_value_lbl.text().lower()

    widget.retranslate_ui()
    assert widget._period_combo.count() == 9
    widget._revenue_worker.wait(3000)
    qapp.processEvents()
    widget.close()


def test_dashboard_reads_maintenance_from_canonical_key(qapp):
    """C1: the operational 'Maintenances actives' card must show the same
    number as the fleet card, whichever key the payload used."""
    widget = DashboardWidget()
    widget.set_revenue_provider(lambda f, t: (0.0, "local"))
    widget.refresh_data({
        "total_vehicles": 3, "available": 0, "rented": 1,
        "reserved": 0, "maintenance": 2,
        "active_maintenance_tickets": 2,  # online payload key
    }, [])
    assert widget._card_maintenance._count_lbl.text() == "2"
    assert widget._card_fleet_maintenance._count_lbl.text() == "2"


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
    s.query(LocalReservation).delete()
    s.query(LocalVehicle).delete()
    s.commit()
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
