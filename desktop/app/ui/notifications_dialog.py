"""
Notifications Dialog for Desktop Software — displays real-time alerts for
document expirations, approaching maintenance dates, and vehicle issues.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QPushButton, QLabel, QWidget, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from app.services.api_client import ApiClient


class NotificationItemWidget(QFrame):
    """A card for a single notification."""
    marked_read = Signal(str)

    def __init__(self, notif: dict, parent=None):
        super().__init__(parent)
        self._notif = notif
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel(self._notif.get("title", "Alerte"))
        title.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.Bold))
        header.addWidget(title)
        header.addStretch()

        severity = self._notif.get("severity", "warning")
        badge = QLabel(self._severity_label(severity))
        badge.setFont(QFont("Hanken Grotesk", 9, QFont.Weight.Bold))
        header.addWidget(badge)
        layout.addLayout(header)

        msg = QLabel(self._notif.get("message", ""))
        msg.setFont(QFont("Hanken Grotesk", 10))
        msg.setWordWrap(True)
        layout.addWidget(msg)

        footer = QHBoxLayout()
        due = self._notif.get("due_date") or ""
        if due:
            date_lbl = QLabel(f"{t('notifications.due_date')}{due}")
            date_lbl.setFont(QFont("Hanken Grotesk", 9))
            footer.addWidget(date_lbl)

        footer.addStretch()

        if not self._notif.get("is_read", False):
            read_btn = QPushButton("Marquer comme lu")
            read_btn.setFont(QFont("Hanken Grotesk", 9))
            read_btn.clicked.connect(lambda: self.marked_read.emit(self._notif.get("id")))
            footer.addWidget(read_btn)

        layout.addLayout(footer)

    def _severity_label(self, severity: str) -> str:
        mapping = {
            "expired": "EXPIRÉ",
            "urgent": "URGENT",
            "warning": "ATTENTION",
            "maintenance_required": "MAINTENANCE REQUISE",
            "info": "INFO",
        }
        return mapping.get(severity, severity.upper())

    def _severity_style(self, severity: str) -> str:
        if severity in ("expired", "urgent"):
            return "background-color: #F3D0D0; color: #8A4545; border-radius: 4px; padding: 2px 8px;"
        elif severity == "warning":
            return "background-color: #F5EBC5; color: #806B2A; border-radius: 4px; padding: 2px 8px;"
        elif severity == "maintenance_required":
            return "background-color: #E7DDF0; color: #625074; border-radius: 4px; padding: 2px 8px;"
        else:
            return "background-color: #DCE7F3; color: #405A78; border-radius: 4px; padding: 2px 8px;"


class NotificationsDialog(QDialog):
    """Dialog displaying all vehicle notifications and document monitoring."""
    def __init__(self, api_client: ApiClient, parent=None):
        super().__init__(parent)
        self._api = api_client
        self.setWindowTitle(t("notifications.title"))
        self.setMinimumSize(600, 500)
        self._setup_ui()
        self.load_notifications()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("🔔 Centre de Notifications")
        title.setFont(QFont("Libre Caslon Text", 16, QFont.Weight.Bold))
        header.addWidget(title)
        header.addStretch()

        mark_all_btn = QPushButton("Tout marquer comme lu")
        mark_all_btn.clicked.connect(self._mark_all_read)
        header.addWidget(mark_all_btn)

        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedSize(32, 32)
        refresh_btn.clicked.connect(self.load_notifications)
        header.addWidget(refresh_btn)

        layout.addLayout(header)

        # Scroll area for items
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._container = QWidget()
        self._items_layout = QVBoxLayout(self._container)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(8)
        self._items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self._container)
        layout.addWidget(scroll)

        # Footer
        footer = QHBoxLayout()
        self._status_lbl = QLabel("")
        footer.addWidget(self._status_lbl)
        footer.addStretch()

        close_btn = QPushButton("Fermer")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    def load_notifications(self):
        """Fetch notifications from backend."""
        while self._items_layout.count():
            item = self._items_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        res = self._api.get_notifications(page=1)
        if not res or not res.get("items"):
            empty_lbl = QLabel(t("notifications.empty"))
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._items_layout.addWidget(empty_lbl)
            self._status_lbl.setText("0 notification")
            return

        items = res["items"]
        unread = res.get("unread_count", 0)
        self._status_lbl.setText(f"{len(items)} notification(s) ({unread} non lue(s))")

        for notif in items:
            w = NotificationItemWidget(notif)
            w.marked_read.connect(self._mark_single_read)
            self._items_layout.addWidget(w)

    def _mark_single_read(self, notif_id: str):
        self._api.mark_notification_read(notif_id)
        self.load_notifications()

    def _mark_all_read(self):
        self._api.mark_all_notifications_read()
        self.load_notifications()
