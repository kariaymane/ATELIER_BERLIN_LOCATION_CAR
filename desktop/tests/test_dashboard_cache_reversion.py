"""
Regression & parity tests verifying that live server dashboard data has strict authority
over local SQLite cache and that no background sync or domain reload causes cache reversion.
"""
import sys
import pytest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def main_window(qapp):
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
    win._is_online = True
    yield win
    try:
        win.deleteLater()
    except Exception:
        pass


def test_live_server_data_not_overwritten_by_domain_changed(main_window):
    """
    Core bug regression:
    1. Server returns live dashboard stats.
    2. UI displays live server data.
    3. Background sync / domain store reload emits _on_domain_changed.
    4. UI MUST retain the live server figures and NOT revert to local SQLite data.
    """
    server_overview = {
        "today_revenue": 7777.0,
        "today_rentals": 12,
        "week_rentals": 24,
        "month_rentals": 50,
        "year_rentals": 100,
        "rented": 42,
        "available": 8,
        "reserved": 5,
        "maintenance": 2,
        "active_maintenance_tickets": 2,
    }
    server_top = [
        {
            "brand": "AUTHORITATIVE_BRAND",
            "model": "AUTHORITATIVE_MODEL",
            "registration": "LIVE-999",
            "rental_count": 99,
            "total_revenue": 99999.0,
            "utilization_rate": 88.5,
        }
    ]

    # Step 1: Server data arrives
    main_window._on_dashboard_stats(server_overview, server_top, generation=main_window._dashboard_generation)

    # Server-authoritative non-fleet metrics are displayed
    assert main_window._dashboard._top_vehicles_data[0]["brand"] == "AUTHORITATIVE_BRAND"
    assert "En direct" in main_window._dashboard._last_refresh_lbl.text()
    assert main_window._authoritative_server_overview["today_revenue"] == 7777.0
    assert main_window._authoritative_server_overview["month_rentals"] == 50
    # Fleet counts reflect canonical local fleet (0 in empty DB, never fictitious server counts)
    assert main_window._dashboard._card_rented._count_lbl.text() == "0"
    assert main_window._dashboard._card_available._count_lbl.text() == "0"

    # Step 2: Background sync finishes -> DomainStore reloads and calls _on_domain_changed
    main_window._on_domain_changed(main_window._store.snapshot, main_window._store.revision + 1)

    # Step 3: Assert UI STILL retains server authoritative metrics and does NOT wipe them out
    assert main_window._dashboard._top_vehicles_data[0]["brand"] == "AUTHORITATIVE_BRAND"
    assert "En direct" in main_window._dashboard._last_refresh_lbl.text()
    assert main_window._authoritative_server_overview["today_revenue"] == 7777.0
    assert main_window._dashboard._card_rented._count_lbl.text() == "0"
    assert main_window._dashboard._card_available._count_lbl.text() == "0"


def test_out_of_order_dashboard_response_dropped(main_window):
    """
    Async race protection:
    Refresh #1 (gen 1) returns after Refresh #2 (gen 2).
    The older gen 1 response must be ignored.
    """
    main_window._dashboard_generation = 2

    # Gen 1 response arrives late
    stale_overview = {"today_revenue": 100.0, "today_rentals": 1, "rented": 1}
    stale_top = [{"brand": "STALE_CAR", "model": "STALE", "rental_count": 1}]
    main_window._on_dashboard_stats(stale_overview, stale_top, generation=1)

    assert main_window._has_server_dashboard is False

    # Gen 2 response arrives
    fresh_overview = {"today_revenue": 5000.0, "today_rentals": 10, "rented": 20}
    fresh_top = [{"brand": "FRESH_CAR", "model": "FRESH", "rental_count": 10}]
    main_window._on_dashboard_stats(fresh_overview, fresh_top, generation=2)

    assert main_window._has_server_dashboard is True
    assert main_window._authoritative_server_overview["today_revenue"] == 5000.0
    assert main_window._dashboard._top_vehicles_data[0]["brand"] == "FRESH_CAR"
    assert main_window._dashboard._card_rented._count_lbl.text() == "0"


def test_offline_fallback_marks_as_cached(main_window):
    """
    When offline, dashboard falls back to local SQLite snapshot and indicates cached status.
    """
    main_window._is_online = False
    main_window._has_server_dashboard = False

    main_window._refresh_dashboard(fetch_server=False)

    assert "Hors ligne / Cache" in main_window._dashboard._last_refresh_lbl.text()
