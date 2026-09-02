"""
Clients module — professional client list with live server data.

ONLINE : data comes from the authoritative API (FastAPI/PostgreSQL).
OFFLINE: falls back to the local SQLite cache and is explicitly labeled
         "Données locales (hors ligne)" so cached data is never presented
         as confirmed live server state.

Selecting a client opens the Client Details view (canonical rental report).
"""
import logging

from PySide6.QtCore import Qt, Signal, QThread
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


class ClientsFetcher(QThread):
    """Fetches the client list from the authoritative API off the UI thread.

    Emits (clients_or_None, status): SUCCESS_WITH_DATA, SUCCESS_EMPTY,
    NETWORK_ERROR, HTTP_401, HTTP_403, HTTP_500, PARSE_ERROR.
    """
    clients_ready = Signal(object, str)

    def __init__(self, api_client, parent=None):
        super().__init__(parent)
        self._api = api_client

    def run(self):
        try:
            resp = self._api.get_clients(page=1, page_size=100)
            if isinstance(resp, dict) and "clients" in resp:
                status = "SUCCESS_WITH_DATA" if resp["clients"] else "SUCCESS_EMPTY"
                self.clients_ready.emit(resp["clients"], status)
                return
            if isinstance(resp, dict) and "http_error" in resp:
                code = resp["http_error"]
                if code == "NETWORK":
                    self.clients_ready.emit(None, "NETWORK_ERROR")
                    return
                if code == 200:
                    self.clients_ready.emit(None, "PARSE_ERROR")
                    return
                self.clients_ready.emit(None, f"HTTP_{code}")
                return
        except Exception as e:
            logger.info("Clients fetch failed: %s", e)
        self.clients_ready.emit(None, "NETWORK_ERROR")


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

        self._empty_lbl = QLabel(t("clients.no_data") if t("clients.no_data") != "clients.no_data" else "Aucun client trouvé")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setFont(QFont("Hanken Grotesk", 12))
        self._empty_lbl.setStyleSheet("color: #6B7264; padding: 40px;")
        self._empty_lbl.hide()
        layout.addWidget(self._empty_lbl, 1)

    # ── Data loading ──────────────────────────────────────────────

    def refresh_data(self):
        """Refresh clients from the canonical DomainStore snapshot. Never blocks UI."""
        try:
            from app.state.domain_store import get_domain_store
            store = get_domain_store()
            snap = store.snapshot
            if snap and hasattr(snap, "clients") and snap.clients:
                self._clients = list(snap.clients)
                self._set_mode_label(live=True)
                self._render()
                return
        except Exception as e:
            logger.debug("DomainStore client load note: %s", e)

        if self._api is not None and getattr(self._api, "_access_token", ""):
            fetcher = ClientsFetcher(self._api, parent=self)
            fetcher.clients_ready.connect(self._on_clients_fetched)
            fetcher.finished.connect(fetcher.deleteLater)
            self._fetcher = fetcher
            fetcher.start()
        else:
            self._clients = self._load_from_local_cache()
            self._set_mode_label(live=False)
            self._render()

    def _on_clients_fetched(self, clients, status):
        """Apply fetch result. API ERRORS are never rendered as '0 clients'."""
        if status in ("SUCCESS_WITH_DATA", "SUCCESS_EMPTY"):
            self._clients = clients or []
            self._set_mode_label(live=True)
            if status == "SUCCESS_EMPTY":
                self._mode_lbl.setText(t("clients.empty_server"))
        elif status == "NETWORK_ERROR":
            self._clients = self._load_from_local_cache()
            self._set_mode_label(live=False)
        elif status == "HTTP_401":
            self._mode_lbl.setText(t("clients.session_expired"))
            self._mode_lbl.setStyleSheet(
                "color: #B91C1C; background: #FEE2E2; border-radius: 6px; padding: 4px 10px;")
            return
        else:  # HTTP_403 / HTTP_500 / PARSE_ERROR
            self._clients = self._load_from_local_cache()
            self._mode_lbl.setText(t("clients.server_error"))
            self._mode_lbl.setStyleSheet(
                "color: #B91C1C; background: #FEE2E2; border-radius: 6px; padding: 4px 10px;")
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
        if len(rows) == 0:
            self._empty_lbl.show()
            self._table.hide()
        else:
            self._empty_lbl.hide()
            self._table.show()
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
                btn = QPushButton(t("clients.open_details") if t("clients.open_details") != "clients.open_details" else "Détails")
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
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight
        )
        self._title_lbl.setText(t("sidebar.clients"))
        self._search.setPlaceholderText(t("clients.search_ph"))
        self._headers = ["Client", "Téléphone", "Email", "CIN", t("vehicles.status"), ""]
        self._table.setHorizontalHeaderLabels(self._headers)
        self._empty_lbl.setText(t("clients.no_data") if t("clients.no_data") != "clients.no_data" else "Aucun client trouvé")
        self.refresh_data()

