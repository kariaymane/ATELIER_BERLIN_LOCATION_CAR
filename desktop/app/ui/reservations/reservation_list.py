"""
Reservation list and creation view.
Fully localized for French and Arabic with RTL layout support.
"""
from datetime import datetime, timezone
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
from app.sync.queue import SyncQueue


class ReservationFormDialog(QDialog):
    """Dialog to create a reservation for a selected vehicle."""
    saved = Signal(dict)

    def __init__(self, vehicle: dict, parent=None):
        super().__init__(parent)
        self.vehicle = vehicle
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

        # Customer Info
        self._customer_name = QLineEdit()
        self._customer_phone = QLineEdit()
        form.addRow(t("reservations.client_name"), self._customer_name)
        form.addRow(t("reservations.client_phone"), self._customer_phone)

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

    def _on_save(self):
        if not self._customer_name.text().strip():
            QMessageBox.warning(self, t("common.error"), t("reservations.err_name_req"))
            return

        start = self._start_dt.dateTime()
        end = self._end_dt.dateTime()

        if start >= end:
            QMessageBox.warning(self, t("common.error"), t("reservations.err_date_order"))
            return

        self.saved.emit({
            "vehicle_id": self.vehicle.get("id"),
            "customer_name": self.customer_name.text().strip(),
            "customer_phone": self._customer_phone.text().strip(),
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

    def __init__(self, device_id: str, user_id: str, user_role: str = "EMPLOYEE", parent=None):
        super().__init__(parent)
        self._device_id = device_id
        self._user_id = user_id
        self._user_role = user_role
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
            available = session.query(LocalVehicle).filter_by(status="AVAILABLE").all()

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
                # Auto-complete expired reservations
                if r.status in ("ACTIVE", "RESERVED") and r.end_datetime:
                    try:
                        end_dt = datetime.fromisoformat(r.end_datetime.replace('Z', '+00:00'))
                        if end_dt.tzinfo is None:
                            end_dt = end_dt.replace(tzinfo=timezone.utc)
                    except Exception:
                        end_dt = None

                    if end_dt and end_dt < now_time:
                        r.status = "COMPLETED"
                        r.updated_at = now_time.isoformat()
                        r.version += 1
                        queue.enqueue("reservation", r.id, "UPDATE", {"id": r.id, "status": "COMPLETED"})

                        v_auto = session.query(LocalVehicle).filter_by(id=r.vehicle_id).first()
                        if v_auto and v_auto.status == "RESERVED":
                            v_auto.status = "AVAILABLE"
                            v_auto.updated_at = now_time.isoformat()
                            v_auto.version += 1
                            queue.enqueue("vehicle", v_auto.id, "UPDATE", {"id": v_auto.id, "status": "AVAILABLE"})
                        session.commit()

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
                start_raw = r.start_datetime[:10] if r.start_datetime else ""
                end_raw = r.end_datetime[:10] if r.end_datetime else ""
                dates_str = f"{start_raw} - {end_raw}" if (start_raw or end_raw) else "-"
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
        dialog = ReservationFormDialog(vehicle_dict, self)
        dialog.saved.connect(self._create_reservation_record)
        dialog.exec()

    _save_reservation = lambda self, data: self._create_reservation_record(data)
    def _create_reservation_record(self, data: dict):
        session = get_local_session()
        try:
            v_id = data["vehicle_id"]
            new_start = data["start_datetime"]
            new_end = data["end_datetime"]

            # Double-booking prevention check locally in SQLite
            overlapping = session.query(LocalReservation).filter(
                LocalReservation.vehicle_id == v_id,
                LocalReservation.status.in_(["ACTIVE", "RESERVED"]),
                LocalReservation.start_datetime < new_end,
                LocalReservation.end_datetime > new_start,
            ).first()
            if overlapping:
                QMessageBox.warning(self, t("common.error"), "Ce véhicule possède déjà une réservation active sur cette période.")
                return

            res_id = str(uuid.uuid4())
            data["id"] = res_id
            now_iso = datetime.now(timezone.utc).isoformat()

            res = LocalReservation(
                id=res_id,
                vehicle_id=data["vehicle_id"],
                customer_name=data["customer_name"],
                customer_phone=data.get("customer_phone"),
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

            vehicle = session.query(LocalVehicle).filter_by(id=data["vehicle_id"]).first()
            if vehicle:
                vehicle.status = "RESERVED"
                vehicle.updated_at = now_iso
                vehicle.version += 1

            queue = SyncQueue(session, self._device_id, self._user_id)
            queue.enqueue("reservation", res_id, "CREATE", data)
            if vehicle:
                queue.enqueue("vehicle", vehicle.id, "UPDATE", {"id": vehicle.id, "status": "RESERVED"})

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
