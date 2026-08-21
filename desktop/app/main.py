"""
Desktop application entry point.
Initializes the local database, shows login, then main window.
"""
import sys
import os
import logging
from pathlib import Path

# Safe platform fallback: try Wayland first, then fallback to XCB (X11)
if "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "wayland;xcb"

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
    # Initialize local database
    init_local_db()

    # Set default language
    set_language(DEFAULT_LANGUAGE)

    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("ATELIER BERLIN LOCATION CAR")

    from app.ui.theme import get_app_stylesheet
    from app.config import get_saved_theme
    app.setStyleSheet(get_app_stylesheet(get_saved_theme()))

    # Show login window
    login = LoginWindow()

    main_window = None

    def on_login_success(user_data: dict):
        nonlocal main_window
        logger.info("Login successful for user: %s", user_data.get("full_name", user_data.get("email", "")))
        login.close()
        main_window = MainWindow(user_data)
        main_window.show()

    login.login_success.connect(on_login_success)
    login.show()

    from app.ui.vehicles.vehicle_hover_preview import cleanup_hover_preview
    exit_code = app.exec()
    cleanup_hover_preview()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
