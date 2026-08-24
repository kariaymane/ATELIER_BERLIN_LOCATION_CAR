"""
Reservation list and creation view.
Fully localized for French and Arabic with RTL layout support.
"""
from datetime import datetime, timezone
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
        self._selected_client_id = None
        self._id_card_path = ""
        self._license_path = ""
        
        self._id_card_btn = QPushButton(t("reservations.choose_image"))
        self._id_card_btn.clicked.connect(self._choose_id_card)
        self._license_btn = QPushButton(t("reservations.choose_image"))
        self._license_btn.clicked.connect(self._choose_license)
        
        form.addRow(t("reservations.client_name"), self._customer_name)
        form.addRow(t("reservations.client_phone"), self._customer_phone)
        form.addRow(t("reservations.email_client"), self._customer_email)
        form.addRow(t("reservations.id_card"), self._id_card_btn)
        form.addRow(t("reservations.license"), self._license_btn)

        # Dates
        now = QDateTime.currentDateTime()
        self._start_dt = QDateTimeEdit(now)
        self._start_dt.setCalendarPopup(True)
        self._start_dt.dateTimeChanged.connect(self._recalculate)

        self._end_dt = QDateTimeEdit(now.addDays(1))
        self._end_dt.setCalendarPopup(True)
        self._end_dt.dateTimeChanged.connect(self._recalculate)

        form.addRow(t("reservations.start_date"), self._start_dt)
        form.addRow(t("reservations.end_date"), self._end_dt)

        # Summary
        self._summary_lbl = QLabel()
        self._summary_lbl.setFont(QFont("Hanken Grotesk", 12, QFont.Weight.Bold))
        form.addRow(t("reservations.summary"), self._summary_lbl)

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
                } for c in rows]
            finally:
                session.close()
        except Exception as e:
            logger.warning("Client list load failed: %s", e)
            return []

    def _on_client_selected(self, index: int):
        client_id = self._client_combo.currentData()
        self._selected_client_id = client_id
        if client_id:
            for c in self._clients_cache:
                if c.get("id") == client_id:
                    self._customer_name.setText(
                        f"{c.get('first_name', '')} {c.get('last_name', '')}".strip())
                    self._customer_phone.setText(c.get("phone", ""))
                    self._customer_email.setText(c.get("email", ""))
                    break

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


    def _choose_id_card(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Choisir Carte d'identification", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._id_card_path = path
            self._id_card_btn.setText(path.split("/")[-1])

    def _choose_license(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Choisir Permis de conduire", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._license_path = path
            self._license_btn.setText(path.split("/")[-1])
            
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
        lic_url = self._upload_file(self._license_path)
        
        self.saved.emit({
            "vehicle_id": self.vehicle.get("id"),
            "customer_id": self._selected_client_id,
            "customer_name": self.customer_name.text().strip(),
            "customer_phone": self._customer_phone.text().strip(),
            "customer_email": self._customer_email.text().strip(),
            "identity_card_image": id_url,
            "driving_license_image": lic_url,
            "start_datetime": start.toPython().astimezone(timezone.utc).isoformat(),
            "end_datetime": end.toPython().astimezone(timezone.utc).isoformat(),
            "daily_price": self.vehicle.get('daily_rental_price', 0),
            "num_days": self._calculated_days,
            "total_price": self._calculated_total,
            "deposit": 0.0,
            "payment_status": "PENDING",
            "status": "RESERVED",
        })
        self.accept()

    @property
    def customer_name(self):
        return self._customer_name


class ReservationWidget(QWidget):
    """Reservations module."""

    reservation_created = Signal()

    def __init__(self, device_id: str, user_id: str, user_role: str = "EMPLOYEE", parent=None, api_client=None):
        super().__init__(parent)
        self._device_id = device_id
        self._user_id = user_id
        self._user_role = user_role
        self._api = api_client
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
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(4, 130)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(5, 200)
        self._table.verticalHeader().setDefaultSectionSize(42)

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

    def refresh_data(self):
        """Fetch all real reservations and vehicles from SQLite local DB."""
        session = get_local_session()
        try:
            # Operational vehicles for new reservations: availability for the
            # chosen dates is governed by the overlap check, not by status.
            available = session.query(LocalVehicle).filter(
                ~LocalVehicle.status.in_(["MAINTENANCE", "SOLD", "INACTIVE"])
            ).all()

            while self._grid.count():
                item = self._grid.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            row, col = 0, 0
            for v in available:
                card = self._create_available_card(v)
                self._grid.addWidget(card, row, col)
                col += 1
                if col >= 3:
                    col = 0
                    row += 1

            reservations = session.query(LocalReservation).order_by(LocalReservation.created_at.desc()).all()
            self._table.setRowCount(len(reservations))

            if len(reservations) == 0:
                self._empty_res_lbl.show()
                self._table.hide()
            else:
                self._empty_res_lbl.hide()
                self._table.show()

            now_time = datetime.now(timezone.utc)
            queue = SyncQueue(session, self._device_id, self._user_id)

            for i, r in enumerate(reservations):
                # Removed erroneous auto-complete of expired reservations logic.
                # A reservation must be manually closed when the vehicle is returned.

                # Vehicle details
                v = session.query(LocalVehicle).filter_by(id=r.vehicle_id).first()
                v_name = f"{v.brand} {v.model}" if v else (r.vehicle_id or "—")

                # 0. Client
                c_name = r.customer_name or "—"
                c_phone = f" ({r.customer_phone})" if r.customer_phone else ""
                self._table.setItem(i, 0, QTableWidgetItem(f"{c_name}{c_phone}"))

                # 1. Véhicule
                self._table.setItem(i, 1, QTableWidgetItem(v_name))

                # 2. Dates
                start_dt_obj = self._parse_dt(r.start_datetime)
                end_dt_obj = self._parse_dt(r.end_datetime)
                start_local = start_dt_obj.astimezone().strftime("%Y-%m-%d") if start_dt_obj else ""
                end_local = end_dt_obj.astimezone().strftime("%Y-%m-%d") if end_dt_obj else ""
                dates_str = f"{start_local} - {end_local}" if (start_local or end_local) else "-"
                self._table.setItem(i, 2, QTableWidgetItem(dates_str))

                # 3. Prix Total
                curr = "DH" if not is_rtl() else "د.م"
                self._table.setItem(i, 3, QTableWidgetItem(f"{r.total_price or 0:,.0f} {curr}"))

                # 4. Statut Badge
                label_txt = t(f"status.{r.status}")
                badge_widget = QWidget()
                bw_layout = QHBoxLayout(badge_widget)
                bw_layout.setContentsMargins(4, 2, 4, 2)
                badge_lbl = QLabel(label_txt)
                badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                badge_lbl.setFont(QFont("Hanken Grotesk", 9, QFont.Weight.Bold))

                if r.status == "ACTIVE":
                    badge_lbl.setProperty("class", "badge_success")
                elif r.status == "RESERVED":
                    badge_lbl.setProperty("class", "badge_warning")
                elif r.status == "CANCELLED":
                    badge_lbl.setProperty("class", "badge_danger")
                else:
                    badge_lbl.setProperty("class", "badge_info")

                bw_layout.addWidget(badge_lbl)
                self._table.setCellWidget(i, 4, badge_widget)

                # 5. Action buttons
                if r.status in ("ACTIVE", "RESERVED") and self._user_role in ("ADMIN", "MANAGER"):
                    act_widget = QWidget()
                    act_layout = QHBoxLayout(act_widget)
                    act_layout.setContentsMargins(4, 4, 4, 4)
                    act_layout.setSpacing(6)

                    complete_btn = QPushButton(t("reservations.action_complete"))
                    complete_btn.setFont(QFont("Hanken Grotesk", 9, QFont.Weight.Bold))
                    complete_btn.setStyleSheet("background-color: #E8F3E6; color: #235821; border: 1px solid #C4DFC0; border-radius: 4px; padding: 4px 8px;")
                    complete_btn.clicked.connect(lambda _, res_id=r.id: self._complete_reservation(res_id))

                    cancel_btn = QPushButton(t("reservations.action_cancel"))
                    cancel_btn.setFont(QFont("Hanken Grotesk", 9, QFont.Weight.Bold))
                    cancel_btn.setStyleSheet("background-color: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; border-radius: 4px; padding: 4px 8px;")
                    cancel_btn.clicked.connect(lambda _, res_id=r.id: self._cancel_reservation(res_id))

                    act_layout.addWidget(complete_btn)
                    act_layout.addWidget(cancel_btn)
                    self._table.setCellWidget(i, 5, act_widget)
                else:
                    self._table.setCellWidget(i, 5, QWidget())

        finally:
            session.close()

    def _create_available_card(self, vehicle: LocalVehicle) -> QFrame:
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

        brand_lbl = QLabel(f"{vehicle.brand} {vehicle.model}")
        brand_lbl.setFont(QFont("Libre Caslon Text", 14, QFont.Weight.Bold))
        brand_lbl.setStyleSheet("color: #1E4D38;")

        fuel_lbl = t(f"fuel.{vehicle.fuel_type}") if vehicle.fuel_type else ""
        sub_info = f"{vehicle.registration} · {vehicle.year or ''} · {fuel_lbl}".strip(" · ")
        sub_lbl = QLabel(sub_info)
        sub_lbl.setFont(QFont("Hanken Grotesk", 10))
        sub_lbl.setStyleSheet("color: #6B7264;")

        curr = "DH" if not is_rtl() else "د.م"
        price_lbl = QLabel(f"{vehicle.daily_rental_price:.0f} {curr} {t('vehicles.per_day')}")
        price_lbl.setFont(QFont("Hanken Grotesk", 12, QFont.Weight.Bold))
        price_lbl.setStyleSheet("color: #1E4D38;")

        btn = QPushButton(t("reservations.add"))
        btn.setProperty("class", "primary")
        btn.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
        v_dict = {
            "id": vehicle.id,
            "brand": vehicle.brand,
            "model": vehicle.model,
            "registration": vehicle.registration,
            "daily_rental_price": vehicle.daily_rental_price
        }
        btn.clicked.connect(lambda _, vd=v_dict: self._open_new_reservation_dialog(vd))

        layout.addWidget(brand_lbl)
        layout.addWidget(sub_lbl)
        layout.addWidget(price_lbl)
        layout.addWidget(btn)

        return card

    def _open_new_reservation_dialog(self, vehicle_dict: dict):
        dialog = ReservationFormDialog(vehicle_dict, self, api_client=self._api)
        dialog.saved.connect(self._create_reservation_record)
        dialog.exec()

    _save_reservation = lambda self, data: self._create_reservation_record(data)
    @staticmethod
    def _parse_dt(value):
        """Parse an ISO datetime string tolerating Z / offsets / naive forms."""
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt
        except Exception:
            return None

    def _create_reservation_record(self, data: dict):
        session = get_local_session()
        try:
            v_id = data["vehicle_id"]
            new_start = self._parse_dt(data["start_datetime"])
            new_end = self._parse_dt(data["end_datetime"])

            if not new_start or not new_end or new_end <= new_start:
                QMessageBox.warning(self, t("common.error"), t("reservations.err_date_order"))
                return

            # Double-booking prevention — canonical overlap rule, real
            # datetime comparison (never string comparison):
            #   start_A < end_B AND end_A > start_B   (adjacent allowed)
            # CANCELLED and COMPLETED reservations never block.
            overlapping = False
            for r in session.query(LocalReservation).filter(
                LocalReservation.vehicle_id == v_id,
                LocalReservation.status.in_(["ACTIVE", "RESERVED"]),
            ).all():
                r_start = self._parse_dt(r.start_datetime)
                r_end = self._parse_dt(r.end_datetime)
                if r_start and r_end and r_start < new_end and r_end > new_start:
                    overlapping = True
                    break

            if not overlapping:
                from app.models.maintenance import LocalMaintenance
                from datetime import timedelta
                for m in session.query(LocalMaintenance).filter(
                    LocalMaintenance.vehicle_id == v_id,
                    LocalMaintenance.status.notin_(["CANCELLED", "COMPLETED"]),
                ).all():
                    m_start = self._parse_dt(m.start_datetime)
                    m_end = self._parse_dt(m.expected_end_datetime) or self._parse_dt(m.actual_end_datetime)
                    if m_end is None and m_start:
                        m_end = m_start + timedelta(days=1)
                    if m_start and m_end and m_start < new_end and m_end > new_start:
                        overlapping = True
                        break

            if overlapping:
                QMessageBox.warning(self, t("common.error"), t("reservations.double_booking"))
                return

            res_id = str(uuid.uuid4())
            data["id"] = res_id
            now_iso = datetime.now(timezone.utc).isoformat()

            # Client relationship: existing client selected in the dialog, or
            # a new Client created from the entered information.
            customer_id = data.get("customer_id")
            if not customer_id:
                customer_id = str(uuid.uuid4())
                new_client = LocalClient(
                    id=customer_id,
                    first_name=data.get("customer_name", "").split(" ")[0],
                    last_name=" ".join(data.get("customer_name", "").split(" ")[1:]),
                    phone=data.get("customer_phone"),
                    email=data.get("customer_email"),
                    identity_card_image=data.get("identity_card_image"),
                    driving_license_image=data.get("driving_license_image"),
                    status="ACTIVE",
                    created_at=now_iso,
                    updated_at=now_iso,
                    version=1,
                )
                session.add(new_client)
                queue_tmp = SyncQueue(session, self._device_id, self._user_id)
                queue_tmp.enqueue("client", customer_id, "CREATE", {
                    "id": customer_id,
                    "first_name": new_client.first_name,
                    "last_name": new_client.last_name,
                    "phone": new_client.phone,
                    "email": new_client.email,
                    "identity_card_image": new_client.identity_card_image,
                    "driving_license_image": new_client.driving_license_image,
                    "status": "ACTIVE",
                })
                data["customer_id"] = customer_id
            data["customer_name"] = data.get("customer_name")

            res = LocalReservation(
                id=res_id,
                vehicle_id=data["vehicle_id"],
                customer_id=customer_id,
                customer_name=data["customer_name"],
                customer_phone=data.get("customer_phone"),
                customer_email=data.get("customer_email"),
                identity_card_image=data.get("identity_card_image"),
                driving_license_image=data.get("driving_license_image"),
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

            session.commit()

            self._tabs.setCurrentIndex(0)
            self.refresh_data()
            self.reservation_created.emit()

        except Exception as e:
            session.rollback()
            QMessageBox.critical(self, t("common.error"), f"Erreur lors de la réservation: {e}")
        finally:
            session.close()

    def _complete_reservation(self, res_id: str):
        session = get_local_session()
        try:
            res = session.query(LocalReservation).filter_by(id=res_id).first()
            if not res:
                return

            now_iso = datetime.now(timezone.utc).isoformat()
            res.status = "COMPLETED"
            res.updated_at = now_iso
            res.version += 1

            vehicle = session.query(LocalVehicle).filter_by(id=res.vehicle_id).first()
            if vehicle and vehicle.status == "RESERVED":
                vehicle.status = "AVAILABLE"
                vehicle.updated_at = now_iso
                vehicle.version += 1

            queue = SyncQueue(session, self._device_id, self._user_id)
            queue.enqueue("reservation", res_id, "UPDATE", {"id": res_id, "status": "COMPLETED"})
            if vehicle:
                queue.enqueue("vehicle", vehicle.id, "UPDATE", {"id": vehicle.id, "status": "AVAILABLE"})

            session.commit()
            self.refresh_data()
            self.reservation_created.emit()
        finally:
            session.close()

    def _cancel_reservation(self, res_id: str):
        session = get_local_session()
        try:
            res = session.query(LocalReservation).filter_by(id=res_id).first()
            if not res:
                return

            now_iso = datetime.now(timezone.utc).isoformat()
            res.status = "CANCELLED"
            res.updated_at = now_iso
            res.version += 1

            vehicle = session.query(LocalVehicle).filter_by(id=res.vehicle_id).first()
            if vehicle and vehicle.status == "RESERVED":
                vehicle.status = "AVAILABLE"
                vehicle.updated_at = now_iso
                vehicle.version += 1

            queue = SyncQueue(session, self._device_id, self._user_id)
            queue.enqueue("reservation", res_id, "UPDATE", {"id": res_id, "status": "CANCELLED"})
            if vehicle:
                queue.enqueue("vehicle", vehicle.id, "UPDATE", {"id": vehicle.id, "status": "AVAILABLE"})

            session.commit()
            self.refresh_data()
            self.reservation_created.emit()
        finally:
            session.close()
