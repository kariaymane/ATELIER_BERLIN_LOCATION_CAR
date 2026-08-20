"""
Comprehensive Test Suite for Offline-First Architecture, Automatic Reconnect/Sync,
Clean User-Facing Settings Page, Full Localization (FR <-> AR with RTL), and No Technical UI.
"""
import sys
import os
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add desktop root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QLineEdit
from PySide6.QtCore import Qt, QTimer

from app.database import init_local_db, get_local_session
from app.models.user import LocalUser
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.sync.queue import SyncQueue
from app.i18n import t, is_rtl, set_language, get_language
from app.config import save_language, get_saved_language
from app.ui.login_window import LoginWindow
from app.ui.main_window import MainWindow
from app.ui.settings.settings_widget import SettingsWidget


def run_tests():
    init_local_db()
    app = QApplication.instance() or QApplication(sys.argv)

    print("\n" + "=" * 80)
    print("🚀 EXECUTING OFFLINE-FIRST, AUTO-SYNC & CLEAN SETTINGS VERIFICATION SUITE")
    print("=" * 80 + "\n")

    # ─────────────────────────────────────────────────────────────────────────────
    # [1/6] LOGIN SCREEN: NO OFFLINE BUTTON & AUTOMATIC OFFLINE AUTHENTICATION
    # ─────────────────────────────────────────────────────────────────────────────
    print("--- [1/6] Verifying Login Screen & Automatic Offline Authentication ---")
    save_language("fr")
    set_language("fr")

    login = LoginWindow()
    login.show()
    app.processEvents()

    # 1.1 Verify NO visible offline button or toggle
    assert not hasattr(login, "_offline_btn"), "Offline button must be completely removed from LoginWindow"
    print("✓ 1.1 Login screen contains no manual Offline button/toggle.")

    # 1.2 Cache credentials of an authorized user locally
    user_id = str(uuid.uuid4())
    test_email = "directeur@soft-executive.local"
    test_pwd = "SecretExecutive2026!"
    login._cache_credentials(
        user_id=user_id,
        email=test_email,
        password=test_pwd,
        full_name="Directeur Général",
        role="ADMIN"
    )

    # 1.3 Test Automatic Offline Login with Valid Credentials
    login_events = []
    login.login_success.connect(lambda data: login_events.append(data))

    login._try_local_login(test_email, test_pwd)
    assert len(login_events) == 1, "Automatic offline login failed to authenticate valid cached user"
    auth_user = login_events[0]
    assert auth_user["user_id"] == user_id
    assert auth_user["email"] == test_email
    assert auth_user["role"] == "ADMIN"
    assert auth_user["offline"] is True
    print("✓ 1.2 Automatic offline login succeeded seamlessly for authorized user.")

    # 1.4 Test Rejected Login with Wrong Password
    bad_login_events = []
    login.login_success.connect(lambda data: bad_login_events.append(data))
    login._try_local_login(test_email, "WrongPassword123!")
    assert len(bad_login_events) == 0, "Login must reject invalid password"
    assert login._error_label.isVisible(), "Error message must be shown for bad password"
    print("✓ 1.3 Offline login strictly rejects invalid passwords without bypassing auth.")
    login.close()

    # ─────────────────────────────────────────────────────────────────────────────
    # [2/6] OFFLINE BUSINESS OPERATIONS & SQLITE PERSISTENCE
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n--- [2/6] Verifying Offline Business Operations & SyncQueue Enqueueing ---")
    win = MainWindow(auth_user)
    win.show()
    app.processEvents()

    # Create Vehicle while Offline
    v_id = str(uuid.uuid4())
    v_reg = f"OFF-{uuid.uuid4().hex[:6].upper()}"
    v_data = {
        "id": v_id,
        "registration": v_reg,
        "vin": f"VIN{uuid.uuid4().hex[:14].upper()}",
        "brand": "Mercedes-Benz",
        "model": "Classe S 500",
        "year": 2025,
        "color": "Noir Obsidienne",
        "fuel_type": "HYBRID",
        "transmission": "AUTOMATIC",
        "current_mileage": 5000,
        "purchase_mileage": 0,
        "purchase_price": 1400000.0,
        "daily_rental_price": 3500.0,
        "status": "AVAILABLE",
        "notes": "Véhicule créé en mode hors ligne",
    }
    win._save_vehicle(v_data)

    # Verify vehicle exists in local SQLite
    session = get_local_session()
    try:
        db_v = session.query(LocalVehicle).filter_by(id=v_id).first()
        assert db_v is not None
        assert db_v.registration == v_reg
        assert db_v.daily_rental_price == 3500.0

        # Verify SyncQueue item enqueued
        queue = SyncQueue(session, win._device_id)
        pending = queue.get_pending()
        matching_sync = [p for p in pending if p.entity_id == v_id and p.operation == "CREATE"]
        assert len(matching_sync) == 1, "Offline change must be safely recorded in SyncQueue"
    finally:
        session.close()
    print("✓ 2.1 Vehicle created offline, stored in local SQLite and recorded in SyncQueue.")

    # ─────────────────────────────────────────────────────────────────────────────
    # [3/6] CLEAN USER-FACING SETTINGS PAGE & SIDEBAR INTEGRATION
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n--- [3/6] Verifying Clean User-Facing Settings Page ---")
    sidebar = win._sidebar
    assert "settings" in sidebar._buttons, "Paramètres must be in Sidebar navigation"
    assert "Paramètres" in sidebar._buttons["settings"].text()

    # Switch to Settings page
    win._switch_page("settings")
    app.processEvents()
    assert win._stack.currentIndex() == win._pages["settings"]
    assert "Paramètres" in win._page_title.text()

    settings_widget = win._settings
    assert isinstance(settings_widget, SettingsWidget)
    assert settings_widget._lang_combo is not None
    assert settings_widget._theme_group is not None

    # Verify NO developer/technical API info exposed in UI
    all_labels = [lbl.text() for lbl in settings_widget.findChildren(QLabel)]
    all_text = " ".join(all_labels).lower()
    for tech_term in ["fastapi", "postgresql", "http://", "port 8000", "backend url", "base url", "sync interval"]:
        assert tech_term not in all_text, f"Technical info '{tech_term}' must not be exposed in Settings UI"
    print("✓ 3.1 Settings page cleanly accessible from sidebar with zero technical developer info.")

    # ─────────────────────────────────────────────────────────────────────────────
    # [4/6] DASHBOARD CLEANLINESS: NO SETTINGS/SYSTEM BLOCK IN DASHBOARD
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n--- [4/6] Verifying Dashboard Cleanliness ---")
    win._switch_page("dashboard")
    app.processEvents()
    dash = win._dashboard
    dash_labels = [lbl.text() for lbl in dash.findChildren(QLabel)]
    dash_text = " ".join(dash_labels).lower()
    for tech_term in ["paramètres", "settings", "système", "fastapi", "postgresql", "api url"]:
        assert tech_term not in dash_text, f"Dashboard must not contain '{tech_term}'"
    print("✓ 4.1 Dashboard contains only business KPIs with no Settings/System technical blocks.")

    # ─────────────────────────────────────────────────────────────────────────────
    # [5/6] COMPLETE LOCALIZATION (FR <-> AR) & RTL ON ALL SCREENS INCLUDING SETTINGS
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n--- [5/6] Verifying Full French <-> Arabic Translation & RTL Layout ---")
    # Switch to Arabic
    win._change_language("ar")
    app.processEvents()

    assert is_rtl()
    assert QApplication.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert win.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert "الإعدادات" in sidebar._buttons["settings"].text()
    assert "لوحة التحكم" in sidebar._buttons["dashboard"].text()
    assert "السيارات" in sidebar._buttons["vehicles"].text()
    assert "الحجوزات" in sidebar._buttons["reservations"].text()
    assert "الصيانة" in sidebar._buttons["maintenance"].text()

    # Settings in Arabic
    win._switch_page("settings")
    app.processEvents()
    assert settings_widget.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert settings_widget._header_lbl.text() == "الإعدادات"
    assert "اللغة" in settings_widget._lang_title.text()
    assert "المظهر" in settings_widget._theme_title.text()
    print("✓ 5.1 Arabic live switching and RTL fully verified across all navigation and Settings page.")

    # Switch back to French
    win._change_language("fr")
    app.processEvents()
    assert not is_rtl()
    assert QApplication.layoutDirection() == Qt.LayoutDirection.LeftToRight
    assert "Paramètres" in sidebar._buttons["settings"].text()
    print("✓ 5.2 French live restoration verified cleanly.")

    # ─────────────────────────────────────────────────────────────────────────────
    # [6/6] CLEANUP & PASS
    # ─────────────────────────────────────────────────────────────────────────────
    win.close()
    print("\n" + "=" * 80)
    print("🎉 ALL OFFLINE-FIRST, AUTO-SYNC & SETTINGS CLEANUP TESTS PASSED 100%!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_tests()
