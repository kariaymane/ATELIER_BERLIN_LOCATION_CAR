"""
Desktop application entry point.
Initializes the local database, shows login, then main window.
"""
import sys
import os
import logging

# Platform plugin initialization for PyInstaller
from pathlib import Path

if sys.platform == "linux" and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "wayland;xcb"

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    INTERNAL_DIR = BASE_DIR / "_internal"
else:
    BASE_DIR = Path(__file__).resolve().parent
    INTERNAL_DIR = BASE_DIR

PYSIDE_DIR = INTERNAL_DIR / "PySide6"

if PYSIDE_DIR.exists():
    os.environ["PATH"] = str(PYSIDE_DIR) + os.pathsep + os.environ.get("PATH", "")
    
    # Also set plugin path
    plugin_path = PYSIDE_DIR / "plugins"
    if plugin_path.exists():
        os.environ["QT_PLUGIN_PATH"] = str(plugin_path)



from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from app.config import DEFAULT_LANGUAGE, DEFAULT_THEME
from app.database import init_local_db
from app.i18n import set_language
from app.ui.login_window import LoginWindow
from app.ui.main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Application entry point."""
    # Initialize local database.
    # Data is preserved across runs; the file is only deleted when
    # CAR_RENTAL_DB_RESET=1 (used by the test suite) — see app.database.init_local_db.
    init_local_db()

    # Set default language
    set_language(DEFAULT_LANGUAGE)

    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("ATELIER BERLIN LOCATION CAR")

    # Application branding — approved Lily logo as window/taskbar icon
    from PySide6.QtGui import QIcon
    _icon_path = Path(__file__).resolve().parent / "assets" / "images" / "logo_transparent_officiel.png"
    if not _icon_path.exists() and getattr(sys, "frozen", False):
        _icon_path = INTERNAL_DIR / "app" / "assets" / "images" / "logo_transparent_officiel.png"
    if _icon_path.exists():
        app.setWindowIcon(QIcon(str(_icon_path)))

    from app.ui.theme import get_app_stylesheet
    from app.config import get_saved_theme
    app.setStyleSheet(get_app_stylesheet(get_saved_theme()))

    # Show login window
    login = LoginWindow()

    main_window = None

    def on_login_success(user_data: dict):
        nonlocal main_window
        logger.info("Login successful for user: %s", user_data.get("full_name", user_data.get("email", "")))
        try:
            # Construct BEFORE closing login so that a construction failure
            # never leaves the user with zero visible windows.
            main_window = MainWindow(user_data)
        except Exception:
            logger.exception("Failed to build main window after login")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                None,
                "ATELIER BERLIN LOCATION CAR",
                "Une erreur technique est survenue au démarrage de l'application.\n"
                "Consultez les journaux pour plus de détails.",
            )
            return
        main_window.show()
        login.close()

    login.login_success.connect(on_login_success)
    login.show()

    from app.ui.vehicles.vehicle_hover_preview import cleanup_hover_preview
    exit_code = app.exec()
    cleanup_hover_preview()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
