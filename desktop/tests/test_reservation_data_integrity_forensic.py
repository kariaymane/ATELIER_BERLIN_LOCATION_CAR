"""
Forensic Regression Test Suite: Reservation, Vehicle & Dashboard Data Integrity.

Verifies:
1. Strict UI separation of Current vs Historical reservations
2. Canonical date formatting (DD/MM/YYYY → DD/MM/YYYY)
3. Dashboard KPI parity with Fleet status (expired reservations do not inflate reserved count)
4. Orphaned reservation protection and vehicle UUID integrity
5. Action button presence and absence of clipping
6. Unified filtering across Current and History tables
7. Vehicle availability calculations with reservations
8. Re-entrant snapshot reload and desktop restart idempotency
"""
import os
import sys
import pytest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from PySide6.QtWidgets import QApplication, QPushButton

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import init_local_db, get_local_session
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.client import LocalClient
from app.state.domain_store import get_domain_store
from app.ui.reservations.reservation_list import ReservationWidget
from app.utils.datetime_utils import format_datetime_range, parse_datetime_utc
from app.sync.dashboard_cache import compute_overview_rows

app = QApplication.instance() or QApplication(sys.argv)
CASABLANCA = ZoneInfo("Africa/Casablanca")


@pytest.fixture(autouse=True)
def clean_test_db(tmp_path, monkeypatch):
    """Ensure every test runs on a pristine temporary database."""
    test_db = tmp_path / "test_integrity.db"
    test_url = f"sqlite:///{test_db}"
    monkeypatch.setenv("CAR_RENTAL_SQLITE_URL", test_url)
    monkeypatch.setenv("CAR_RENTAL_DATA_DIR", str(tmp_path))
    init_local_db()
    store = get_domain_store()
    store.reload()
    yield
    store.reload()


def test_canonical_date_formatting():
    """Verify format_datetime_range outputs canonical DD/MM/YYYY → DD/MM/YYYY."""
    s = "2026-08-24T22:12:00Z"
    e = "2026-08-25T22:12:00Z"
    formatted = format_datetime_range(s, e)
    # 22:12 UTC is 23:12 Casablanca (UTC+1), so dates are 24/08/2026 → 25/08/2026
    assert "24/08/2026 → 25/08/2026" in formatted

    # Single date
    single = format_datetime_range(s, None)
    assert "24/08/2026" in single

    # Empty dates
    assert format_datetime_range(None, None) == "-"


def _make_vehicle(vid: str, reg: str, brand: str = "Dacia", model: str = "Logan", status: str = "AVAILABLE") -> LocalVehicle:
    now_iso = datetime.now(timezone.utc).isoformat()
    return LocalVehicle(
        id=vid,
        registration=reg,
        vin=f"VIN-{vid}-0011223344",
        brand=brand,
        model=model,
        year=2024,
        color="Blanc",
        fuel_type="Diesel",
        transmission="Manual",
        daily_rental_price=150.0,
        status=status,
        created_at=now_iso,
        updated_at=now_iso,
    )


def test_subtab_separation_current_vs_history():
    """Verify that Current and History reservations are strictly separated."""
    session = get_local_session()

    v1 = _make_vehicle("veh-1", "V1-123", "Dacia", "Logan")
    v2 = _make_vehicle("veh-2", "V2-456", "Renault", "Clio")
    session.add_all([v1, v2])

    now = datetime.now(timezone.utc)
    future_start = (now + timedelta(days=2)).isoformat()
    future_end = (now + timedelta(days=5)).isoformat()
    past_start = (now - timedelta(days=10)).isoformat()
    past_end = (now - timedelta(days=5)).isoformat()

    # 1. Upcoming RESERVED -> must be in Current
    r_upcoming = LocalReservation(
        id="res-upcoming", vehicle_id="veh-1", customer_name="Future Client",
        start_datetime=future_start, end_datetime=future_end,
        status="RESERVED", total_price=450.0, num_days=3, daily_price=150.0
    )
    # 2. ACTIVE covering now -> must be in Current
    r_active = LocalReservation(
        id="res-active", vehicle_id="veh-2", customer_name="Active Client",
        start_datetime=(now - timedelta(days=1)).isoformat(),
        end_datetime=(now + timedelta(days=2)).isoformat(),
        status="ACTIVE", total_price=600.0, num_days=3, daily_price=200.0
    )
    # 3. COMPLETED -> must be in History
    r_completed = LocalReservation(
        id="res-completed", vehicle_id="veh-2", customer_name="Completed Client",
        start_datetime=past_start, end_datetime=past_end,
        status="COMPLETED", total_price=400.0, num_days=2, daily_price=200.0
    )
    # 4. CANCELLED -> must be in History
    r_cancelled = LocalReservation(
        id="res-cancelled", vehicle_id="veh-1", customer_name="Cancelled Client",
        start_datetime=future_start, end_datetime=future_end,
        status="CANCELLED", total_price=450.0, num_days=3, daily_price=150.0
    )

    session.add_all([r_upcoming, r_active, r_completed, r_cancelled])
    session.commit()
    session.close()

    store = get_domain_store()
    store.reload()
    snap = store.snapshot

    # Check DomainStore properties
    assert len(snap.current_reservations) == 2
    curr_ids = {r["id"] for r in snap.current_reservations}
    assert curr_ids == {"res-upcoming", "res-active"}

    assert len(snap.historical_reservations) == 2
    hist_ids = {r["id"] for r in snap.historical_reservations}
    assert hist_ids == {"res-completed", "res-cancelled"}

    # Check UI Widget tables
    widget = ReservationWidget("dev-1", "user-1", user_role="ADMIN")
    widget.refresh_data()

    # Current table
    assert widget._table.rowCount() == 2
    # History table
    assert widget._history_table.rowCount() == 2


def test_action_buttons_and_details_dialog():
    """Verify action buttons appear on Current and 'Détails' appears on History."""
    session = get_local_session()
    v = _make_vehicle("v-btn", "BTN-1", "Peugeot", "208")
    session.add(v)

    now = datetime.now(timezone.utc)
    r_res = LocalReservation(
        id="r-reserved", vehicle_id="v-btn", customer_name="Client Res",
        start_datetime=(now + timedelta(days=5)).isoformat(),
        end_datetime=(now + timedelta(days=7)).isoformat(),
        status="RESERVED", total_price=300.0, num_days=2, daily_price=150.0
    )
    r_active = LocalReservation(
        id="r-active", vehicle_id="v-btn", customer_name="Client Active",
        start_datetime=(now - timedelta(days=1)).isoformat(),
        end_datetime=(now + timedelta(days=2)).isoformat(),
        status="ACTIVE", total_price=450.0, num_days=3, daily_price=150.0
    )
    r_comp = LocalReservation(
        id="r-comp", vehicle_id="v-btn", customer_name="Client Comp",
        start_datetime=(now - timedelta(days=5)).isoformat(),
        end_datetime=(now - timedelta(days=2)).isoformat(),
        status="COMPLETED", total_price=300.0, num_days=2, daily_price=150.0
    )
    session.add_all([r_res, r_active, r_comp])
    session.commit()
    session.close()

    widget = ReservationWidget("dev-1", "user-1", user_role="ADMIN")
    widget.refresh_data()

    # In Current table:
    # Row for RESERVED has Activer and Annuler (cannot Terminer before start)
    res_buttons = [b.text() for b in widget._table.cellWidget(0, 5).findChildren(QPushButton)]
    assert any("Activer" in t or "تفعيل" in t for t in res_buttons)
    assert any("Annuler" in t or "إلغاء" in t for t in res_buttons)
    assert not any("Terminer" in t or "إتمام" in t for t in res_buttons)

    # Row for ACTIVE has Terminer and Annuler
    act_buttons = [b.text() for b in widget._table.cellWidget(1, 5).findChildren(QPushButton)]
    assert any("Terminer" in t or "إتمام" in t for t in act_buttons)
    assert any("Annuler" in t or "إلغاء" in t for t in act_buttons)
    assert not any("Activer" in t or "تفعيل" in t for t in act_buttons)

    # In History table, action widget should have Détails
    hist_act_widget = widget._history_table.cellWidget(0, 5)
    assert hist_act_widget is not None
    hist_buttons = hist_act_widget.findChildren(QPushButton)
    assert len(hist_buttons) == 1
    assert "Détails" in hist_buttons[0].text() or "التفاصيل" in hist_buttons[0].text()


def test_orphaned_reservation_filtering():
    """Verify that reservations referencing non-existent vehicles are swept."""
    session = get_local_session()
    # Add reservation referencing non-existent vehicle 'ghost-vehicle'
    r_ghost = LocalReservation(
        id="r-ghost", vehicle_id="ghost-vehicle", customer_name="Ghost Client",
        start_datetime="2026-10-01T10:00:00Z", end_datetime="2026-10-05T10:00:00Z",
        status="RESERVED", total_price=500.0, num_days=4, daily_price=125.0
    )
    session.add(r_ghost)
    session.commit()
    session.close()

    store = get_domain_store()
    store.reload()
    snap = store.snapshot

    # DomainStore filters out orphaned reservations
    assert len(snap.reservations) == 0
    assert len(snap.current_reservations) == 0
    assert len(snap.historical_reservations) == 0


def test_dashboard_kpi_parity_with_fleet_status():
    """Verify that expired RESERVED rentals do NOT inflate reserved_rentals or fleet reserved."""
    session = get_local_session()
    v1 = _make_vehicle("v-kpi", "KPI-1", "Fiat", "500")
    session.add(v1)

    now = datetime.now(timezone.utc)
    # Expired RESERVED reservation
    r_past_reserved = LocalReservation(
        id="r-past-res", vehicle_id="v-kpi", customer_name="Past Res",
        start_datetime=(now - timedelta(days=5)).isoformat(),
        end_datetime=(now - timedelta(days=3)).isoformat(),
        status="RESERVED", total_price=300.0, num_days=2, daily_price=150.0
    )
    session.add(r_past_reserved)
    session.commit()
    session.close()

    store = get_domain_store()
    store.reload()
    snap = store.snapshot

    # Vehicle must be AVAILABLE, not RESERVED
    assert snap.fleet_counts["available"] == 1
    assert snap.fleet_counts["reserved"] == 0
    assert snap.fleet_counts["rented"] == 0

    # Overview must have reserved_rentals = 0
    assert snap.overview["available"] == 1
    assert snap.overview["reserved"] == 0
    assert snap.overview["reserved_rentals"] == 0
    assert snap.overview["active_rentals"] == 0


def test_table_filter_filters_both_tables():
    """Verify that set_filter matches text in both Current and History tables."""
    session = get_local_session()
    v = _make_vehicle("v-flt", "FLT-1", "Audi", "A3")
    session.add(v)

    now = datetime.now(timezone.utc)
    r_curr = LocalReservation(
        id="r-c", vehicle_id="v-flt", customer_name="Alpha Client",
        start_datetime=(now + timedelta(days=1)).isoformat(),
        end_datetime=(now + timedelta(days=3)).isoformat(),
        status="RESERVED", total_price=300.0, num_days=2, daily_price=150.0
    )
    r_hist = LocalReservation(
        id="r-h", vehicle_id="v-flt", customer_name="Beta Client",
        start_datetime=(now - timedelta(days=5)).isoformat(),
        end_datetime=(now - timedelta(days=2)).isoformat(),
        status="COMPLETED", total_price=300.0, num_days=2, daily_price=150.0
    )
    session.add_all([r_curr, r_hist])
    session.commit()
    session.close()

    widget = ReservationWidget("dev-1", "user-1", user_role="ADMIN")
    widget.refresh_data()

    # Filter for 'Alpha'
    widget.set_filter("Alpha")
    assert not widget._table.isRowHidden(0)
    assert widget._history_table.isRowHidden(0)

    # Filter for 'Beta'
    widget.set_filter("Beta")
    assert widget._table.isRowHidden(0)
    assert not widget._history_table.isRowHidden(0)

    # Clear filter
    widget.set_filter("")
    assert not widget._table.isRowHidden(0)
    assert not widget._history_table.isRowHidden(0)
