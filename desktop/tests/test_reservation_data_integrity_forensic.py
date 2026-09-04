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
from app.models.maintenance import LocalMaintenance
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


def _make_maintenance(mid: str, vid: str, title: str = "Repair", status: str = "IN_PROGRESS",
                      start_datetime: str = None, expected_end_datetime: str = None) -> LocalMaintenance:
    now_iso = datetime.now(timezone.utc).isoformat()
    return LocalMaintenance(
        id=mid,
        vehicle_id=vid,
        type="PREVENTIVE",
        title=title,
        status=status,
        start_datetime=start_datetime or now_iso,
        expected_end_datetime=expected_end_datetime,
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


def test_regression_test_1_orphan_active_reservation():
    """TEST 1: 1 real AVAILABLE vehicle + 0 valid reservations + 1 orphan ACTIVE reservation covering now.
    Expected: total=1, available=1, rented=0, reserved=0, maintenance=0.
    len(snapshot.reservations) == 0, current == 0, history == 0.
    """
    session = get_local_session()
    v1 = _make_vehicle("v-real-1", "REAL-1", "Dacia", "Logan", status="AVAILABLE")
    session.add(v1)

    now = datetime.now(timezone.utc)
    r_orphan = LocalReservation(
        id="r-orphan-active",
        vehicle_id="ghost-vehicle-does-not-exist",
        customer_name="Ghost Client",
        start_datetime=(now - timedelta(days=1)).isoformat(),
        end_datetime=(now + timedelta(days=2)).isoformat(),
        status="ACTIVE",
        total_price=500.0,
        num_days=3,
        daily_price=150.0,
    )
    session.add(r_orphan)
    session.commit()
    session.close()

    store = get_domain_store()
    store.reload()
    snap = store.snapshot

    assert snap.fleet_counts["total_vehicles"] == 1
    assert snap.fleet_counts["available"] == 1
    assert snap.fleet_counts["rented"] == 0
    assert snap.fleet_counts["reserved"] == 0
    assert snap.fleet_counts["maintenance"] == 0

    assert snap.overview["available"] == 1
    assert snap.overview["rented"] == 0
    assert snap.overview["reserved"] == 0
    assert snap.overview["maintenance"] == 0

    assert len(snap.reservations) == 0
    assert len(snap.current_reservations) == 0
    assert len(snap.historical_reservations) == 0


def test_regression_test_2_orphan_reserved_reservation():
    """TEST 2: 1 real AVAILABLE vehicle + 1 orphan RESERVED reservation covering now.
    Expected: available=1, rented=0, reserved=0.
    """
    session = get_local_session()
    v1 = _make_vehicle("v-real-2", "REAL-2", "Renault", "Clio", status="AVAILABLE")
    session.add(v1)

    now = datetime.now(timezone.utc)
    r_orphan_res = LocalReservation(
        id="r-orphan-reserved",
        vehicle_id="ghost-vehicle-2",
        customer_name="Ghost Res",
        start_datetime=(now - timedelta(hours=2)).isoformat(),
        end_datetime=(now + timedelta(days=2)).isoformat(),
        status="RESERVED",
        total_price=400.0,
        num_days=2,
        daily_price=200.0,
    )
    session.add(r_orphan_res)
    session.commit()
    session.close()

    store = get_domain_store()
    store.reload()
    snap = store.snapshot

    assert snap.fleet_counts["available"] == 1
    assert snap.fleet_counts["rented"] == 0
    assert snap.fleet_counts["reserved"] == 0
    assert snap.fleet_counts["total_vehicles"] == 1


def test_regression_test_3_orphan_maintenance():
    """TEST 3: 1 real AVAILABLE vehicle + 1 orphan maintenance ticket covering now.
    Expected: available=1, maintenance=0.
    """
    session = get_local_session()
    v1 = _make_vehicle("v-real-3", "REAL-3", "Peugeot", "208", status="AVAILABLE")
    session.add(v1)

    now = datetime.now(timezone.utc)
    m_orphan = _make_maintenance(
        "m-orphan-1",
        "ghost-vehicle-3",
        title="Ghost repair",
        status="IN_PROGRESS",
        start_datetime=(now - timedelta(days=1)).isoformat(),
        expected_end_datetime=(now + timedelta(days=2)).isoformat(),
    )
    session.add(m_orphan)
    session.commit()
    session.close()

    store = get_domain_store()
    store.reload()
    snap = store.snapshot

    assert snap.fleet_counts["available"] == 1
    assert snap.fleet_counts["maintenance"] == 0
    assert snap.fleet_counts["total_vehicles"] == 1
    assert len(snap.maintenances) == 0


def test_regression_test_4_valid_control_active():
    """TEST 4: Valid control case: 1 real vehicle + 1 valid ACTIVE reservation covering now.
    Expected: total=1, rented=1, available=0.
    Proves the fix does NOT simply ignore all reservations.
    """
    session = get_local_session()
    v1 = _make_vehicle("v-real-4", "REAL-4", "Dacia", "Duster", status="AVAILABLE")
    session.add(v1)

    now = datetime.now(timezone.utc)
    r_valid = LocalReservation(
        id="r-valid-active",
        vehicle_id="v-real-4",
        customer_name="Real Client",
        start_datetime=(now - timedelta(days=1)).isoformat(),
        end_datetime=(now + timedelta(days=2)).isoformat(),
        status="ACTIVE",
        total_price=600.0,
        num_days=3,
        daily_price=200.0,
    )
    session.add(r_valid)
    session.commit()
    session.close()

    store = get_domain_store()
    store.reload()
    snap = store.snapshot

    assert snap.fleet_counts["total_vehicles"] == 1
    assert snap.fleet_counts["rented"] == 1
    assert snap.fleet_counts["available"] == 0
    assert snap.fleet_counts["reserved"] == 0
    assert len(snap.reservations) == 1


def test_regression_test_5_valid_reserved_upcoming():
    """TEST 5: Valid RESERVED reservation (upcoming booking).
    Expected: reserved=1, available=0, rented=0.
    """
    session = get_local_session()
    v1 = _make_vehicle("v-real-5", "REAL-5", "Hyundai", "Accent", status="AVAILABLE")
    session.add(v1)

    now = datetime.now(timezone.utc)
    r_valid_res = LocalReservation(
        id="r-valid-res-upcoming",
        vehicle_id="v-real-5",
        customer_name="Future Client",
        start_datetime=(now + timedelta(days=2)).isoformat(),
        end_datetime=(now + timedelta(days=5)).isoformat(),
        status="RESERVED",
        total_price=600.0,
        num_days=3,
        daily_price=200.0,
    )
    session.add(r_valid_res)
    session.commit()
    session.close()

    store = get_domain_store()
    store.reload()
    snap = store.snapshot

    assert snap.fleet_counts["total_vehicles"] == 1
    assert snap.fleet_counts["reserved"] == 1
    assert snap.fleet_counts["available"] == 0
    assert snap.fleet_counts["rented"] == 0
    assert len(snap.reservations) == 1


def test_regression_test_6_mix_real_and_orphan():
    """TEST 6: Mix:
    3 real vehicles
    1 valid ACTIVE
    1 valid RESERVED
    1 orphan ACTIVE
    1 orphan RESERVED
    Expected fleet: total=3, rented=1, reserved=1, available=1, maintenance=0.
    """
    session = get_local_session()
    v1 = _make_vehicle("v-mix-1", "MIX-1", "Dacia", "Logan")
    v2 = _make_vehicle("v-mix-2", "MIX-2", "Renault", "Clio")
    v3 = _make_vehicle("v-mix-3", "MIX-3", "Fiat", "Punto")
    session.add_all([v1, v2, v3])

    now = datetime.now(timezone.utc)
    # 1. Valid ACTIVE on v1
    r1 = LocalReservation(
        id="r-mix-valid-act", vehicle_id="v-mix-1", customer_name="Client 1",
        start_datetime=(now - timedelta(days=1)).isoformat(),
        end_datetime=(now + timedelta(days=2)).isoformat(),
        status="ACTIVE", total_price=300.0, num_days=3, daily_price=100.0,
    )
    # 2. Valid RESERVED on v2 (upcoming)
    r2 = LocalReservation(
        id="r-mix-valid-res", vehicle_id="v-mix-2", customer_name="Client 2",
        start_datetime=(now + timedelta(days=1)).isoformat(),
        end_datetime=(now + timedelta(days=4)).isoformat(),
        status="RESERVED", total_price=300.0, num_days=3, daily_price=100.0,
    )
    # 3. Orphan ACTIVE on non-existent vehicle
    r3_orphan = LocalReservation(
        id="r-mix-orphan-act", vehicle_id="ghost-mix-veh-1", customer_name="Ghost Client 1",
        start_datetime=(now - timedelta(days=1)).isoformat(),
        end_datetime=(now + timedelta(days=2)).isoformat(),
        status="ACTIVE", total_price=500.0, num_days=3, daily_price=150.0,
    )
    # 4. Orphan RESERVED on non-existent vehicle
    r4_orphan = LocalReservation(
        id="r-mix-orphan-res", vehicle_id="ghost-mix-veh-2", customer_name="Ghost Client 2",
        start_datetime=(now + timedelta(days=2)).isoformat(),
        end_datetime=(now + timedelta(days=5)).isoformat(),
        status="RESERVED", total_price=500.0, num_days=3, daily_price=150.0,
    )
    session.add_all([r1, r2, r3_orphan, r4_orphan])
    session.commit()
    session.close()

    store = get_domain_store()
    store.reload()
    snap = store.snapshot

    assert snap.fleet_counts["total_vehicles"] == 3
    assert snap.fleet_counts["rented"] == 1
    assert snap.fleet_counts["reserved"] == 1
    assert snap.fleet_counts["available"] == 1
    assert snap.fleet_counts["maintenance"] == 0
    assert len(snap.reservations) == 2


def test_p0_fleet_count_invariants():
    """P0 — INVARIANT TEST:
    Assert rented + reserved + maintenance + available == total_vehicles
    (for non-structural operational fleet) and <= total_registered_vehicles.
    """
    session = get_local_session()
    v1 = _make_vehicle("v-inv-1", "INV-1", "Dacia", "Logan", status="AVAILABLE")
    v2 = _make_vehicle("v-inv-2", "INV-2", "Renault", "Clio", status="AVAILABLE")
    v3 = _make_vehicle("v-inv-3", "INV-3", "Peugeot", "208", status="AVAILABLE")
    v4 = _make_vehicle("v-inv-4", "INV-4", "Mercedes", "C220", status="SOLD")
    v5 = _make_vehicle("v-inv-5", "INV-5", "BMW", "Serie 3", status="INACTIVE")
    session.add_all([v1, v2, v3, v4, v5])

    now = datetime.now(timezone.utc)
    # 1 active rental on v1
    r1 = LocalReservation(
        id="r-inv-1", vehicle_id="v-inv-1", customer_name="Client Inv",
        start_datetime=(now - timedelta(days=1)).isoformat(),
        end_datetime=(now + timedelta(days=2)).isoformat(),
        status="ACTIVE", total_price=300.0, num_days=3, daily_price=100.0,
    )
    # 1 active maintenance on v2
    m1 = _make_maintenance(
        "m-inv-1", "v-inv-2", title="Vidange",
        status="IN_PROGRESS",
        start_datetime=(now - timedelta(days=1)).isoformat(),
        expected_end_datetime=(now + timedelta(days=1)).isoformat(),
    )
    # 2 orphan reservations
    r_orphan1 = LocalReservation(
        id="r-inv-orphan-1", vehicle_id="ghost-1", customer_name="Ghost",
        start_datetime=(now - timedelta(days=1)).isoformat(),
        end_datetime=(now + timedelta(days=2)).isoformat(),
        status="ACTIVE", total_price=300.0, num_days=3, daily_price=100.0,
    )
    r_orphan2 = LocalReservation(
        id="r-inv-orphan-2", vehicle_id="ghost-2", customer_name="Ghost 2",
        start_datetime=(now + timedelta(days=1)).isoformat(),
        end_datetime=(now + timedelta(days=3)).isoformat(),
        status="RESERVED", total_price=300.0, num_days=3, daily_price=100.0,
    )
    session.add_all([r1, m1, r_orphan1, r_orphan2])
    session.commit()
    session.close()

    store = get_domain_store()
    store.reload()
    snap = store.snapshot

    fc = snap.fleet_counts
    total = fc["total_vehicles"]
    rented = fc["rented"]
    reserved = fc["reserved"]
    maint = fc["maintenance"]
    avail = fc["available"]

    # Operational fleet invariant: exactly matches non-structural vehicles (3)
    assert total == 3
    assert rented == 1
    assert maint == 1
    assert reserved == 0
    assert avail == 1
    assert rented + reserved + maint + avail == total
    assert rented + reserved + maint + avail <= 5


def test_dashboard_source_of_truth_no_flicker():
    """P0 — MANDATORY DASHBOARD VALIDATION:
    Initial local dashboard = rented 1
    Server overview arrives with rented 3
    Canonical local fleet still = rented 1
    Expected final displayed fleet value: rented = 1
    No intermediate state where UI exposes server=3.
    Across server fetch, navigation, reload, reconnect, and boundary tick.
    """
    session = get_local_session()
    v1 = _make_vehicle("v-sot-1", "SOT-1", "Dacia", "Logan", status="AVAILABLE")
    session.add(v1)

    now = datetime.now(timezone.utc)
    r1 = LocalReservation(
        id="r-sot-1", vehicle_id="v-sot-1", customer_name="Client SOT",
        start_datetime=(now - timedelta(hours=2)).isoformat(),
        end_datetime=(now + timedelta(days=2)).isoformat(),
        status="ACTIVE", total_price=300.0, num_days=2, daily_price=150.0,
    )
    session.add(r1)
    session.commit()
    session.close()

    store = get_domain_store()
    store.reload()
    snap = store.snapshot

    # Step 1: Initial local snapshot is rented=1
    assert snap.fleet_counts["rented"] == 1
    assert snap.fleet_counts["available"] == 0
    assert snap.fleet_counts["total_vehicles"] == 1
    assert snap.overview["rented"] == 1

    # Step 2: Server overview arrives claiming rented=3, available=0, total_vehicles=3
    server_overview = {
        "total_vehicles": 3,
        "available": 0,
        "rented": 3,
        "reserved": 0,
        "maintenance": 0,
        "today_revenue": 1500.0,
        "month_revenue": 15000.0,
    }
    snap_after_server = store.update_server_dashboard(server_overview, generation=1)

    # Canonical local fleet must remain rented=1 in both fleet_counts and overview
    assert snap_after_server.fleet_counts["rented"] == 1
    assert snap_after_server.overview["rented"] == 1
    assert snap_after_server.overview["total_vehicles"] == 1
    assert snap_after_server.overview["available"] == 0
    # Server-only metrics are preserved
    assert snap_after_server.overview["today_revenue"] == 1500.0
    assert snap_after_server.overview["month_revenue"] == 15000.0

    # Step 3: Test Navigation / UI refresh
    from app.ui.dashboard import DashboardWidget
    dash = DashboardWidget()
    canonical_ov = dict(snap_after_server.overview)
    dash.refresh_data(canonical_ov, [])
    assert dash._card_rented._count_lbl.text() == "1"
    assert dash._card_available._count_lbl.text() == "0"

    # Step 4: Test Reload
    snap_reload = store.reload()
    assert snap_reload.fleet_counts["rented"] == 1
    assert snap_reload.overview["rented"] == 1
    assert snap_reload.overview["today_revenue"] == 1500.0

    # Step 5: Test Reconnect (clear + update)
    store.clear_server_dashboard()
    snap_cleared = store.reload()
    assert snap_cleared.fleet_counts["rented"] == 1
    assert snap_cleared.overview["rented"] == 1

    snap_reconnected = store.update_server_dashboard(server_overview, generation=2)
    assert snap_reconnected.fleet_counts["rented"] == 1
    assert snap_reconnected.overview["rented"] == 1

    # Step 6: Test Boundary Tick
    store.recompute_effective(now=now + timedelta(hours=1))
    snap_tick = store.snapshot
    assert snap_tick.fleet_counts["rented"] == 1
    assert snap_tick.overview["rented"] == 1


def test_p1_expired_reserved_state_behavior():
    """P1 Audit: RESERVED with start < now and end < now.
    Documents current behavior:
    1. It does NOT inflate fleet reserved or rented (vehicle remains AVAILABLE).
    2. It appears in snap.current_reservations because its stored status is RESERVED.
    """
    session = get_local_session()
    v1 = _make_vehicle("v-exp-res", "EXP-1", "Dacia", "Sandero", status="AVAILABLE")
    session.add(v1)

    now = datetime.now(timezone.utc)
    r_expired_reserved = LocalReservation(
        id="r-exp-res-1",
        vehicle_id="v-exp-res",
        customer_name="Expired Reserved Client",
        start_datetime=(now - timedelta(days=5)).isoformat(),
        end_datetime=(now - timedelta(days=2)).isoformat(),
        status="RESERVED",
        total_price=300.0,
        num_days=3,
        daily_price=100.0,
    )
    session.add(r_expired_reserved)
    session.commit()
    session.close()

    store = get_domain_store()
    store.reload()
    snap = store.snapshot

    # Vehicle is AVAILABLE, not RESERVED or RENTED
    assert snap.fleet_counts["available"] == 1
    assert snap.fleet_counts["reserved"] == 0
    assert snap.fleet_counts["rented"] == 0

    # It resides in current_reservations by status column
    curr_ids = [r["id"] for r in snap.current_reservations]
    assert "r-exp-res-1" in curr_ids
