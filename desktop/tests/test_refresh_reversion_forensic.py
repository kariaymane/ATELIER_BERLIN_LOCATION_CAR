"""
Dedicated forensic regression tests proving:
1. OLD -> Refresh -> NEW -> late OLD response -> REMAINS NEW
2. Rapid multiple refreshes
3. Background sync during refresh
4. WebSocket/realtime event during refresh
5. Startup refresh
6. Offline cache & reconnect
7. Tab switching preserves server authority
"""
import sys
import pytest
from datetime import datetime, timezone, date, timedelta
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow
from app.state.domain_store import get_domain_store, reset_domain_store, DomainSnapshot
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.database import get_local_session, init_local_db
from app.services.event_bus import get_event_bus


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def fresh_store():
    init_local_db()
    store = reset_domain_store()
    store.clear_server_dashboard()
    return store


@pytest.fixture
def main_window(qapp, fresh_store):
    user_data = {
        "id": "user-test",
        "user_id": "user-test",
        "access_token": "dummy-token",
        "refresh_token": "dummy-refresh",
        "full_name": "Test Admin",
        "role": "ADMIN",
        "offline": False,
    }
    win = MainWindow(user_data)
    win._sync_timer.stop()  # disable periodic sync for deterministic test control
    win._is_online = True
    yield win
    try:
        win.deleteLater()
    except Exception:
        pass


def test_old_refresh_new_late_old_response_retained_as_new(main_window, fresh_store):
    """
    Mandated scenario:
    OLD DATA -> Refresh -> NEW DATA -> late OLD response -> REMAINS NEW.
    """
    # 1. Setup local SQLite with OLD data
    session = get_local_session()
    session.query(LocalReservation).delete()
    session.query(LocalVehicle).delete()
    now_iso = datetime.now(timezone.utc).isoformat()
    old_veh = LocalVehicle(
        id="v-old",
        registration="OLD-001",
        vin="11111111111111111",
        brand="OldCar",
        model="Stale",
        year=2020,
        color="Noir",
        fuel_type="DIESEL",
        transmission="MANUAL",
        daily_rental_price=100.0,
        status="AVAILABLE",
        created_at=now_iso,
        updated_at=now_iso,
        version=1
    )
    session.add(old_veh)
    session.commit()
    session.close()

    fresh_store.clear_server_dashboard()
    fresh_store.reload()
    main_window._refresh_dashboard(fetch_server=False)

    # Initial state: old data from SQLite
    assert main_window._dashboard._card_available._count_lbl.text() == "1"
    assert main_window._dashboard._card_rented._count_lbl.text() == "0"

    # 2. User clicks Refresh -> Request generation bumped
    main_window._dashboard_generation = 1

    # 3. Server returns NEW authoritative data (generation 1)
    new_server_overview = {
        "total_vehicles": 3,
        "available": 0,
        "reserved": 0,
        "rented": 3,
        "maintenance": 0,
        "active_rentals": 1,
        "today_rentals": 2,
        "today_revenue": 3200.0,
        "week_revenue": 14200.0,
        "month_revenue": 22000.0,
        "year_revenue": 51300.0,
    }
    server_top = [{"brand": "NEW_BRAND", "model": "NEW_MODEL", "rental_count": 10}]
    main_window._on_dashboard_stats(new_server_overview, server_top, generation=1)

    # UI now displays NEW live data
    assert main_window._dashboard._card_available._count_lbl.text() == "0"
    assert main_window._dashboard._card_rented._count_lbl.text() == "3"
    assert "En direct" in main_window._dashboard._last_refresh_lbl.text()

    # 4. Late OLD response arrives (generation 0 or from earlier fetcher)
    stale_overview = {"available": 999, "rented": 888}
    stale_top = [{"brand": "STALE_CAR", "rental_count": 1}]
    main_window._on_dashboard_stats(stale_overview, stale_top, generation=0)

    # UI MUST RETAIN NEW DATA — late response rejected!
    assert main_window._dashboard._card_available._count_lbl.text() == "0"
    assert main_window._dashboard._card_rented._count_lbl.text() == "3"
    assert main_window._dashboard._top_vehicles_data[0]["brand"] == "NEW_BRAND"


def test_rapid_multiple_refreshes(main_window):
    """
    Rapid multiple refreshes (clicks):
    Generations 1, 2, 3, 4, 5.
    Older responses arriving out of order are dropped.
    Only latest generation 5 is accepted.
    """
    for gen in range(1, 6):
        main_window._dashboard_generation = gen

    assert main_window._dashboard_generation == 5

    # Out of order returns: gen 2 arrives
    gen2_ov = {"rented": 2, "available": 2}
    main_window._on_dashboard_stats(gen2_ov, [], generation=2)
    assert getattr(main_window, "_has_server_dashboard", False) is False

    # Out of order returns: gen 4 arrives
    gen4_ov = {"rented": 4, "available": 4}
    main_window._on_dashboard_stats(gen4_ov, [], generation=4)
    assert getattr(main_window, "_has_server_dashboard", False) is False

    # Latest response: gen 5 arrives
    gen5_ov = {"rented": 50, "available": 5, "total_vehicles": 55}
    main_window._on_dashboard_stats(gen5_ov, [], generation=5)
    assert getattr(main_window, "_has_server_dashboard", False) is True
    assert main_window._dashboard._card_rented._count_lbl.text() == "50"
    assert main_window._dashboard._card_available._count_lbl.text() == "5"


def test_background_sync_during_refresh(main_window, fresh_store):
    """
    Background sync completes and reloads DomainStore while live server metrics are active.
    Live server data MUST NOT be overwritten by the background sync SQLite reload.
    """
    server_overview = {
        "total_vehicles": 3,
        "available": 0,
        "reserved": 0,
        "rented": 3,
        "maintenance": 0,
        "month_revenue": 22000.0,
    }
    main_window._on_dashboard_stats(server_overview, [], generation=1)

    assert main_window._dashboard._card_rented._count_lbl.text() == "3"

    # Background sync completes:
    sync_report = {"is_online": True, "pull": {"items": []}, "push": {"pushed": 0}}
    main_window._on_sync_finished(sync_report)

    # DomainStore reload triggered:
    fresh_store.reload()

    # UI MUST still display server figures
    assert main_window._dashboard._card_rented._count_lbl.text() == "3"
    assert main_window._dashboard._card_available._count_lbl.text() == "0"


def test_websocket_realtime_event_during_refresh(main_window, fresh_store):
    """
    Realtime WebSocket event arrives during refresh and triggers data_refreshed.
    Live dashboard metrics MUST remain authoritative.
    """
    server_overview = {"total_vehicles": 3, "available": 0, "rented": 3}
    main_window._on_dashboard_stats(server_overview, [], generation=1)

    # Simulate WebSocket emitting data_refreshed event
    get_event_bus().data_refreshed.emit()

    assert main_window._dashboard._card_rented._count_lbl.text() == "3"
    assert main_window._dashboard._card_available._count_lbl.text() == "0"


def test_startup_refresh(main_window, fresh_store):
    """
    Startup sequence:
    1. Initially renders offline snapshot (or blank)
    2. Server returns -> transitions to live
    3. Subsequent sync cycles do not cause reversion
    """
    # 1. Startup: no server dashboard yet
    main_window._has_server_dashboard = False
    fresh_store.clear_server_dashboard()
    main_window._refresh_dashboard(fetch_server=False)
    assert "Hors ligne / Cache" in main_window._dashboard._last_refresh_lbl.text()

    # 2. Server response arrives
    server_overview = {"total_vehicles": 3, "available": 0, "rented": 3}
    main_window._on_dashboard_stats(server_overview, [], generation=1)
    assert "En direct" in main_window._dashboard._last_refresh_lbl.text()
    assert main_window._dashboard._card_rented._count_lbl.text() == "3"

    # 3. Follow-up sync cycle finishes
    main_window._on_sync_finished({"is_online": True})
    assert "En direct" in main_window._dashboard._last_refresh_lbl.text()
    assert main_window._dashboard._card_rented._count_lbl.text() == "3"


def test_offline_cache_and_reconnect(main_window, fresh_store):
    """
    When a network glitch or offline report arrives:
    Authoritative server data MUST NOT be wiped out or reverted to 0.
    When reconnect happens:
    State updates cleanly.
    """
    server_overview = {"total_vehicles": 3, "available": 0, "rented": 3, "month_revenue": 22000.0}
    main_window._on_dashboard_stats(server_overview, [], generation=1)
    assert main_window._dashboard._card_rented._count_lbl.text() == "3"

    # Network glitch occurs
    main_window._on_sync_finished({"is_online": False, "error": "timeout"})
    # Must NOT revert to local SQLite or zero:
    assert main_window._dashboard._card_rented._count_lbl.text() == "3"
    assert main_window._dashboard._card_available._count_lbl.text() == "0"

    # Network reconnects
    main_window._on_sync_finished({"is_online": True})
    assert main_window._dashboard._card_rented._count_lbl.text() == "3"


def test_tab_switching_preserves_server_authority(main_window):
    """
    User switches between tabs (Dashboard -> Vehicles -> Reservations -> Dashboard).
    Dashboard MUST NOT lose its authoritative server figures.
    """
    server_overview = {"total_vehicles": 3, "available": 0, "rented": 3}
    main_window._on_dashboard_stats(server_overview, [], generation=1)
    assert main_window._dashboard._card_rented._count_lbl.text() == "3"

    # Navigate to vehicles
    main_window._switch_page("vehicles")
    assert main_window._current_page_key == "vehicles"

    # Navigate to reservations
    main_window._switch_page("reservations")
    assert main_window._current_page_key == "reservations"

    # Navigate back to dashboard
    main_window._switch_page("dashboard")
    assert main_window._current_page_key == "dashboard"
    assert main_window._dashboard._card_rented._count_lbl.text() == "3"
    assert main_window._dashboard._card_available._count_lbl.text() == "0"


def test_local_revenue_worker_cannot_downgrade_live_server_revenue(main_window):
    """
    Live server revenue is displayed.
    A background revenue worker fails and returns source="local" with 0.0 DH.
    Dashboard MUST reject the local downgrade and preserve the live server revenue.
    """
    server_overview = {
        "total_vehicles": 3, "available": 0, "rented": 3,
        "month_revenue": 22000.0, "today_revenue": 3200.0,
    }
    main_window._on_dashboard_stats(server_overview, [], generation=1)

    rev_text_before = main_window._dashboard._revenue_value_lbl.text()
    assert rev_text_before != "—" and rev_text_before != "0.00 DH"

    # Background worker attempts local fallback
    req_id = main_window._dashboard._revenue_req_id
    main_window._dashboard._on_revenue_done(0.0, "local", req_id=req_id)

    rev_text_after = main_window._dashboard._revenue_value_lbl.text()
    assert rev_text_after == rev_text_before
    assert rev_text_after != "0.00 DH"
