"""
Real-time Desktop Notification Toast / Alert banner widget.
Displays live notifications when events occur from Mobile or API.
"""
import logging
from datetime import datetime
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QGraphicsOpacityEffect, QWidget
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, Signal
from PySide6.QtGui import QFont, QColor

logger = logging.getLogger(__name__)


class NotificationToast(QFrame):
    """Floating notification toast banner with auto-dismiss and animations."""

    dismissed = Signal()

    def __init__(
        self,
        title: str,
        message: str,
        origin: str = "Mobile",
        event_type: str = "INFO",
        parent: QWidget = None,
        duration_ms: int = 7000
    ):
        super().__init__(parent)
        self.setObjectName("NotificationToast")
        self.setWindowFlags(Qt.SubWindow | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        self._title = title
        self._message = message
        self._origin = origin
        self._event_type = event_type
        self._duration_ms = duration_ms

        self._setup_ui()
        self._setup_animation()

    def _setup_ui(self):
        # Determine accent colors & icons
        if "MAINTENANCE_ENTERED" in self._event_type or "MAINTENANCE" in self._event_type:
            icon_char = "🔧"
            badge_bg = "#FEE2E2"
            badge_fg = "#991B1B"
            border_color = "#FCA5A5"
        elif "RENTED" in self._event_type or "RESERVATION" in self._event_type:
            icon_char = "🚗"
            badge_bg = "#FEF3C7"
            badge_fg = "#92400E"
            border_color = "#FCD34D"
        elif "EXITED" in self._event_type or "RETURNED" in self._event_type or "AVAILABLE" in self._event_type:
            icon_char = "✅"
            badge_bg = "#DCFCE7"
            badge_fg = "#166534"
            border_color = "#86EFAC"
        else:
            icon_char = "📋"
            badge_bg = "#E0E7FF"
            badge_fg = "#3730A3"
            border_color = "#A5B4FC"


        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        # Icon Circle
        icon_label = QLabel(icon_char)
        icon_label.setFont(QFont("Hanken Grotesk", 18))
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setFixedSize(40, 40)
        layout.addWidget(icon_label)

        # Content Column
        content_layout = QVBoxLayout()
        content_layout.setSpacing(4)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # Header row: Title + Origin Badge + Time
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        title_lbl = QLabel(self._title)
        title_lbl.setFont(QFont("Hanken Grotesk", 11, QFont.Bold))
        header_row.addWidget(title_lbl)

        origin_badge = QLabel(f"📱 {self._origin}" if self._origin.lower() == "mobile" else f"🖥️ {self._origin}")
        origin_badge.setFont(QFont("Hanken Grotesk", 8, QFont.Bold))
        header_row.addWidget(origin_badge)

        now_str = datetime.now().strftime("%H:%M:%S")
        time_lbl = QLabel(now_str)
        time_lbl.setFont(QFont("Hanken Grotesk", 9))
        header_row.addWidget(time_lbl)
        header_row.addStretch()

        content_layout.addLayout(header_row)

        # Message
        msg_lbl = QLabel(self._message)
        msg_lbl.setFont(QFont("Hanken Grotesk", 10))
        msg_lbl.setWordWrap(True)
        content_layout.addWidget(msg_lbl)

        layout.addLayout(content_layout, 1)

        # Close button
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self._dismiss)
        layout.addWidget(close_btn)

    def _setup_animation(self):
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.0)

        # Fade in animation
        self._fade_in = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_in.setDuration(250)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_in.start()

        # Auto dismiss timer
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._dismiss)
        self._dismiss_timer.start(self._duration_ms)

    def _dismiss(self):
        self._fade_out = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_out.setDuration(300)
        self._fade_out.setStartValue(self._opacity_effect.opacity())
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._fade_out.finished.connect(self._on_fade_out_finished)
        self._fade_out.start()

    def _on_fade_out_finished(self):
        self.hide()
        self.dismissed.emit()
        self.deleteLater()
