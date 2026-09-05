"""
Sidebar navigation widget matching Stitch ATELIER BERLIN LOCATION CAR Design.
Provides seamless LTR/RTL support and dynamic live re-translation.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QFrame, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from app.i18n import t, is_rtl


class Sidebar(QWidget):
    """Navigation rail.

    RESPONSIVE CONTRACT: the rail keeps a comfortable 260px on roomy windows
    but is allowed to narrow to ``MIN_WIDTH`` so the main content is never
    squeezed off-screen, and its contents live in a vertical QScrollArea so a
    short window (720px tall or less, once the OS panel is subtracted) scrolls
    the navigation instead of clipping the bottom entries. Previously
    ``setFixedWidth(260)`` plus a tall un-scrollable column meant a small
    screen simply lost the lower buttons.
    """

    MIN_WIDTH = 200
    PREFERRED_WIDTH = 260
    page_changed = Signal(str)
    language_changed = Signal(str)
    theme_changed = Signal(str)
    logout_requested = Signal()

    PAGE_KEYS = [
        ("dashboard", "🏠", "sidebar.dashboard"),
        ("vehicles", "🚗", "sidebar.vehicles"),
        ("clients", "👥", "sidebar.clients"),
        ("reservations", "📅", "sidebar.reservations"),
        ("maintenance", "🔧", "sidebar.maintenance"),
        ("settings", "⚙️", "sidebar.settings"),
    ]

    def __init__(self, user_role="EMPLOYEE", parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setMaximumWidth(self.PREFERRED_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._user_role = user_role
        self._current_page = "dashboard"
        self._buttons = {}
        self._setup_ui()

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        # The rail scrolls vertically so a short window never clips the lower
        # navigation entries; horizontal scrolling stays off because every
        # child is allowed to shrink.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        outer.addWidget(self._scroll)

        inner = QWidget()
        inner.setObjectName("sidebarInner")
        inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        inner.setStyleSheet("background: transparent;")
        self._scroll.setWidget(inner)

        layout = QVBoxLayout(inner)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(6)

        # Official Transparent Logo (max 200px, KeepAspectRatio, SmoothTransformation, centered)
        self._logo_lbl = QLabel()
        self._logo_lbl.setStyleSheet("background: transparent; border: none;")
        self._logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        from pathlib import Path
        from PySide6.QtGui import QPixmap
        logo_path = Path(__file__).resolve().parent.parent.parent / "assets" / "images" / "logo_transparent_officiel.png"
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                # 150px, not 200: the rail can narrow to MIN_WIDTH and a
                # 200px pixmap would then be wider than the content area.
                scaled = pixmap.scaled(
                    150,
                    150,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._logo_lbl.setPixmap(scaled)
        layout.addWidget(self._logo_lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(10)

        # Brand header: ATELIER BERLIN LOCATION CAR (Libre Caslon Text)
        self._name_lbl = QLabel("ATELIER BERLIN LOCATION CAR")
        self._name_lbl.setFont(QFont("Libre Caslon Text", 12, QFont.Weight.Bold))
        self._name_lbl.setStyleSheet("color: #1E4D38; background: transparent; border: none; padding-left: 10px; padding-right: 10px;")
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_lbl.setWordWrap(True)
        layout.addWidget(self._name_lbl)
        layout.addSpacing(16)

        # Navigation buttons
        for key, icon, label_key in self.PAGE_KEYS:
            btn = QPushButton(f"  {icon}  {t(label_key)}")
            btn.setProperty("class", "nav_btn")
            btn.setFixedHeight(46)
            btn.setFont(QFont("Hanken Grotesk", 13, QFont.Weight.DemiBold))
            btn.clicked.connect(lambda c, k=key: self._on_click(k))
            self._buttons[key] = btn
            layout.addWidget(btn)

        layout.addStretch()

        # Bottom section: Déconnexion
        self._btn_logout = QPushButton(f"  ↪  {t('sidebar.logout')}")
        self._btn_logout.setProperty("class", "nav_btn")
        self._btn_logout.setFixedHeight(42)
        self._btn_logout.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.DemiBold))
        self._btn_logout.clicked.connect(self.logout_requested.emit)
        layout.addWidget(self._btn_logout)

        self._set_active("dashboard")

    def retranslate_ui(self):
        """Update all text on the sidebar when language changes."""
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)
        for key, icon, label_key in self.PAGE_KEYS:
            if key in self._buttons:
                self._buttons[key].setText(f"  {icon}  {t(label_key)}")
        self._btn_logout.setText(f"  ↪  {t('sidebar.logout')}")

    def update_sync_status(self, status: str, details: str = ""):
        """Maintains interface compatibility for background sync events."""
        pass

    def _on_click(self, key):
        self._set_active(key)
        self.page_changed.emit(key)

    def _set_active(self, key):
        self._current_page = key
        for k, btn in self._buttons.items():
            if k == key:
                btn.setProperty("active", "true")
            else:
                btn.setProperty("active", "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()
