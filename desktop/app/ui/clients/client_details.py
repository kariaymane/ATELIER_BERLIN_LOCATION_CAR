"""
Client Details view — canonical live client report.

ONLINE : every value comes from GET /api/v1/clients/{id}/rentals
         (PostgreSQL via FastAPI — the single business authority).
OFFLINE: falls back to local SQLite reconciliation (cache) and the header
         explicitly shows "Données locales (hors ligne)".

Displayed rules come from the backend canonical report:
  - CANCELLED rentals are listed but excluded from totals
  - days use the server-stored duration (num_days)
  - amounts are server-computed totals (Numeric-backed)
"""
import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QFrame, QMessageBox,
)

from app.i18n import t, is_rtl
from app.services.image_cache import get_image_cache

logger = logging.getLogger(__name__)


class ClientReportFetcher(QThread):
    """Fetches the canonical client rental report off the UI thread."""
    report_ready = Signal(dict)
    fetch_failed = Signal()

    def __init__(self, api_client, client_id: str, parent=None):
        super().__init__(parent)
        self._api = api_client
        self._client_id = client_id

    def run(self):
        try:
            report = self._api.get_client_rentals_report(self._client_id)
            if isinstance(report, dict) and "summary" in report:
                self.report_ready.emit(report)
            else:
                self.fetch_failed.emit()
        except Exception as e:
            logger.info("Client report fetch failed: %s", e)
            self.fetch_failed.emit()


class ClientDetailsDialog(QDialog):
    """Full-screen style details dialog for one client."""

    def __init__(self, client_row: dict, api_client=None, parent=None):
        super().__init__(parent)
        self._client = dict(client_row or {})
        self._client_id = str(self._client.get("id") or "")
        self._api = api_client
        self._fetcher = None
        self.setWindowTitle(t("clients.client_details"))
        self.resize(1080, 720)
        self._setup_ui()
        self._load()

    # ── UI construction ───────────────────────────────────────────

    def _setup_ui(self):
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        # Header: name + live/offline mode chip
        header = QHBoxLayout()
        title = f"{self._client.get('first_name', '')} {self._client.get('last_name', '')}".strip() or "—"
        self._name_lbl = QLabel(title)
        self._name_lbl.setFont(QFont("Libre Caslon Text", 19, QFont.Weight.Bold))
        self._name_lbl.setStyleSheet("color: #1E4D38;")
        header.addWidget(self._name_lbl)
        header.addStretch()
        self._mode_lbl = QLabel("")
        self._mode_lbl.setFont(QFont("Hanken Grotesk", 9))
        self._mode_lbl.setStyleSheet(
            "color: #975A16; background: #FEF3C7; border-radius: 6px; padding: 4px 10px;")
        header.addWidget(self._mode_lbl)
        close = QPushButton("✕")
        close.setFixedSize(34, 34)
        close.clicked.connect(self.accept)
        header.addWidget(close)
        layout.addLayout(header)

        # Identity block
        info = QFrame()
        info.setObjectName("clientInfo")
        info.setStyleSheet("#clientInfo { background: #F7FAF5; border-radius: 10px; }")
        info_layout = QHBoxLayout(info)
        info_layout.setContentsMargins(16, 12, 16, 12)
        info_layout.setSpacing(26)
        self._info_labels = {}
        for key in ("id", "phone", "email", "cin_number"):
            box = QVBoxLayout()
            cap = QLabel({
                "id": "ID", "phone": t("clients.col_phone"),
                "email": t("clients.col_email"), "cin_number": t("clients.col_cin"),
            }[key])
            cap.setStyleSheet("color: #6B7264; font-size: 11px;")
            val = QLabel(self._display(self._client.get(key)))
            val.setStyleSheet("color: #2D3748; font-size: 13px; font-weight: 600;")
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(cap)
            box.addWidget(val)
            self._info_labels[key] = val
            info_layout.addLayout(box)
        info_layout.addStretch()

        # Documents
        docs_box = QVBoxLayout()
        docs_box.setSpacing(6)
        self._doc_thumbs = {}
        for key, label_key in (("identity_card_image", "docs_cin"),
                               ("driving_license_image", "docs_license")):
            cap = QLabel(t(f"clients.{label_key}"))
            cap.setStyleSheet("color: #6B7264; font-size: 11px;")
            thumb = QLabel(t("clients.doc_missing"))
            thumb.setFixedSize(96, 64)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setStyleSheet(
                "background: #FFFFFF; border: 1px solid #D5DDD3; border-radius: 8px; color: #9CA3AF; font-size: 10px;")
            self._doc_thumbs[key] = thumb
            docs_box.addWidget(cap)
            docs_box.addWidget(thumb)
        info_layout.addLayout(docs_box)
        layout.addWidget(info)

        # KPI cards row
        kpis = QHBoxLayout()
        kpis.setSpacing(12)
        self._kpi_cards = {}
        kpi_defs = [
            ("total_rentals", t("clients.total_rentals")),
            ("total_days", t("clients.total_days")),
            ("total_amount", t("clients.total_amount")),
            ("active_rentals", t("clients.active")),
            ("completed_rentals", t("clients.completed")),
            ("cancelled_rentals", t("clients.cancelled")),
            ("vehicles_rented", t("clients.vehicles_rented")),
        ]
        for key, label in kpi_defs:
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background: #1E4D38; border-radius: 10px; }")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(10, 10, 10, 10)
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #CDE3D5; font-size: 10px;")
            lbl.setWordWrap(True)
            val = QLabel("—")
            val.setStyleSheet("color: #FFFFFF; font-size: 17px; font-weight: 700;")
            cl.addWidget(lbl)
            cl.addWidget(val)
            self._kpi_cards[key] = val
            kpis.addWidget(card, 1)
        layout.addLayout(kpis)

        # Rental history table
        self._history_title = QLabel(t("clients.rental_history"))
        self._history_title.setFont(QFont("Hanken Grotesk", 13, QFont.Weight.Bold))
        self._history_title.setStyleSheet("color: #1E4D38;")
        layout.addWidget(self._history_title)

        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._hist_headers = [
            t("clients.col_vehicle"), t("clients.col_registration"),
            t("clients.col_start"), t("clients.col_end"),
            t("clients.total_days"), t("clients.col_daily_price"),
            t("clients.col_total"), t("vehicles.status"), "ID",
        ]
        self._table.setHorizontalHeaderLabels(self._hist_headers)
        hv = self._table.horizontalHeader()
        hv.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 8):
            hv.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hv.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(8, 90)
        self._table.verticalHeader().setDefaultSectionSize(36)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table, 1)

        # Vehicle breakdown strip
        self._vehicles_lbl = QLabel("")
        self._vehicles_lbl.setWordWrap(True)
        self._vehicles_lbl.setStyleSheet("color: #4A5568; font-size: 12px;")
        layout.addWidget(self._vehicles_lbl)

    @staticmethod
    def _display(value):
        return str(value) if value else "—"

    # ── Data flow ─────────────────────────────────────────────────

    def _load(self):
        """Load live canonical data; fall back to labeled local cache."""
        if self._api is not None:
            self._fetcher = ClientReportFetcher(self._api, self._client_id, parent=self)
            self._fetcher.report_ready.connect(self._on_report_ready)
            self._fetcher.fetch_failed.connect(self._on_fetch_failed)
            self._fetcher.finished.connect(self._fetcher.deleteLater)
            self._mode_lbl.setText("...")
            self._fetcher.start()
        else:
            self._apply_offline_fallback()

    def _on_report_ready(self, report: dict):
        self._set_mode(live=True)
        s = report.get("summary", {})
        self._apply_summary(s)
        self._apply_history(report.get("rentals") or [])
        self._apply_vehicles(report.get("vehicles") or [])

    def _on_fetch_failed(self):
        self._apply_offline_fallback()

    def _apply_offline_fallback(self):
        """Reconcile from the local SQLite cache; clearly labeled offline.

        Uses the same eligibility rule as the backend:
          CANCELLED excluded from totals; num_days is canonical duration.
        """
        self._set_mode(live=False)
        try:
            from app.database import get_local_session
            from app.models.reservation import LocalReservation
            session = get_local_session()
            try:
                name = f"{self._client.get('first_name', '')} {self._client.get('last_name', '')}".strip()
                phone = self._client.get("phone", "")
                query = session.query(LocalReservation)
                conds = []
                if phone:
                    conds.append(LocalReservation.customer_phone == phone)
                if name:
                    conds.append(LocalReservation.customer_name.ilike(f"%{name}%"))
                rows = []
                if conds:
                    from sqlalchemy import or_
                    rows = query.filter(or_(*conds)).order_by(
                        LocalReservation.start_datetime.desc()).all()
                summary = {
                    "total_rentals": 0, "total_days": 0, "total_amount": 0.0,
                    "active_rentals": 0, "completed_rentals": 0,
                    "cancelled_rentals": 0, "vehicles_rented": 0,
                }
                vehicles = {}
                hist = []
                for r in rows:
                    veh = ""
                    reg = ""
                    if r.vehicle_id:
                        from app.models.vehicle import LocalVehicle
                        vrec = session.query(LocalVehicle).filter_by(id=r.vehicle_id).first()
                        if vrec:
                            veh = f"{vrec.brand or ''} {vrec.model or ''}".strip()
                            reg = vrec.registration or ""
                    hist.append({
                        "vehicle_label": veh or "—", "registration": reg or "—",
                        "start": r.start_datetime, "end": r.end_datetime,
                        "num_days": int(r.num_days or 1),
                        "daily_price": float(r.daily_price or 0),
                        "total_price": float(r.total_price or 0),
                        "status": r.status, "rid": r.id,
                    })
                    if r.status == "CANCELLED":
                        summary["cancelled_rentals"] += 1
                        continue
                    summary["total_rentals"] += 1
                    days = int(r.num_days or 1)
                    amount = float(r.total_price or 0)
                    summary["total_days"] += days
                    summary["total_amount"] += amount
                    if r.status == "ACTIVE":
                        summary["active_rentals"] += 1
                    elif r.status == "COMPLETED":
                        summary["completed_rentals"] += 1
                    entry = vehicles.setdefault(r.vehicle_id, {
                        "label": veh or r.vehicle_id, "rentals": 0,
                        "days": 0, "amount": 0.0})
                    entry["rentals"] += 1
                    entry["days"] += days
                    entry["amount"] += amount
                summary["vehicles_rented"] = len(vehicles)
                summary["total_amount"] = round(summary["total_amount"], 2)
                self._apply_summary(summary)
                self._render_history(hist)
                parts = [
                    f"{e['label']} — {e['rentals']} loc / {e['days']} j / "
                    f"{round(e['amount'], 2)} DH"
                    for e in sorted(vehicles.values(), key=lambda x: x['rentals'], reverse=True)
                ]
                self._vehicles_lbl.setText(
                    " · ".join(parts) if parts else "—")
            finally:
                session.close()
        except Exception as e:
            logger.error("Offline client fallback failed: %s", e)

    def _set_mode(self, live: bool):
        if live:
            self._mode_lbl.setText(t("clients.live_data"))
            self._mode_lbl.setStyleSheet(
                "color: #1E4D38; background: #E6F4EA; border-radius: 6px; padding: 4px 10px;")
        else:
            self._mode_lbl.setText(t("clients.offline_data"))
            self._mode_lbl.setStyleSheet(
                "color: #975A16; background: #FEF3C7; border-radius: 6px; padding: 4px 10px;")

    def _apply_summary(self, s: dict):
        currency = "د.م" if is_rtl() else "DH"
        self._kpi_cards["total_rentals"].setText(str(s.get("total_rentals", 0)))
        self._kpi_cards["total_days"].setText(str(s.get("total_days", 0)))
        self._kpi_cards["total_amount"].setText(f"{float(s.get('total_amount', 0)):.2f} {currency}")
        self._kpi_cards["active_rentals"].setText(str(s.get("active_rentals", 0)))
        self._kpi_cards["completed_rentals"].setText(str(s.get("completed_rentals", 0)))
        self._kpi_cards["cancelled_rentals"].setText(str(s.get("cancelled_rentals", 0)))
        self._kpi_cards["vehicles_rented"].setText(str(s.get("vehicles_rented", 0)))

    def _apply_history(self, rentals: list):
        rows = []
        for r in rentals:
            rows.append({
                "vehicle_label": f"{r.get('vehicle_brand', '')} {r.get('vehicle_model', '')}".strip() or "—",
                "registration": r.get("vehicle_registration") or "—",
                "start": (r.get("start_datetime") or "")[:16].replace("T", " "),
                "end": (r.get("end_datetime") or "")[:16].replace("T", " "),
                "num_days": r.get("num_days", 1),
                "daily_price": r.get("daily_price", 0),
                "total_price": r.get("total_price", 0),
                "status": r.get("status", ""),
                "rid": r.get("id", ""),
            })
        self._render_history(rows)

    def _render_history(self, rows: list):
        self._table.setRowCount(len(rows))
        currency = "د.م" if is_rtl() else "DH"
        for i, r in enumerate(rows):
            vals = [
                r.get("vehicle_label", "—"),
                r.get("registration", "—"),
                str(r.get("start", "—")),
                str(r.get("end", "—")),
                str(r.get("num_days", 1)),
                f"{float(r.get('daily_price', 0)):.2f}",
                f"{float(r.get('total_price', 0)):.2f} {currency}",
                t(f"status.{r['status']}") if r.get("status") else "—",
                str(r.get("rid", ""))[:8],
            ]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(i, col, item)
        if not rows:
            self._table.setRowCount(1)
            empty = QTableWidgetItem("—")
            self._table.setItem(0, 0, empty)

    def _apply_vehicles(self, vehicles: list):
        currency = "د.م" if is_rtl() else "DH"
        parts = []
        for v in vehicles:
            label = f"{v.get('brand', '')} {v.get('model', '')}".strip() or v.get("registration", "")
            parts.append(
                f"{label} ({v.get('registration', '')}) — "
                f"{v.get('rentals', 0)} loc / {v.get('days', 0)} j / "
                f"{float(v.get('amount', 0)):.2f} {currency}"
            )
        self._vehicles_lbl.setText(" · ".join(parts) if parts else "—")

    # ── Documents ────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._load_document_thumbnails()

    def _load_document_thumbnails(self):
        """Render document thumbnails through the authenticated image cache.

        Missing documents keep the explicit 'Document non disponible' state.
        The cache delivers images asynchronously via image_loaded.
        """
        cache = get_image_cache()
        if not hasattr(self, "_doc_cache_connected"):
            cache.image_loaded.connect(self._on_doc_image_loaded)
            self._doc_cache_connected = True
        for key, thumb in self._doc_thumbs.items():
            url = self._client.get(key)
            if not url or not str(url).startswith("/static"):
                continue  # keep "Document non disponible"
            thumb.setProperty("cache_key", f"{self._client_id}_{cache._build_url(url)}")
            thumb.setText("⏳")
            cache.get_image(url, vehicle_id=self._client_id)

    def _on_doc_image_loaded(self, cache_key: str, pixmap):
        if not pixmap or pixmap.isNull():
            return
        for key, thumb in self._doc_thumbs.items():
            if thumb.property("cache_key") == cache_key:
                thumb.setText("")
                thumb.setPixmap(pixmap.scaled(
                    thumb.size(), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
                break
