"""
Reservation list and creation view.
Fully localized for French and Arabic with RTL layout support.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import logging
import uuid
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QScrollArea, QFrame,
    QPushButton, QLabel, QGridLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QDialog, QFormLayout, QLineEdit, QDateTimeEdit,
    QDoubleSpinBox, QStyleFactory,
)
from PySide6.QtCore import Qt, Signal, QDateTime, QDate, QTime
from PySide6.QtGui import QFont, QPalette, QColor

from app.i18n import t, is_rtl
from app.database import get_local_session
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.client import LocalClient
from app.sync.queue import SyncQueue
from app.models.sync_queue import SyncQueueItem

logger = logging.getLogger(__name__)


class ReservationFormDialog(QDialog):
    """Dialog to create a reservation for a selected vehicle."""
    saved = Signal(dict)

    def __init__(self, vehicle: dict, parent=None, api_client=None):
        super().__init__(parent)
        self.vehicle = vehicle
        from app.services.api_client import ApiClient
        from app.config import API_BASE_URL
        self._api = api_client or ApiClient(API_BASE_URL)
        brand_model = f"{vehicle.get('brand', '')} {vehicle.get('model', '')}".strip()
        self.setWindowTitle(t("reservations.dialog_title", name=brand_model))
        self.setMinimumWidth(500)
        self._setup_ui()

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        layout = QVBoxLayout(self)

        curr = "DH" if not is_rtl() else "د.م"
        info_lbl = QLabel(f"🚗 {self.vehicle.get('brand', '')} {self.vehicle.get('model', '')} - {self.vehicle.get('daily_rental_price', 0)} {curr} {t('vehicles.per_day')}")
        info_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        layout.addWidget(info_lbl)

        form = QFormLayout()

        # Client selection: existing Client OR new client (typed below)
        from PySide6.QtWidgets import QComboBox
        self._client_combo = QComboBox()
        self._client_combo.addItem(t("reservations.new_client"), None)
        self._clients_cache = self._load_clients_for_selection()
        for c in self._clients_cache:
            label = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
            if c.get("phone"):
                label += f" — {c['phone']}"
            self._client_combo.addItem(label, c.get("id"))
        self._client_combo.currentIndexChanged.connect(self._on_client_selected)
        form.addRow(t("sidebar.clients"), self._client_combo)

        # Customer Info
        self._customer_name = QLineEdit()
        self._customer_phone = QLineEdit()
        self._customer_email = QLineEdit()
        self._customer_cin = QLineEdit()
        self._selected_client_id = None
        self._id_card_path = ""
        self._id_card_back_path = ""
        self._license_path = ""
        self._license_back_path = ""

        self._id_card_btn = QPushButton(t("reservations.choose_image"))
        self._id_card_btn.clicked.connect(self._choose_id_card)
        self._id_card_back_btn = QPushButton(t("reservations.choose_image"))
        self._id_card_back_btn.clicked.connect(self._choose_id_card_back)
        self._license_btn = QPushButton(t("reservations.choose_image"))
        self._license_btn.clicked.connect(self._choose_license)
        self._license_back_btn = QPushButton(t("reservations.choose_image"))
        self._license_back_btn.clicked.connect(self._choose_license_back)

        form.addRow(t("reservations.client_name"), self._customer_name)
        form.addRow(t("reservations.client_phone"), self._customer_phone)
        form.addRow(t("reservations.email_client"), self._customer_email)
        form.addRow(t("clients.col_cin") if t("clients.col_cin") != "clients.col_cin" else "CIN", self._customer_cin)
        form.addRow(t("clients.docs_cin_recto"), self._id_card_btn)
        form.addRow(t("clients.docs_cin_verso"), self._id_card_back_btn)
        form.addRow(t("clients.docs_license_recto"), self._license_btn)
        form.addRow(t("clients.docs_license_verso"), self._license_back_btn)

        # Dates
        from PySide6.QtCore import QTime
        now = QDateTime.currentDateTime()
        # Normalize to canonical 09:00:00 local time to avoid accidental 
        # offset overlaps when user only modifies the date.
        now.setTime(QTime(9, 0, 0))
        
        start_val = self.vehicle.get("start_dt") or now
        end_val = self.vehicle.get("end_dt") or now.addDays(1)
        
        self._start_dt = QDateTimeEdit(start_val)
        self._start_dt.setCalendarPopup(True)
        self._start_dt.dateTimeChanged.connect(self._recalculate)

        self._end_dt = QDateTimeEdit(end_val)
        self._end_dt.setCalendarPopup(True)
        self._end_dt.dateTimeChanged.connect(self._recalculate)

        form.addRow(t("reservations.start_date"), self._start_dt)
        form.addRow(t("reservations.end_date"), self._end_dt)

        # Summary
        self._summary_lbl = QLabel()
        self._summary_lbl.setFont(QFont("Hanken Grotesk", 12, QFont.Weight.Bold))
        form.addRow(t("reservations.summary"), self._summary_lbl)

        # Availability Warning
        self._avail_lbl = QLabel()
        self._avail_lbl.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
        self._avail_lbl.setStyleSheet("color: #991B1B;")  # Red for warnings
        self._avail_lbl.hide()
        form.addRow("", self._avail_lbl)

        layout.addLayout(form)
        self._recalculate()

        # Buttons
        btns = QHBoxLayout()
        cancel = QPushButton(t("common.cancel"))
        cancel.clicked.connect(self.reject)

        self.save_btn = QPushButton(t("reservations.btn_confirm"))
        self.save_btn.setProperty("class", "primary")
        self.save_btn.clicked.connect(self._on_save)

        btns.addStretch()
        btns.addWidget(cancel)
        btns.addWidget(self.save_btn)
        layout.addLayout(btns)

    def _load_clients_for_selection(self):
        """Existing clients from the local cache (offline-safe)."""
        try:
            session = get_local_session()
            try:
                rows = session.query(LocalClient).order_by(
                    LocalClient.last_name, LocalClient.first_name).all()
                return [{
                    "id": c.id,
                    "first_name": c.first_name or "",
                    "last_name": c.last_name or "",
                    "phone": c.phone or "",
                    "email": c.email or "",
                    "cin_number": c.cin_number or "",
                } for c in rows]
            finally:
                session.close()
        except Exception as e:
            logger.warning("Client list load failed: %s", e)
            return []

    def _on_client_selected(self, index: int):
        client_id = self._client_combo.currentData()
        self._selected_client_id = client_id
        # Snapshot of the loaded existing-client values, so `_on_save` can tell
        # whether the user edited them (write-back) vs left them untouched.
        self._loaded_client_fields = None
        if client_id:
            for c in self._clients_cache:
                if c.get("id") == client_id:
                    name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
                    phone = c.get("phone", "") or ""
                    email = c.get("email", "") or ""
                    cin = c.get("cin_number", "") or ""
                    self._customer_name.setText(name)
                    self._customer_phone.setText(phone)
                    self._customer_email.setText(email)
                    self._customer_cin.setText(cin)
                    self._loaded_client_fields = {
                        "name": name, "phone": phone, "email": email, "cin": cin,
                    }
                    break
        else:
            # "Nouveau client" — no client identity may leak from a previous
            # selection. Every field starts blank.
            self._customer_name.clear()
            self._customer_phone.clear()
            self._customer_email.clear()
            self._customer_cin.clear()
            self._id_card_path = self._id_card_back_path = ""
            self._license_path = self._license_back_path = ""

    def _recalculate(self):
        start = self._start_dt.dateTime()
        end = self._end_dt.dateTime()

        days = start.daysTo(end)
        if days < 1:
            days = 1

        daily = self.vehicle.get('daily_rental_price', 0)
        total = days * daily
        self._summary_lbl.setText(t("reservations.summary_calc", days=days, daily=daily, total=total))
        self._calculated_days = days
        self._calculated_total = total
        
        # Immediate local availability check. The QDateTimeEdit holds local
        # wall time — CONVERT it to the UTC instant (same as `_on_save`), never
        # let parse_datetime_utc relabel a naive local value as UTC (that skewed
        # the pre-check ~1 h vs. what the reservation actually persists).
        req_start = parse_datetime_utc(start.toPython().astimezone(timezone.utc))
        req_end = parse_datetime_utc(end.toPython().astimezone(timezone.utc))
        
        if not req_start or not req_end or req_start >= req_end:
            self._avail_lbl.setText(t("reservations.err_date_order"))
            self._avail_lbl.show()
            if hasattr(self, 'save_btn'):
                self.save_btn.setEnabled(False)
            return
            
        v_id = self.vehicle.get("id")
        session = get_local_session()
        blocked_reason = None
        try:
            reservations = session.query(LocalReservation).filter(
                LocalReservation.vehicle_id == v_id,
                LocalReservation.status.in_(BLOCKING_RESERVATION_STATUSES)
            ).all()
            for r in reservations:
                r_start = parse_datetime_utc(r.start_datetime)
                r_end = parse_datetime_utc(r.end_datetime)
                if reservations_overlap(r_start, r_end, req_start, req_end):
                    blocked_reason = t("reservations.double_booking")
                    break
                    
            if not blocked_reason:
                maintenances = session.query(LocalMaintenance).filter(
                    LocalMaintenance.vehicle_id == v_id,
                    ~LocalMaintenance.status.in_(["CANCELLED", "COMPLETED"])
                ).all()
                for m in maintenances:
                    m_start = parse_datetime_utc(m.start_datetime)
                    m_end = parse_datetime_utc(m.actual_end_datetime) if m.actual_end_datetime else parse_datetime_utc(m.expected_end_datetime)
                    if m_start and not m_end and req_end > m_start:
                        blocked_reason = t("reservations.in_maintenance")
                        break
                    if reservations_overlap(m_start, m_end, req_start, req_end):
                        blocked_reason = t("reservations.in_maintenance")
                        break
        finally:
            session.close()

        if blocked_reason:
            self._avail_lbl.setText("⚠️ " + blocked_reason)
            self._avail_lbl.show()
            if hasattr(self, 'save_btn'):
                self.save_btn.setEnabled(False)
        else:
            self._avail_lbl.hide()
            if hasattr(self, 'save_btn'):
                self.save_btn.setEnabled(True)


    def _pick_document(self, attr: str, button, caption: str):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, caption, "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            setattr(self, attr, path)
            button.setText(path.split("/")[-1])

    def _choose_id_card(self):
        self._pick_document("_id_card_path", self._id_card_btn, t("clients.docs_cin_recto"))

    def _choose_id_card_back(self):
        self._pick_document("_id_card_back_path", self._id_card_back_btn, t("clients.docs_cin_verso"))

    def _choose_license(self):
        self._pick_document("_license_path", self._license_btn, t("clients.docs_license_recto"))

    def _choose_license_back(self):
        self._pick_document("_license_back_path", self._license_back_btn, t("clients.docs_license_verso"))
            
    def _upload_file(self, local_path):
        """Upload a client document (ID card / license).

        Returns the server URL on success. When offline, stores the file in
        DATA_DIR/pending_uploads and returns a relative `pending_uploads/`
        marker using the same convention as the vehicle photo form.
        """
        if not local_path:
            return ""
        if (local_path.startswith("http")
                or local_path.startswith("/static")
                or local_path.startswith("pending_uploads/")):
            return local_path

        try:
            res = self._api.upload_client_image(local_path)
            if res and isinstance(res, dict) and "image_url" in res:
                return res["image_url"]
        except Exception as e:
            logger.warning("Client document upload failed: %s", e)

        # Offline: durably queue the file for the SyncEngine pending-upload
        # processor; a marker placeholder is stored on the entity until the
        # upload is confirmed by the server.
        try:
            from app.sync.uploads import store_pending_file
            stored = store_pending_file(local_path)
            return f"pending_uploads/{stored.name}"
        except Exception:
            pass
        return ""

    def _on_save(self):
        if not self._customer_name.text().strip():
            QMessageBox.warning(self, t("common.error"), t("reservations.err_name_req"))
            return

        start = self._start_dt.dateTime()
        end = self._end_dt.dateTime()

        if start >= end:
            QMessageBox.warning(self, t("common.error"), t("reservations.err_date_order"))
            return

        id_url = self._upload_file(self._id_card_path)
        id_back_url = self._upload_file(self._id_card_back_path)
        lic_url = self._upload_file(self._license_path)
        lic_back_url = self._upload_file(self._license_back_path)

        # _creation_succeeded is set by the slot connected to `saved`
        # (_create_reservation_record). The dialog must only close when
        # the reservation was actually persisted — otherwise the user
        # loses all input and has to re-enter everything.
        # Write-back: when an existing client is selected and the user edited
        # any of its fields in this form, propagate the change to the canonical
        # Client record (not just this reservation's snapshot).
        client_field_updates = None
        if self._selected_client_id and getattr(self, "_loaded_client_fields", None):
            current = {
                "name": self._customer_name.text().strip(),
                "phone": self._customer_phone.text().strip(),
                "email": self._customer_email.text().strip(),
                "cin": self._customer_cin.text().strip(),
            }
            if current != self._loaded_client_fields:
                client_field_updates = current

        self._creation_succeeded = False
        self.saved.emit({
            "vehicle_id": self.vehicle.get("id"),
            "customer_id": self._selected_client_id,
            "client_field_updates": client_field_updates,
            "customer_name": self.customer_name.text().strip(),
            "customer_phone": self._customer_phone.text().strip(),
            "customer_email": self._customer_email.text().strip(),
            "customer_cin": self._customer_cin.text().strip(),
            "identity_card_image": id_url,
            "identity_card_image_back": id_back_url,
            "driving_license_image": lic_url,
            "driving_license_image_back": lic_back_url,
            "start_datetime": start.toPython().replace(tzinfo=ZoneInfo("Africa/Casablanca")).astimezone(timezone.utc).isoformat(),
            "end_datetime": end.toPython().replace(tzinfo=ZoneInfo("Africa/Casablanca")).astimezone(timezone.utc).isoformat(),
            "daily_price": self.vehicle.get('daily_rental_price', 0),
            "num_days": self._calculated_days,
            "total_price": self._calculated_total,
            "deposit": 0.0,
            "payment_status": "PENDING",
            "status": "RESERVED",
        })
        # Only close the dialog when the reservation was successfully
        # created.  On failure the dialog stays open so the user can
        # adjust dates / pick a different vehicle without re-entering
        # all client data.
        if self._creation_succeeded:
            self.accept()

    @property
    def customer_name(self):
        return self._customer_name


# Canonical datetime/overlap helpers (single source of truth).
from app.utils.datetime_utils import parse_datetime_utc, reservations_overlap, BLOCKING_RESERVATION_STATUSES
from app.models.maintenance import LocalMaintenance
from app.state.domain_store import get_domain_store


class ReservationWidget(QWidget):
    """Reservations module."""

    reservation_created = Signal()

    def __init__(self, device_id: str, user_id: str, user_role: str = "EMPLOYEE", parent=None, api_client=None):
        super().__init__(parent)
        self._device_id = device_id
        self._user_id = user_id
        self._user_role = user_role
        self._api = api_client
        # Canonical read model. The reservations table AND the "available
        # vehicles" grid are pure projections of the DomainStore snapshot;
        # this widget never queries SQLite for display state.
        self._store = get_domain_store()
        self._rendered_rev = None
        self._setup_ui()

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header with title and + Nouvelle réservation button
        header = QHBoxLayout()
        self._title_lbl = QLabel(t("reservations.title"))
        self._title_lbl.setFont(QFont("Libre Caslon Text", 20, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet("color: #1E4D38;")
        header.addWidget(self._title_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()

        self._add_res_btn = QPushButton(t("reservations.add"))
        self._add_res_btn.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.Bold))
        self._add_res_btn.clicked.connect(self._toggle_new_res_view)
        header.addWidget(self._add_res_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)

        self._tabs = QTabWidget()

        # Tab 1: List of reservations
        self._list_tab = QWidget()
        self._setup_list_tab()
        self._tabs.addTab(self._list_tab, t("reservations.tab_list").replace("&", "&&"))

        # Tab 2: Available cars for new reservation
        self._new_res_tab = QWidget()
        self._setup_new_res_tab()
        self._tabs.addTab(self._new_res_tab, t("reservations.tab_new"))

        layout.addWidget(self._tabs)
        self._tabs.currentChanged.connect(self.refresh_data)

    def retranslate_ui(self):
        """Update strings and table headers when language changes."""
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)
        self._title_lbl.setText(t("reservations.title"))
        self._add_res_btn.setText(t("reservations.add"))
        self._tabs.setTabText(0, t("reservations.tab_list").replace("&", "&&"))
        self._tabs.setTabText(1, t("reservations.tab_new"))
        self._empty_res_lbl.setText(t("reservations.no_data"))

        self._table.setHorizontalHeaderLabels([
            t("reservations.col_client"),
            t("reservations.col_vehicle"),
            t("reservations.col_dates"),
            t("reservations.col_total"),
            t("reservations.col_status"),
            t("reservations.col_actions")
        ])
        self.refresh_data()

    def _toggle_new_res_view(self):
        if self._tabs.currentIndex() == 0:
            self._tabs.setCurrentIndex(1)
        else:
            self._tabs.setCurrentIndex(0)

    def _setup_new_res_tab(self):
        layout = QVBoxLayout(self._new_res_tab)

        # Interval selection header
        filter_layout = QHBoxLayout()
        filter_layout.setContentsMargins(0, 0, 0, 10)
        
        now = QDateTime.currentDateTime()
        now.setTime(QTime(9, 0, 0))
        
        self._filter_start_dt = QDateTimeEdit(now)
        self._filter_start_dt.setCalendarPopup(True)
        # Filter dates are pure VIEW state — re-project the current snapshot,
        # no store reload. (Drop the QDateTime the signal passes.)
        self._filter_start_dt.dateTimeChanged.connect(lambda *_: self._refresh_available_vehicles())

        self._filter_end_dt = QDateTimeEdit(now.addDays(1))
        self._filter_end_dt.setCalendarPopup(True)
        self._filter_end_dt.dateTimeChanged.connect(lambda *_: self._refresh_available_vehicles())

        filter_layout.addWidget(QLabel(t("reservations.start_date")))
        filter_layout.addWidget(self._filter_start_dt)
        filter_layout.addSpacing(20)
        filter_layout.addWidget(QLabel(t("reservations.end_date")))
        filter_layout.addWidget(self._filter_end_dt)
        filter_layout.addStretch()
        
        layout.addLayout(filter_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._cars_container = QWidget()
        self._grid = QGridLayout(self._cars_container)
        self._grid.setSpacing(20)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll.setWidget(self._cars_container)
        layout.addWidget(scroll)

    def _setup_list_tab(self):
        layout = QVBoxLayout(self._list_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            t("reservations.col_client"),
            t("reservations.col_vehicle"),
            t("reservations.col_dates"),
            t("reservations.col_total"),
            t("reservations.col_status"),
            t("reservations.col_actions")
        ])

        header = self._table.horizontalHeader()
        header.setMinimumSectionSize(120)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(4, 130)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(5, 290)
        self._table.verticalHeader().setDefaultSectionSize(48)

        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)

        layout.addWidget(self._table)

        self._empty_res_lbl = QLabel(t("reservations.no_data"))
        self._empty_res_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_res_lbl.hide()
        layout.addWidget(self._empty_res_lbl)

    def set_filter(self, text: str):
        text = text.lower()
        for row in range(self._table.rowCount()):
            match = False
            for col in range(self._table.columnCount()):
                item = self._table.item(row, col)
                if item and text in item.text().lower():
                    match = True
            self._table.setRowHidden(row, not match)
    def _refresh_available_vehicles(self, snap=None):
        """Re-project the "available vehicles for the selected dates" grid.

        Pure function of (DomainStore snapshot, the two filter QDateTimeEdits).
        Reads NO SQLite — the snapshot already carries every vehicle,
        reservation and maintenance row plus each vehicle's canonical
        effective status.
        """
        if not hasattr(self, '_filter_start_dt') or not hasattr(self, '_filter_end_dt'):
            return

        snap = snap if snap is not None else self._store.snapshot

        start_dt = self._filter_start_dt.dateTime()
        end_dt = self._filter_end_dt.dateTime()

        # Parse to canonical UTC — CONVERT the local wall time, do not relabel it.
        req_start = parse_datetime_utc(start_dt.toPython().astimezone(timezone.utc))
        req_end = parse_datetime_utc(end_dt.toPython().astimezone(timezone.utc))

        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not req_start or not req_end or req_start >= req_end:
            return  # invalid interval — grid stays cleared

        # Exclude ONLY structural states — a raw ``MAINTENANCE`` flag is not
        # authoritative for a given date window; the maintenance interval
        # overlap check below is. Filtering it here would hide a vehicle that
        # is actually free for the requested dates.
        vehicles = [v for v in snap.vehicles
                    if (v.get("raw_status") or "").upper() not in ("SOLD", "INACTIVE")]
        blocking_reservations = [r for r in snap.reservations
                                 if (r.get("status") or "") in BLOCKING_RESERVATION_STATUSES]
        blocking_maintenances = [m for m in snap.maintenances
                                 if (m.get("status") or "").upper() not in ("CANCELLED", "COMPLETED")]

        available_vehicles = []
        for v in vehicles:
            vid = str(v.get("id"))
            blocked = False
            for r in blocking_reservations:
                if str(r.get("vehicle_id")) == vid:
                    r_start = parse_datetime_utc(r.get("start_datetime"))
                    r_end = parse_datetime_utc(r.get("end_datetime"))
                    if reservations_overlap(r_start, r_end, req_start, req_end):
                        blocked = True
                        break

            if not blocked:
                for m in blocking_maintenances:
                    if str(m.get("vehicle_id")) == vid:
                        m_start = parse_datetime_utc(m.get("start_datetime"))
                        # Maintenance blocks until actual_end_datetime, else expected_end_datetime.
                        m_end = (parse_datetime_utc(m.get("actual_end_datetime"))
                                 if m.get("actual_end_datetime")
                                 else parse_datetime_utc(m.get("expected_end_datetime")))
                        # No end time (indefinite maintenance): blocks everything after start.
                        if m_start and not m_end and req_end > m_start:
                            blocked = True
                            break
                        if reservations_overlap(m_start, m_end, req_start, req_end):
                            blocked = True
                            break

            if not blocked:
                available_vehicles.append(v)

        row, col = 0, 0
        for v in available_vehicles:
            card = self._create_available_card(v)
            self._grid.addWidget(card, row, col)
            col += 1
            if col >= 3:
                col = 0
                row += 1

    def refresh_data(self):
        """Public entrypoint. As a direct call (tab switch, language switch,
        tests) it asks the DomainStore to publish a fresh revision, then
        renders from that snapshot. When reached from the store fan-out
        (``MainWindow._on_domain_changed``) the reload is a re-entrant no-op
        and we render the already-published snapshot. Either way the table
        AND the availability grid are pure projections of ``store.snapshot``.
        """
        store = self._store
        rev_before = store.revision
        try:
            store.reload()
        except Exception as e:
            logger.error("Reservation snapshot reload failed: %s", e, exc_info=True)
        if store.revision != rev_before and self._rendered_rev == store.revision:
            return  # a re-entrant fan-out call already rendered this revision
        self._render_from_snapshot(store.snapshot)
        self._rendered_rev = store.revision

    def _render_from_snapshot(self, snap):
        """Render the reservations table + availability grid from the snapshot."""
        self._refresh_available_vehicles(snap)

        vehicles_by_id = {str(v.get("id")): v for v in snap.vehicles}
        reservations = sorted(
            snap.reservations, key=lambda r: r.get("created_at") or "", reverse=True)

        self._table.setRowCount(len(reservations))
        if len(reservations) == 0:
            self._empty_res_lbl.show()
            self._table.hide()
        else:
            self._empty_res_lbl.hide()
            self._table.show()

        for i, r in enumerate(reservations):
            v = vehicles_by_id.get(str(r.get("vehicle_id")))
            v_name = f"{v.get('brand', '')} {v.get('model', '')}".strip() if v else (r.get("vehicle_id") or "—")

            # 0. Client
            c_name = r.get("customer_name") or "—"
            c_phone = f" ({r.get('customer_phone')})" if r.get("customer_phone") else ""
            client_text = f"{c_name}{c_phone}"
            client_item = QTableWidgetItem(client_text)
            client_item.setToolTip(client_text)
            self._table.setItem(i, 0, client_item)

            # 1. Véhicule
            vehicle_item = QTableWidgetItem(v_name)
            vehicle_item.setToolTip(v_name)
            self._table.setItem(i, 1, vehicle_item)

            # 2. Dates
            start_dt_obj = self._parse_dt(r.get("start_datetime"))
            end_dt_obj = self._parse_dt(r.get("end_datetime"))
            start_local = start_dt_obj.astimezone().strftime("%Y-%m-%d") if start_dt_obj else ""
            end_local = end_dt_obj.astimezone().strftime("%Y-%m-%d") if end_dt_obj else ""
            dates_str = f"{start_local} - {end_local}" if (start_local or end_local) else "-"
            self._table.setItem(i, 2, QTableWidgetItem(dates_str))

            # 3. Prix Total
            curr = "DH" if not is_rtl() else "د.م"
            self._table.setItem(i, 3, QTableWidgetItem(f"{r.get('total_price') or 0:,.0f} {curr}"))

            # 4. Statut Badge
            status = r.get("status")
            label_txt = t(f"status.{status}")
            reason = (r.get("cancellation_reason") or "")
            is_maint_cancel = status == "CANCELLED" and reason.upper() == "MAINTENANCE"
            if is_maint_cancel:
                label_txt = t("reservations.cancelled_due_to_maintenance")
            badge_widget = QWidget()
            bw_layout = QHBoxLayout(badge_widget)
            bw_layout.setContentsMargins(4, 2, 4, 2)
            badge_lbl = QLabel(label_txt)
            badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge_lbl.setFont(QFont("Hanken Grotesk", 9, QFont.Weight.Bold))
            if is_maint_cancel:
                badge_lbl.setToolTip(t("reservations.cancelled_due_to_maintenance"))

            if status == "ACTIVE":
                badge_lbl.setProperty("class", "badge_success")
            elif status == "RESERVED":
                badge_lbl.setProperty("class", "badge_warning")
            elif status == "CANCELLED":
                badge_lbl.setProperty("class", "badge_danger")
            else:
                badge_lbl.setProperty("class", "badge_info")

            bw_layout.addWidget(badge_lbl)
            self._table.setCellWidget(i, 4, badge_widget)

            # 5. Action buttons
            if status in ("ACTIVE", "RESERVED") and self._user_role in ("ADMIN", "MANAGER"):
                act_widget = QWidget()
                act_layout = QHBoxLayout(act_widget)
                act_layout.setContentsMargins(4, 4, 4, 4)
                act_layout.setSpacing(6)

                # "Activer" is an explicit RESERVED -> ACTIVE operational-status
                # transition (e.g. staff confirming vehicle pickup at the
                # counter). It does NOT gate the "en location" / revenue KPIs —
                # those are time-derived (start <= now < end) and already count
                # a RESERVED reservation covering now. Activer is bookkeeping,
                # not a precondition for being "currently rented".
                if status == "RESERVED":
                    activate_btn = QPushButton(t("reservations.action_activate"))
                    activate_btn.setFont(QFont("Hanken Grotesk", 9, QFont.Weight.Bold))
                    activate_btn.setStyleSheet("background-color: #E7F0FE; color: #1D4ED8; border: 1px solid #BFDBFE; border-radius: 4px; padding: 4px 8px;")
                    activate_btn.clicked.connect(lambda _, res_id=r.get("id"): self._activate_reservation(res_id))
                    act_layout.addWidget(activate_btn)

                complete_btn = QPushButton(t("reservations.action_complete"))
                complete_btn.setFont(QFont("Hanken Grotesk", 9, QFont.Weight.Bold))
                complete_btn.setStyleSheet("background-color: #E8F3E6; color: #235821; border: 1px solid #C4DFC0; border-radius: 4px; padding: 4px 8px;")
                complete_btn.clicked.connect(lambda _, res_id=r.get("id"): self._complete_reservation(res_id))

                cancel_btn = QPushButton(t("reservations.action_cancel"))
                cancel_btn.setFont(QFont("Hanken Grotesk", 9, QFont.Weight.Bold))
                cancel_btn.setStyleSheet("background-color: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; border-radius: 4px; padding: 4px 8px;")
                cancel_btn.clicked.connect(lambda _, res_id=r.get("id"): self._cancel_reservation(res_id))

                act_layout.addWidget(complete_btn)
                act_layout.addWidget(cancel_btn)
                self._table.setCellWidget(i, 5, act_widget)
            else:
                self._table.setCellWidget(i, 5, QWidget())

    def _create_available_card(self, vehicle: dict) -> QFrame:
        """``vehicle`` is a DomainStore snapshot row (dict), not an ORM object."""
        card = QFrame()
        card.setProperty("class", "surface")
        card.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E5DE;
                border-radius: 8px;
                padding: 12px;
            }
            QFrame:hover {
                border: 1px solid #B5CDB0;
            }
        """)

        layout = QVBoxLayout(card)
        layout.setSpacing(8)

        brand_lbl = QLabel(f"{vehicle.get('brand', '')} {vehicle.get('model', '')}".strip())
        brand_lbl.setFont(QFont("Libre Caslon Text", 14, QFont.Weight.Bold))
        brand_lbl.setStyleSheet("color: #1E4D38;")

        fuel_lbl = t(f"fuel.{vehicle.get('fuel_type')}") if vehicle.get("fuel_type") else ""
        sub_info = f"{vehicle.get('registration', '')} · {vehicle.get('year') or ''} · {fuel_lbl}".strip(" · ")
        sub_lbl = QLabel(sub_info)
        sub_lbl.setFont(QFont("Hanken Grotesk", 10))
        sub_lbl.setStyleSheet("color: #6B7264;")

        curr = "DH" if not is_rtl() else "د.م"
        price_lbl = QLabel(f"{(vehicle.get('daily_rental_price') or 0):.0f} {curr} {t('vehicles.per_day')}")
        price_lbl.setFont(QFont("Hanken Grotesk", 12, QFont.Weight.Bold))
        price_lbl.setStyleSheet("color: #1E4D38;")

        btn = QPushButton(t("reservations.add"))
        btn.setProperty("class", "primary")
        btn.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
        v_dict = {
            "id": vehicle.get("id"),
            "brand": vehicle.get("brand"),
            "model": vehicle.get("model"),
            "registration": vehicle.get("registration"),
            "daily_rental_price": vehicle.get("daily_rental_price"),
            "start_dt": self._filter_start_dt.dateTime() if hasattr(self, '_filter_start_dt') else None,
            "end_dt": self._filter_end_dt.dateTime() if hasattr(self, '_filter_end_dt') else None
        }
        btn.clicked.connect(lambda _, vd=v_dict: self._open_new_reservation_dialog(vd))

        layout.addWidget(brand_lbl)
        layout.addWidget(sub_lbl)
        layout.addWidget(price_lbl)
        layout.addWidget(btn)

        return card

    def _open_new_reservation_dialog(self, vehicle_dict: dict):
        dialog = ReservationFormDialog(vehicle_dict, self, api_client=self._api)
        self._active_reservation_dialog = dialog
        dialog.saved.connect(self._create_reservation_record)
        dialog.exec()
        self._active_reservation_dialog = None

    _save_reservation = lambda self, data: self._create_reservation_record(data)

    @staticmethod
    def _parse_dt(value):
        """Parse an ISO datetime string into timezone-aware UTC datetime."""
        return parse_datetime_utc(value)

    def _create_reservation_record(self, data: dict):
        session = get_local_session()
        # Keep the client write-back payload out of the reservation sync body.
        client_field_updates = data.pop("client_field_updates", None)
        try:
            v_id = data["vehicle_id"]
            new_start = parse_datetime_utc(data["start_datetime"])
            new_end = parse_datetime_utc(data["end_datetime"])

            if not new_start or not new_end or new_end <= new_start:
                QMessageBox.warning(self, t("common.error"), t("reservations.err_date_order"))
                return

            # Ask the server for the authoritative verdict when online, and
            # PRESERVE THE ERROR CATEGORY — a business error must never be shown
            # as "server unreachable" and vice-versa:
            #   200 available:false      -> real conflict  (double-booking / maintenance)
            #   409                      -> real conflict
            #   401                      -> session expired
            #   403                      -> permission denied
            #   400 / 422                -> invalid reservation data
            #   404                      -> vehicle not on the server yet
            #                               (created offline) -> use local check
            #   5xx / malformed          -> server error
            #   transport (timeout after
            #     retries / connect)     -> server unreachable
            # Only a genuine transport failure or an outright server error
            # blocks with a technical message; a definitive verdict is obeyed.
            server_checked = False
            if self._api and getattr(self._api, "_access_token", ""):
                try:
                    avail_resp = self._api.check_availability(
                        v_id,
                        new_start.isoformat(),
                        new_end.isoformat()
                    )
                    code = avail_resp.get("http_error") if isinstance(avail_resp, dict) else None
                    is_transport = avail_resp is None or (
                        isinstance(avail_resp, dict) and (
                            avail_resp.get("transport")
                            or code in ("NETWORK", "timeout", "connect", "error")))

                    if isinstance(avail_resp, dict) and "available" in avail_resp:
                        server_checked = True
                        if not avail_resp["available"]:
                            logger.info("RESERVATION_AVAILABILITY_CHECK: SERVER BLOCKED reason=%s",
                                        avail_resp.get("reason"))
                            if avail_resp.get("reason") == "MAINTENANCE":
                                QMessageBox.warning(self, t("common.error"), t("reservations.in_maintenance"))
                            else:
                                QMessageBox.warning(self, t("common.error"), t("reservations.double_booking"))
                            return
                        logger.info("RESERVATION_AVAILABILITY_CHECK: SERVER AVAILABLE")
                    elif code == 409:
                        QMessageBox.warning(self, t("common.error"), t("reservations.double_booking"))
                        return
                    elif code == 401:
                        QMessageBox.warning(self, t("common.error"), t("clients.session_expired"))
                        return
                    elif code == 403:
                        QMessageBox.warning(self, t("common.error"), t("common.permission_denied"))
                        return
                    elif code in (400, 422):
                        QMessageBox.warning(self, t("common.error"), t("reservations.err_invalid_data"))
                        return
                    elif code == 404:
                        # Vehicle exists locally but not yet on the server
                        # (offline-first). Not an error — verify locally.
                        logger.info("RESERVATION_AVAILABILITY_CHECK: 404 — vehicle not synced, using local check")
                    elif is_transport:
                        logger.warning("RESERVATION_AVAILABILITY_CHECK: transport failure (%s) — unreachable", code)
                        QMessageBox.warning(self, t("common.error"), t("sync.server_unavailable"))
                        return
                    else:
                        # 5xx or malformed response — a real server-side error.
                        logger.warning("RESERVATION_AVAILABILITY_CHECK: server error %s", avail_resp)
                        QMessageBox.warning(self, t("common.error"), t("reservations.err_server_error"))
                        return
                except Exception as e:
                    logger.warning("Online availability check errored: %s", e)
                    QMessageBox.warning(self, t("common.error"), t("sync.server_unavailable"))
                    return

            if not server_checked:
                # Double-booking prevention — canonical overlap rule, real
                # datetime comparison (never string comparison):
                #   existing_start < requested_end AND existing_end > requested_start (adjacent allowed)
                # Only ACTIVE and RESERVED block; CANCELLED and COMPLETED reservations never block.
                overlapping = False
                blocking_info = {}
                for r in session.query(LocalReservation).filter(
                    LocalReservation.vehicle_id == v_id
                ).all():
                    r_status = (r.status or "").strip().upper()
                    if r_status not in ("ACTIVE", "RESERVED"):
                        continue
                    r_start = parse_datetime_utc(r.start_datetime)
                    r_end = parse_datetime_utc(r.end_datetime)
                    if reservations_overlap(r_start, r_end, new_start, new_end):
                        overlapping = True
                        blocking_info = {
                            "entity": "RESERVATION",
                            "id": r.id,
                            "status": r_status,
                            "start": r_start.isoformat(),
                            "end": r_end.isoformat(),
                        }
                        break

                if not overlapping:
                    from app.models.maintenance import LocalMaintenance
                    from app.utils.fleet_status import FAR_FUTURE
                    for m in session.query(LocalMaintenance).filter(
                        LocalMaintenance.vehicle_id == v_id
                    ).all():
                        m_status = (m.status or "").strip().upper()
                        if m_status in ("CANCELLED", "COMPLETED"):
                            continue
                        m_start = parse_datetime_utc(m.start_datetime)
                        # CANONICAL: an active maintenance with no explicit end
                        # is open-ended — it occupies the vehicle until closed.
                        m_end = (parse_datetime_utc(m.actual_end_datetime)
                                 or parse_datetime_utc(m.expected_end_datetime)
                                 or FAR_FUTURE)
                        if reservations_overlap(m_start, m_end, new_start, new_end):
                            overlapping = True
                            blocking_info = {
                                "entity": "MAINTENANCE",
                                "id": m.id,
                                "status": m_status,
                                "start": m_start.isoformat(),
                                "end": m_end.isoformat(),
                            }
                            break

                if overlapping:
                    logger.info(
                        "RESERVATION_AVAILABILITY_CHECK: vehicle_id=%s requested_start_utc=%s requested_end_utc=%s source=LOCAL result=BLOCKED blocking_entity=%s blocking_id=%s blocking_status=%s blocking_start=%s blocking_end=%s",
                        v_id, new_start.isoformat(), new_end.isoformat(),
                        blocking_info.get("entity"), blocking_info.get("id"),
                        blocking_info.get("status"), blocking_info.get("start"), blocking_info.get("end")
                    )
                    if blocking_info.get("entity") == "MAINTENANCE":
                        QMessageBox.warning(self, t("common.error"), t("reservations.in_maintenance"))
                    else:
                        QMessageBox.warning(self, t("common.error"), t("reservations.double_booking"))
                    return
                else:
                    logger.info(
                        "RESERVATION_AVAILABILITY_CHECK: vehicle_id=%s requested_start_utc=%s requested_end_utc=%s source=LOCAL result=AVAILABLE",
                        v_id, new_start.isoformat(), new_end.isoformat()
                    )

            res_id = str(uuid.uuid4())
            data["id"] = res_id
            now_iso = datetime.now(timezone.utc).isoformat()

            # TRANSACTIONAL: client + reservation + sync queue items are
            # committed as ONE unit. Any failure compensates: the queued
            # client CREATE is removed together with the local client row —
            # no orphan client, no orphan reservation.
            client_queue_item = None
            customer_id = data.get("customer_id")
            if not customer_id:
                customer_id = str(uuid.uuid4())
                raw_name = (data.get("customer_name") or "").strip()
                name_parts = raw_name.split(" ", 1)
                first_name = name_parts[0] if name_parts and name_parts[0] else "Client"
                last_name = name_parts[1] if len(name_parts) > 1 else ""
                new_client = LocalClient(
                    id=customer_id,
                    first_name=first_name,
                    last_name=last_name,
                    phone=data.get("customer_phone"),
                    email=data.get("customer_email"),
                    cin_number=data.get("customer_cin"),
                    identity_card_image=data.get("identity_card_image"),
                    identity_card_image_back=data.get("identity_card_image_back"),
                    driving_license_image=data.get("driving_license_image"),
                    driving_license_image_back=data.get("driving_license_image_back"),
                    status="ACTIVE",
                    created_at=now_iso,
                    updated_at=now_iso,
                    version=1,
                )
                session.add(new_client)
                queue_tmp = SyncQueue(session, self._device_id, self._user_id)
                client_queue_item = queue_tmp.enqueue("client", customer_id, "CREATE", {
                    "id": customer_id,
                    "first_name": new_client.first_name,
                    "last_name": new_client.last_name,
                    "phone": new_client.phone,
                    "email": new_client.email,
                    "cin_number": new_client.cin_number,
                    "identity_card_image": new_client.identity_card_image,
                    "identity_card_image_back": new_client.identity_card_image_back,
                    "driving_license_image": new_client.driving_license_image,
                    "driving_license_image_back": new_client.driving_license_image_back,
                    "status": "ACTIVE",
                })
                data["customer_id"] = customer_id
            data["customer_name"] = data.get("customer_name")

            try:

                res = LocalReservation(
                    id=res_id,
                    vehicle_id=data["vehicle_id"],
                    customer_id=customer_id,
                    customer_name=data["customer_name"],
                    customer_phone=data.get("customer_phone"),
                    customer_email=data.get("customer_email"),
                    identity_card_image=data.get("identity_card_image"),
                    driving_license_image=data.get("driving_license_image"),
                    cancellation_reason=None,
                    start_datetime=data["start_datetime"],
                    end_datetime=data["end_datetime"],
                    daily_price=data.get("daily_price", 0.0),
                    num_days=data.get("num_days", 1),
                    total_price=data.get("total_price", 0.0),
                    deposit=data.get("deposit", 0.0),
                    payment_status=data.get("payment_status", "PENDING"),
                    status="RESERVED",
                    created_at=now_iso,
                    updated_at=now_iso,
                    version=1
                )
                session.add(res)

                # CANONICAL: vehicle.status is NOT changed on reservation creation
                # (matches the backend — availability is governed by date-overlap,
                # not by vehicle.status). The old local RESERVED manipulation
                # caused vehicles to disappear from the available list for all
                # dates after any booking.

                queue = SyncQueue(session, self._device_id, self._user_id)
                queue.enqueue("reservation", res_id, "CREATE", data)

                # WRITE-BACK: an existing client whose fields were edited in
                # this form updates the canonical Client record (same
                # transaction), so every observer converges on the new data.
                client_updates = client_field_updates
                if data.get("customer_id") and not client_queue_item and client_updates:
                    existing_client = session.query(LocalClient).filter_by(
                        id=data["customer_id"]).one_or_none()
                    if existing_client is not None:
                        raw = (client_updates.get("name") or "").strip()
                        parts = raw.split(" ", 1)
                        if parts and parts[0]:
                            existing_client.first_name = parts[0]
                            existing_client.last_name = parts[1] if len(parts) > 1 else ""
                        existing_client.phone = client_updates.get("phone") or None
                        existing_client.email = client_updates.get("email") or None
                        existing_client.cin_number = client_updates.get("cin") or None
                        existing_client.updated_at = now_iso
                        existing_client.version = (existing_client.version or 1) + 1
                        queue.enqueue("client", existing_client.id, "UPDATE", {
                            "id": existing_client.id,
                            "first_name": existing_client.first_name,
                            "last_name": existing_client.last_name,
                            "phone": existing_client.phone,
                            "email": existing_client.email,
                            "cin_number": existing_client.cin_number,
                            "version": existing_client.version,
                        })

                # Register durable pending-upload records for offline documents.
                from app.sync.uploads import register_pending_upload
                for field in ("identity_card_image", "driving_license_image"):
                    register_pending_upload(
                        session,
                        marker=data.get(field) or "",
                        entity_type="reservation",
                        entity_id=res_id,
                        upload_type="CLIENT_DOCUMENT",
                        remote_endpoint="/api/v1/clients/upload-image",
                        field_name=field,
                    )
                # Verso images belong to the Client entity only (the reservation
                # snapshot has no *_back columns). Register them against the
                # client so the pending-upload processor resolves the marker in
                # the client row + the client CREATE sync payload.
                for field in ("identity_card_image_back", "driving_license_image_back"):
                    register_pending_upload(
                        session,
                        marker=data.get(field) or "",
                        entity_type="client",
                        entity_id=customer_id,
                        upload_type="CLIENT_DOCUMENT",
                        remote_endpoint="/api/v1/clients/upload-image",
                        field_name=field,
                    )

                session.commit()
            except Exception as creation_error:
                # ROLLBACK + COMPENSATE: remove the already-committed client
                # CREATE queue item and the local client row so no orphan
                # client survives a failed reservation creation.
                session.rollback()
                if client_queue_item is not None:
                    try:
                        session.query(SyncQueueItem).filter_by(
                            id=client_queue_item.id).delete()
                        session.query(LocalClient).filter_by(
                            id=customer_id).delete()
                        session.commit()
                        logger.warning(
                            "Reservation creation failed (%s) — compensated: client %s removed",
                            creation_error, customer_id)
                    except Exception as comp_error:
                        logger.error("Compensation failed: %s", comp_error)
                QMessageBox.warning(self, t("common.error"),
                                    str(creation_error) or t("common.error"))
                return

            # Signal success back to the dialog so it closes.
            dlg = getattr(self, "_active_reservation_dialog", None)
            if dlg is not None:
                dlg._creation_succeeded = True

            self._tabs.setCurrentIndex(0)
            self.refresh_data()
            self.reservation_created.emit()

        except Exception as e:
            session.rollback()
            QMessageBox.critical(self, t("common.error"), f"Erreur lors de la réservation: {e}")
        finally:
            session.close()

    def _set_reservation_status(self, res_id: str, new_status: str):
        """Canonical write path for a manual reservation status change
        (complete / cancel). One transaction via ``DomainStore.mutate()``: on
        commit the store reloads and every view converges; on failure it rolls
        back and publishes NOTHING.
        """
        def _apply(session):
            res = session.query(LocalReservation).filter_by(id=res_id).first()
            if not res:
                return
            now_iso = datetime.now(timezone.utc).isoformat()
            res.status = new_status
            res.updated_at = now_iso
            res.version += 1
            SyncQueue(session, self._device_id, self._user_id).enqueue(
                "reservation", res_id, "UPDATE", {"id": res_id, "status": new_status})

        try:
            self._store.mutate(_apply)
        except Exception as e:
            logger.error("Failed to set reservation %s -> %s: %s", res_id, new_status, e, exc_info=True)
            QMessageBox.critical(self, t("common.error"), t("common.error"))
            return
        self.reservation_created.emit()  # -> MainWindow triggers a background sync

    def _activate_reservation(self, res_id: str):
        """RESERVED -> ACTIVE: an explicit operational bookkeeping transition
        (e.g. confirming vehicle pickup at the counter). It does NOT gate the
        "en location" / revenue KPIs, which are time-derived and already
        count a RESERVED reservation covering `now` — see fleet_status.py."""
        self._set_reservation_status(res_id, "ACTIVE")

    def _complete_reservation(self, res_id: str):
        self._set_reservation_status(res_id, "COMPLETED")

    def _cancel_reservation(self, res_id: str):
        self._set_reservation_status(res_id, "CANCELLED")
