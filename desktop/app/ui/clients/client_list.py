"""
Clients module — professional client list with live server data.

ONLINE : data comes from the authoritative API (FastAPI/PostgreSQL).
OFFLINE: falls back to the local SQLite cache and is explicitly labeled
         "Données locales (hors ligne)" so cached data is never presented
         as confirmed live server state.

Selecting a client opens the Client Details view (canonical rental report).
"""
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QMessageBox,
)

from app.i18n import t, is_rtl
from app.database import get_local_session
from app.models.client import LocalClient
from app.models.reservation import LocalReservation

logger = logging.getLogger(__name__)


class ClientsWidget(QWidget):
    """Clients list page with search and live-data indicator."""

    client_selected = Signal(str)  # client_id

    def __init__(self, api_client=None, parent=None):
        super().__init__(parent)
        self._api = api_client
        self._clients = []
        self._setup_ui()

    def _setup_ui(self):
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        header = QHBoxLayout()
        self._title_lbl = QLabel(t("sidebar.clients"))
        self._title_lbl.setFont(QFont("Libre Caslon Text", 20, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet("color: #1E4D38;")
        header.addWidget(self._title_lbl)
        header.addStretch()
        self._mode_lbl = QLabel("")
        self._mode_lbl.setFont(QFont("Hanken Grotesk", 9))
        self._mode_lbl.setStyleSheet("color: #6B7264; background: #F2F5F0; border-radius: 6px; padding: 4px 10px;")
        header.addWidget(self._mode_lbl)
        layout.addLayout(header)

        search_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(t("clients.search_ph"))
        self._search.setFixedHeight(38)
        self._search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search, 1)
        self._refresh_btn = QPushButton(t("topbar.refresh"))
        self._refresh_btn.setFixedHeight(38)
        self._refresh_btn.clicked.connect(self.refresh_data)
        search_row.addWidget(self._refresh_btn)
        layout.addLayout(search_row)

        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._headers = [
            t("clients.total_rentals") + " / " + t("reservations.col_client"),
            t("login.phone") if False else "Téléphone",
            "Email", "CIN", t("vehicles.status"), "",
        ]
        # Keep simple canonical headers:
        self._headers = ["Client", "Téléphone", "Email", "CIN", t("vehicles.status"), ""]
        self._table.setHorizontalHeaderLabels(self._headers)
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            header_view.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(5, 110)
        self._table.verticalHeader().setDefaultSectionSize(42)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self._table, 1)

    # ── Data loading ──────────────────────────────────────────────

    def refresh_data(self):
        """Refresh clients from the authoritative API; fall back to SQLite."""
        loaded_live = False
        if self._api is not None:
            try:
                resp = self._api.get_clients(page=1, page_size=100)
                if isinstance(resp, dict) and "clients" in resp:
                    self._clients = resp["clients"]
                    loaded_live = True
            except Exception as e:
                logger.info("Clients API fetch failed (offline?): %s", e)
        if not loaded_live:
            self._clients = self._load_from_local_cache()
        self._set_mode_label(live=loaded_live)
        self._render()

    @staticmethod
    def _load_from_local_cache() -> list:
        session = get_local_session()
        try:
            out = []
            for c in session.query(LocalClient).order_by(LocalClient.last_name).all():
                out.append({
                    "id": c.id,
                    "first_name": c.first_name,
                    "last_name": c.last_name,
                    "phone": c.phone or "",
                    "email": c.email or "",
                    "cin_number": getattr(c, "cin_number", "") or "",
                    "status": getattr(c, "status", "ACTIVE"),
                    "_offline": True,
                })
            return out
        finally:
            session.close()

    def _set_mode_label(self, live: bool):
        if live:
            self._mode_lbl.setText(t("clients.live_data"))
            self._mode_lbl.setStyleSheet(
                "color: #1E4D38; background: #E6F4EA; border-radius: 6px; padding: 4px 10px;")
        else:
            self._mode_lbl.setText(t("clients.offline_data"))
            self._mode_lbl.setStyleSheet(
                "color: #975A16; background: #FEF3C7; border-radius: 6px; padding: 4px 10px;")

    # ── Rendering ─────────────────────────────────────────────────

    def _render(self):
        rows = self._filter_rows(self._clients, self._search.text().strip())
        self._table.setRowCount(len(rows))
        for i, c in enumerate(rows):
            name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip() or "—"
            values = [
                name,
                c.get("phone") or "—",
                c.get("email") or "—",
                c.get("cin_number") or "—",
                t(f"status.{c['status']}") if c.get("status") else "—",
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                item.setData(Qt.ItemDataRole.UserRole, c.get("id"))
                self._table.setItem(i, col, item)
            btn = QPushButton(t("clients.open_details"))
            btn.setProperty("class", "primary")
            cid = c.get("id")
            btn.clicked.connect(lambda _, cid_=cid: self.client_selected.emit(cid_))
            self._table.setCellWidget(i, 5, btn)

    def _filter_rows(self, rows, text):
        if not text:
            return rows
        needle = text.lower()
        out = []
        for c in rows:
            hay = " ".join(str(c.get(k, "") or "") for k in
                           ("first_name", "last_name", "phone", "email", "cin_number"))
            if needle in hay.lower():
                out.append(c)
        return out

    def _apply_filter(self):
        self._render()

    def _on_row_double_clicked(self, index):
        item = self._table.item(index.row(), 0)
        if item:
            cid = item.data(Qt.ItemDataRole.UserRole)
            if cid:
                self.client_selected.emit(cid)

    def retranslate_ui(self):
        self._title_lbl.setText(t("sidebar.clients"))
        self._search.setPlaceholderText(t("clients.search_ph"))
        self._refresh_btn.setText(t("topbar.refresh"))
        self._headers = ["Client", "Téléphone", "Email", "CIN", t("vehicles.status"), ""]
        self._table.setHorizontalHeaderLabels(self._headers)
        self.refresh_data()
