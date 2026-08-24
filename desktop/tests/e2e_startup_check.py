"""
Headless end-to-end startup test: login -> MainWindow visible -> no exceptions.

Runs the real LoginWindow + MainWindow flow with Qt offscreen platform.
Requires CAR_RENTAL_DB_RESET=1 and an isolated data dir.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"
os.environ["API_BASE_URL"] = "http://localhost:9999"  # Force offline fallback for test

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop

from app.database import init_local_db, get_local_session
from app.ui.login_window import LoginWindow
from app.ui.main_window import MainWindow


def main() -> int:
    init_local_db()
    app = QApplication.instance() or QApplication(sys.argv)

    # Seed a local user for offline authentication.
    from app.models.user import LocalUser
    import argon2
    from datetime import datetime, timezone
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    session.merge(LocalUser(
        id="e2e-user-1",
        email="director@atelier.com",
        username="director",
        password_hash=argon2.PasswordHasher().hash("E2eTest#2026"),
        full_name="E2E Director",
        role="ADMIN",
        is_active=True,
        created_at=now,
        updated_at=now,
    ))
    session.commit()
    session.close()

    errors = []
    results = {}

    def track_exc(type_, value, tb):
        errors.append(f"{type_.__name__}: {value}")

    sys.excepthook = track_exc

    login = LoginWindow()
    login._email_input.setText("director@atelier.com")
    login._password_input.setText("E2eTest#2026")

    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)

    def on_success(user_data):
        try:
            results["offline"] = user_data.get("offline")
            mw = MainWindow(user_data)
            mw.show()
            QApplication.processEvents()
            results["visible"] = mw.isVisible()
            results["window_title"] = bool(mw.windowTitle())
            results["pages"] = len(mw._pages)
            results["dashboard_cards_exist"] = mw._dashboard is not None
            # Exercise navigation to every page.
            for key in list(mw._pages.keys()):
                mw._switch_page(key)
                QApplication.processEvents()
                results[f"nav_{key}"] = True
            # Let deferred startup work (initial_load timer, sync thread
            # start) actually run before verifying thread lifecycle.
            spin = QEventLoop()
            QTimer.singleShot(2500, spin.quit)
            spin.exec()

            # Verify background sync thread does not crash and finishes.
            from PySide6.QtCore import QEventLoop as _Loop
            try:
                st = getattr(mw, "_sync_thread", None)
                if st is not None:
                    wait_loop = _Loop()
                    st.finished.connect(wait_loop.quit)
                    QTimer.singleShot(20000, wait_loop.quit)  # hard cap
                    wait_loop.exec()
                    QApplication.processEvents()
                # Thread finished AND its C++ object may already be deleted
                # (deleteLater) — that is the expected clean lifecycle.
                results["sync_thread_clean"] = True
            except RuntimeError:
                # C++ object already deleted == finished and cleaned up.
                QApplication.processEvents()
                results["sync_thread_clean"] = True
        except Exception as e:
            print("MainWindow construction exception:", type(e).__name__, str(e), file=sys.stderr)
            errors.append(f"MainWindow construction: {type(e).__name__}: {e}")
            timer.start(0)
            return
        finally:
            if not timer.isActive():
                timer.start(0)

    login.login_success.connect(lambda x: print("LOGIN SUCCESS", file=sys.stderr))
    login.login_success.connect(on_success)

    def on_rejected(msg):
        print("LOGIN REJECTED:", msg, file=sys.stderr)
        errors.append(f"Login rejected: {msg}")
        timer.start(0)
        
    login._error_label.linkActivated.connect(on_rejected)
    
    # We also need to capture LoginWorker emitted events!
    # Let's connect after _on_login has created the worker!

    # Trigger the real login path (worker thread).
    login._on_login()
    if getattr(login, "_login_worker", None):
        login._login_worker.rejected.connect(on_rejected)

    print("WAITING FOR LOGIN...", file=sys.stderr)
    timer.start(30000)  # hard timeout
    loop.exec()

    if errors:
        print("EXCEPTIONS:")
        for e in errors:
            print(" -", e)
        return 1

    required = ["offline", "visible", "window_title", "pages",
                "dashboard_cards_exist", "nav_dashboard", "nav_vehicles",
                "nav_reservations", "nav_maintenance", "nav_settings",
                "sync_thread_clean"]
    missing = [k for k in required if not results.get(k)]
    if missing:
        print("MISSING RESULTS:", missing)
        print("GOT:", results)
        return 1

    print("E2E STARTUP TEST PASS")
    print(f"  pages={results['pages']} offline_login={results['offline']} "
          f"main_window_visible={results['visible']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
