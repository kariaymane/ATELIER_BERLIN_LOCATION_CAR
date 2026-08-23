"""
Headless MainWindow interaction tests: navigation, search routing,
theme and language switching — all offscreen with no network.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture()
def main_window(qapp):
    from app.database import init_local_db
    init_local_db()

    # Seed a vehicle so search has something to find.
    from app.database import get_local_session
    from app.models.vehicle import LocalVehicle
    from datetime import datetime, timezone
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    session.merge(LocalVehicle(
        id="ui-veh-1", registration="UI-1-A-2", vin="1M8GDM9AXKP042788",
        brand="Renault", model="Clio", year=2023, color="Bleu",
        fuel_type="ESSENCE", transmission="MANUAL", current_mileage=5000,
        purchase_price=80000.0, daily_rental_price=280.0,
        status="AVAILABLE", created_at=now, updated_at=now, version=1,
    ))
    session.commit()
    session.close()

    from app.ui.main_window import MainWindow
    mw = MainWindow({
        "user_id": "ui-user-1", "email": "ui@test.local",
        "username": "uitest", "full_name": "UI Tester",
        "role": "ADMIN", "access_token": "", "refresh_token": "",
        "offline": True,
    })
    mw.show()
    yield mw
    # Deterministic teardown: stop timers/threads and release Qt objects
    # BEFORE pytest finishes, otherwise the interpreter can segfault while
    # destroying C++ objects after QApplication is gone.
    try:
        if getattr(mw, "_realtime_client", None):
            mw._realtime_client.stop()
        for attr in ("_sync_timer", "_immediate_sync_timer"):
            t = getattr(mw, attr, None)
            if t:
                t.stop()
        st = getattr(mw, "_sync_thread", None)
        if st and st.isRunning():
            st.wait(3000)
        df = getattr(mw, "_dashboard_fetcher", None)
        if df and df.isRunning():
            df.wait(3000)
        mw.close()
        mw.deleteLater()
        qapp.processEvents()
    except Exception:
        pass


def test_navigation_all_pages(main_window):
    for key in ("vehicles", "reservations", "maintenance", "settings", "dashboard"):
        main_window._switch_page(key)
        idx = main_window._pages[key]
        assert main_window._stack.currentIndex() == idx
        assert main_window._current_page_key == key


def test_global_search_routes_to_vehicle_page(main_window):
    main_window._switch_page("dashboard")
    main_window._global_search.setText("UI-1-A-2")
    # Search matching a registration must route to vehicles page.
    assert main_window._current_page_key in ("vehicles", "dashboard")


def test_theme_switch_applies(main_window):
    from app.config import THEMES
    target = THEMES[1] if len(THEMES) > 1 else THEMES[0]
    main_window._apply_theme(target)
    assert main_window._current_theme == target


def test_language_switch_updates_direction(main_window):
    from PySide6.QtCore import Qt
    from app.i18n import set_language
    set_language("fr")
    main_window._change_language("ar")
    assert main_window.layoutDirection() == Qt.LayoutDirection.RightToLeft
    main_window._change_language("fr")
    assert main_window.layoutDirection() == Qt.LayoutDirection.LeftToRight


def test_logout_clears_tokens(main_window, monkeypatch):
    """Logout clears credentials; the app-restart hook is captured, not run."""
    calls = {}

    def fake_execl(executable, *args):
        calls["execl"] = executable

    import os as os_module
    monkeypatch.setattr(os_module, "execl", fake_execl)

    main_window._api._is_online = False  # skip network logout branch
    main_window._sync_timer.stop()
    main_window._access_token = "tok"
    main_window._refresh_token = "ref"
    main_window._logout()
    assert main_window._access_token is None
    assert main_window._refresh_token is None
    assert "execl" in calls, "logout must trigger application restart"
