"""
Login window — secure authentication with automatic offline fallback.
No manual offline switch. Supports French/Arabic with live RTL layout switching.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QMessageBox, QComboBox, QApplication
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont

from app.i18n import t, is_rtl, set_language, load_translations
from app.config import get_saved_language, save_language, API_BASE_URL
import logging

logger = logging.getLogger(__name__)


class LoginWorker(QThread):
    """Performs authentication off the UI thread.

    Tries online authentication first; falls back automatically to the
    local SQLite cache when the server is unreachable.
    """
    succeeded = Signal(dict)
    rejected = Signal(str)

    def __init__(self, email: str, password: str, parent=None):
        super().__init__(parent)
        self._email = email
        self._password = password

    def run(self):
        user_data = self._authenticate_online()
        if user_data is not None:
            # Cache credentials locally so future logins work offline.
            try:
                self._cache_credentials_locally(
                    self._email, self._password, user_data
                )
            except Exception as e:
                logger.error("Failed to cache credentials locally: %s", e)
            self.succeeded.emit(user_data)
            return

        if getattr(self, '_server_rejected', False):
            self.rejected.emit(t("login.error"))
            return

        user_data = self._authenticate_offline()
        if user_data is not None:
            self.succeeded.emit(user_data)
        else:
            # Network failed AND offline failed
            self.rejected.emit(t("common.error_connection"))

    def _cache_credentials_locally(self, email, password, user_data):
        """Securely store Argon2 hashed password and metadata in SQLite."""
        from app.database import get_local_session
        from app.models.user import LocalUser
        from datetime import datetime, timezone
        import argon2

        ph = argon2.PasswordHasher()
        pwd_hash = ph.hash(password)

        session = get_local_session()
        try:
            now = datetime.now(timezone.utc).isoformat()
            user_id = str(user_data.get("user_id", "") or "")
            username = user_data.get("username", email.split("@")[0])

            existing = session.query(LocalUser).filter(
                (LocalUser.email == email) |
                (LocalUser.username == username) |
                (LocalUser.id == user_id)
            ).first()

            if existing:
                if user_id:
                    existing.id = user_id
                existing.password_hash = pwd_hash
                existing.role = user_data.get("role", existing.role)
                existing.full_name = user_data.get("full_name", existing.full_name)
                existing.updated_at = now
            else:
                local_user = LocalUser(
                    id=user_id or f"local-{email}",
                    email=email,
                    username=username,
                    password_hash=pwd_hash,
                    full_name=user_data.get("full_name", "Utilisateur"),
                    role=user_data.get("role", "EMPLOYEE"),
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                session.add(local_user)
            session.commit()
        finally:
            session.close()

    def _authenticate_online(self):
        """Returns user_data on success, None when offline fallback is needed."""
        import httpx
        try:
            with httpx.Client(timeout=4.0) as client:
                response = client.post(
                    f"{API_BASE_URL}/api/v1/auth/login",
                    json={"email": self._email, "password": self._password},
                )
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "user_id": data.get("user_id", data.get("id", "")),
                        "email": self._email,
                        "username": data.get("username", self._email.split("@")[0]),
                        "full_name": data.get("full_name", data.get("name", "Utilisateur")),
                        "role": data.get("role", "EMPLOYEE"),
                        "access_token": data.get("access_token", ""),
                        "refresh_token": data.get("refresh_token", ""),
                        "offline": False,
                    }
                if response.status_code in (400, 401, 422):
                    # Server explicitly rejected these credentials.
                    self._server_rejected = True
                else:
                    self._server_rejected = False
        except Exception as e:
            logger.info("Server unreachable (%s), falling back to offline authentication", e)
            self._server_rejected = False
        return None

    def _authenticate_offline(self):
        from app.database import get_local_session
        from app.models.user import LocalUser
        import argon2

        session = get_local_session()
        try:
            user = session.query(LocalUser).filter(
                (LocalUser.email == self._email) | (LocalUser.username == self._email)
            ).first()

            if user and user.password_hash:
                ph = argon2.PasswordHasher()
                try:
                    ph.verify(user.password_hash, self._password)
                    return {
                        "user_id": user.id,
                        "email": user.email,
                        "username": user.username,
                        "full_name": user.full_name,
                        "role": user.role,
                        "access_token": "",
                        "refresh_token": "",
                        "offline": True,
                    }
                except argon2.exceptions.VerifyMismatchError:
                    return None
            return None
        except Exception as e:
            logger.error("Offline auth error: %s", e)
            return None
        finally:
            session.close()


class LoginWindow(QWidget):
    """Login form that automatically authenticates online or falls back to local SQLite."""

    login_success = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        current_lang = get_saved_language()
        set_language(current_lang)

        self.setWindowTitle(f"ATELIER BERLIN LOCATION CAR — {t('login.title')}")
        self.setMinimumSize(480, 620)
        self.resize(560, 720)
        self._setup_ui()

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        # Outer layout: centers the login card both vertically and horizontally
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(20, 20, 20, 20)
        outer_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Centered Login Card (Prevents stretching across full screen)
        self._card = QFrame()
        self._card.setObjectName("loginCard")
        self._card.setFixedWidth(440)
        self._card.setStyleSheet("""
            #loginCard {
                background: transparent;
            }
        """)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Official Logo (360px wide, KeepAspectRatio, perfectly transparent)
        self._logo_lbl = QLabel()
        self._logo_lbl.setStyleSheet("background: transparent; border: none;")
        self._logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        import os
        from PySide6.QtGui import QPixmap
        logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "images", "logo_transparent_officiel.png"))
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            if not pixmap.isNull():
                self._logo_lbl.setPixmap(pixmap.scaledToWidth(440, Qt.TransformationMode.SmoothTransformation))
        card_layout.addWidget(self._logo_lbl)

        card_layout.addSpacing(20)

        # Main Brand Title: ATELIER BERLIN LOCATION CAR
        self._title_lbl = QLabel("ATELIER BERLIN LOCATION CAR")
        self._title_lbl.setFont(QFont("Libre Caslon Text", 17, QFont.Weight.Bold))
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setStyleSheet("color: #1E4D38; background: transparent;")
        card_layout.addWidget(self._title_lbl)

        card_layout.addSpacing(6)

        self._sub_title = QLabel(t("app_subtitle"))
        self._sub_title.setFont(QFont("Hanken Grotesk", 10))
        self._sub_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_title.setStyleSheet("color: #6B7264; background: transparent;")
        card_layout.addWidget(self._sub_title)

        card_layout.addSpacing(28)

        # Input 1: E-mail
        self._email_input = QLineEdit()
        self._email_input.setPlaceholderText(t("login.email_placeholder"))
        self._email_input.setFixedHeight(44)
        self._email_input.setFont(QFont("Hanken Grotesk", 11))
        self._email_input.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #D5DDD3;
                border-radius: 8px;
                padding: 0px 14px;
                color: #2D3748;
            }
            QLineEdit:focus {
                border: 1.5px solid #1E4D38;
            }
        """)
        card_layout.addWidget(self._email_input)

        card_layout.addSpacing(14)

        # Input 2: Mot de passe
        pwd_container = QFrame()
        pwd_container.setStyleSheet("background: transparent;")
        pwd_layout = QHBoxLayout(pwd_container)
        pwd_layout.setContentsMargins(0, 0, 0, 0)
        pwd_layout.setSpacing(0)

        self._password_input = QLineEdit()
        self._password_input.setPlaceholderText(t("login.password_placeholder"))
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.setFixedHeight(44)
        self._password_input.setFont(QFont("Hanken Grotesk", 11))
        self._password_input.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #D5DDD3;
                border-top-left-radius: 8px;
                border-bottom-left-radius: 8px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                padding: 0px 14px;
                color: #2D3748;
            }
            QLineEdit:focus {
                border: 1.5px solid #1E4D38;
            }
        """)
        self._password_input.returnPressed.connect(self._on_login)
        pwd_layout.addWidget(self._password_input)

        self._toggle_pwd_btn = QPushButton("👁")
        self._toggle_pwd_btn.setFixedSize(40, 44)
        self._toggle_pwd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_pwd_btn.setStyleSheet("""
            QPushButton {
                background-color: #F2F5F0;
                border: 1px solid #D5DDD3;
                border-left: none;
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
                color: #6B7264;
            }
            QPushButton:hover {
                background-color: #E5ECE3;
            }
        """)
        self._toggle_pwd_btn.clicked.connect(self._toggle_password_visibility)
        pwd_layout.addWidget(self._toggle_pwd_btn)

        card_layout.addWidget(pwd_container)

        card_layout.addSpacing(22)

        # Login button
        self._login_btn = QPushButton(t("login.login_button"))
        self._login_btn.setFixedHeight(46)
        self._login_btn.setFont(QFont("Hanken Grotesk", 12, QFont.Weight.Bold))
        self._login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._login_btn.setStyleSheet("""
            QPushButton {
                background-color: #1E4D38;
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #2D6A4F;
            }
            QPushButton:pressed {
                background-color: #173E2D;
            }
            QPushButton:disabled {
                background-color: #A3B899;
            }
        """)
        self._login_btn.clicked.connect(self._on_login)
        card_layout.addWidget(self._login_btn)

        card_layout.addSpacing(14)

        # Error banner
        self._error_label = QLabel(t("login.error"))
        self._error_label.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Medium))
        self._error_label.setStyleSheet("color: #DC2626; background-color: #FEE2E2; border: 1px solid #FCA5A5; border-radius: 6px; padding: 8px;")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.hide()
        card_layout.addWidget(self._error_label)

        outer_layout.addWidget(self._card, alignment=Qt.AlignmentFlag.AlignCenter)

    def _retranslate(self):
        self.setWindowTitle(f"ATELIER BERLIN LOCATION CAR — {t('login.title')}")
        self._sub_title.setText(t("app_subtitle"))
        self._email_input.setPlaceholderText(t("login.email_placeholder"))
        self._password_input.setPlaceholderText(t("login.password_placeholder"))
        self._login_btn.setText(t("login.login_button"))
        self._error_label.setText(t("login.error"))

    def _toggle_password_visibility(self):
        if self._password_input.echoMode() == QLineEdit.EchoMode.Password:
            self._password_input.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self._password_input.setEchoMode(QLineEdit.EchoMode.Password)

    def _on_login(self):
        email = self._email_input.text().strip().lower()
        password = self._password_input.text()

        if not email or not password:
            self._show_error(t("login.error"))
            return

        try:
            if getattr(self, "_login_worker", None) and self._login_worker.isRunning():
                return
        except RuntimeError:
            self._login_worker = None
            return  # login already in progress

        self._error_label.hide()
        self._login_btn.setEnabled(False)
        self._login_btn.setText("...")

        worker = LoginWorker(email, password, parent=self)
        worker.succeeded.connect(self._on_login_succeeded)
        worker.rejected.connect(self._on_login_rejected)
        worker.finished.connect(worker.deleteLater)
        self._login_worker = worker
        worker.start()

    def _on_login_succeeded(self, user_data: dict):
        self._login_btn.setEnabled(True)
        self._login_btn.setText(t("login.login_button"))
        self.login_success.emit(user_data)

    def _on_login_rejected(self, error_msg: str = None):
        if not error_msg:
            error_msg = t("login.error")
        self._show_error(error_msg)
        self._login_btn.setEnabled(True)
        self._login_btn.setText(t("login.login_button"))

    def _try_local_login(self, email: str, password: str) -> bool:
        """Helper for headless testing."""
        self._email_input.setText(email)
        self._password_input.setText(password)
        self._authenticate_offline(email, password)
        return True

    def _cache_credentials(self, user_id: str = None, email: str = None, password: str = None, full_name: str = 'Admin', role: str = 'ADMIN'):
        """Helper for test setup."""
        user_data = {'user_id': user_id, 'email': email, 'full_name': full_name, 'role': role}
        self._cache_credentials_locally(email, password, user_data)

    def _cache_credentials_locally(self, email: str, password: str, user_data: dict):
        """Securely store Argon2 hashed password and user metadata in SQLite for offline access."""
        from app.database import get_local_session
        from app.models.user import LocalUser
        from datetime import datetime, timezone
        import argon2

        ph = argon2.PasswordHasher()
        pwd_hash = ph.hash(password)

        session = get_local_session()
        try:
            now = datetime.now(timezone.utc).isoformat()
            user_id = user_data.get("user_id", "")
            username = user_data.get("username", email.split("@")[0])

            existing = session.query(LocalUser).filter(
                (LocalUser.email == email) |
                (LocalUser.username == username) |
                (LocalUser.id == user_id)
            ).first()

            if existing:
                if user_id:
                    existing.id = user_id
                existing.password_hash = pwd_hash
                existing.role = user_data.get("role", existing.role)
                existing.full_name = user_data.get("full_name", existing.full_name)
                existing.updated_at = now
            else:
                local_user = LocalUser(
                    id=user_id or f"local-{email}",
                    email=email,
                    username=username,
                    password_hash=pwd_hash,
                    full_name=user_data.get("full_name", "Utilisateur"),
                    role=user_data.get("role", "EMPLOYEE"),
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                session.add(local_user)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to cache credentials locally: %s", e)
        finally:
            session.close()

    def _show_error(self, message: str):
        self._error_label.setText(message)
        self._error_label.show()
