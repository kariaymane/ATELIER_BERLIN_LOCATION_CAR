"""
Maintenance list and creation view.
Fully localized for French and Arabic with RTL layout support.
"""

import uuid
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QDialog, QFormLayout,
    QLineEdit, QDateTimeEdit, QComboBox, QTextEdit, QDoubleSpinBox,
    QStyleFactory,
)
from PySide6.QtCore import Qt, Signal, QDateTime
from PySide6.QtGui import QFont, QPalette, QColor

from app.i18n import t, is_rtl
from app.database import get_local_session
from app.models.vehicle import LocalVehicle
from app.models.maintenance import LocalMaintenance
from datetime import datetime, timezone
from app.sync.queue import SyncQueue


class MaintenanceFormDialog(QDialog):
    """Dialog to create a maintenance record for a selected vehicle."""
    saved = Signal(dict)

    def __init__(self, vehicle: dict = None, parent=None):
        super().__init__(parent)
        self.vehicle = vehicle
        brand_model = f"{vehicle.get('brand', '')} {vehicle.get('model', '')}".strip() if vehicle else t("maintenance.title")
        self.setWindowTitle(t("maintenance.dialog_title", name=brand_model))
        self.setMinimumWidth(500)
        self._setup_ui()

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        layout = QVBoxLayout(self)

        form = QFormLayout()

        if self.vehicle:
            info_lbl = QLabel(f"🔧 {self.vehicle.get('brand', '')} {self.vehicle.get('model', '')} ({self.vehicle.get('registration', '')})")
            info_lbl.setFont(QFont("Hanken Grotesk", 13, QFont.Weight.Bold))
            layout.addWidget(info_lbl)
        else:
            self._vehicle_combo = QComboBox()
            from app.database import get_local_session
            from app.models.vehicle import LocalVehicle
            session = get_local_session()
            try:
                vehicles = session.query(LocalVehicle).filter(LocalVehicle.status != "MAINTENANCE").all()
                for v in vehicles:
                    self._vehicle_combo.addItem(f"{v.brand} {v.model} ({v.registration})", v.id)
            finally:
                session.close()
            form.addRow(t("maintenance.col_vehicle"), self._vehicle_combo)

        self._type = QComboBox()
        self._type.addItem(t("maintenance.type_accident"), "Accident")
        self._type.addItem(t("maintenance.type_panne"), "Panne")
        self._type.addItem(t("maintenance.type_entretien"), "Entretien")
        self._type.addItem(t("maintenance.type_mecanique"), "Mécanique")
        self._type.addItem(t("maintenance.type_carrosserie"), "Carrosserie")
        self._type.addItem(t("maintenance.type_autre"), "Autre")
        form.addRow(t("maintenance.problem_type"), self._type)

        self._desc = QTextEdit()
        self._desc.setMaximumHeight(80)
        form.addRow(t("maintenance.description"), self._desc)

        now = QDateTime.currentDateTime()
        self._start_dt = QDateTimeEdit(now)
        self._start_dt.setCalendarPopup(True)
        form.addRow(t("maintenance.start_date"), self._start_dt)

        self._end_dt = QDateTimeEdit(now.addDays(7))
        self._end_dt.setCalendarPopup(True)
        form.addRow(t("maintenance.expected_return"), self._end_dt)

        self._cost = QDoubleSpinBox()
        self._cost.setRange(0, 1000000)
        curr = "DH" if not is_rtl() else "د.م"
        self._cost.setSuffix(f" {curr}")
        form.addRow(t("maintenance.estimated_cost"), self._cost)

        layout.addLayout(form)

        btns = QHBoxLayout()
        cancel = QPushButton(t("common.cancel"))
        cancel.setProperty("secondary", True)
        cancel.clicked.connect(self.reject)

        save = QPushButton(t("maintenance.btn_confirm"))
        save.setProperty("primary", True)
        save.clicked.connect(self._on_save)

        btns.addStretch()
        btns.addWidget(cancel)
        btns.addWidget(save)
        layout.addLayout(btns)

    def _on_save(self):
        start = self._start_dt.dateTime()
        end = self._end_dt.dateTime()

        if not self._desc.toPlainText().strip():
            QMessageBox.warning(self, t("common.error"), t("maintenance.err_desc_req"))
            return

        if start >= end:
            QMessageBox.warning(self, t("common.error"), t("maintenance.err_date_order"))
            return

        v_id = self.vehicle.get("id") if self.vehicle else self._vehicle_combo.currentData()
        if not v_id:
            QMessageBox.warning(self, t("common.error"), t("maintenance.col_vehicle") + " ?")
            return

        self.saved.emit({
            "vehicle_id": v_id,
            "type": self._type.currentData() or self._type.currentText(),
            "description": self._desc.toPlainText(),
            "start_datetime": start.toPython().replace(tzinfo=timezone.utc).isoformat(),
            "expected_end_datetime": end.toPython().replace(tzinfo=timezone.utc).isoformat(),
            "estimated_cost": self._cost.value(),
            "step": "DIAGNOSTIC",
            "status": "ACTIVE",
        })
        self.accept()


class MaintenanceWidget(QWidget):
    """Maintenance list view."""

    maintenance_updated = Signal()
    maintenance_add_requested = Signal(dict)

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

        # Header with title (left), Dernière actualisation and + Nouvelle maintenance (right)
        header = QHBoxLayout()
        self._title_lbl = QLabel(t("maintenance.title"))
        self._title_lbl.setFont(QFont("Libre Caslon Text", 20, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet("color: #1E4D38;")
        header.addWidget(self._title_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()

        self._last_refresh_lbl = QLabel(t("maintenance.last_refresh", time=datetime.now().strftime('%H:%M')))
        self._last_refresh_lbl.setFont(QFont("Hanken Grotesk", 10))
        self._last_refresh_lbl.setStyleSheet("color: #6B7264;")
        header.addWidget(self._last_refresh_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)

        if self._user_role in ("ADMIN", "MANAGER"):
            header.addSpacing(16)
            self._add_btn = QPushButton(f"+ {t('maintenance.add')}")
            self._add_btn.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.Bold))
            self._add_btn.clicked.connect(self._on_add_clicked)
            header.addWidget(self._add_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        else:
            self._add_btn = None

        layout.addLayout(header)

        # Filter bar
        filter_bar = QHBoxLayout()
        self._filter_lbl = QLabel(t("maintenance.filter_status"))
        self._filter_lbl.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Medium))
        filter_bar.addWidget(self._filter_lbl)

        self._status_filter = QComboBox()
        self._status_filter.addItem(t("maintenance.filter_active"), "active")
        self._status_filter.addItem(t("maintenance.filter_completed"), "completed")
        self._status_filter.addItem(t("maintenance.filter_all"), "all")
        self._status_filter.setFont(QFont("Hanken Grotesk", 10))
        self._status_filter.currentIndexChanged.connect(self.refresh_data)
        self._status_filter.setMinimumWidth(180)
        self._status_filter.setFixedHeight(34)
        filter_bar.addWidget(self._status_filter)
        filter_bar.addStretch()
        layout.addLayout(filter_bar)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            t("maintenance.col_vehicle"),
            t("maintenance.col_type"),
            t("maintenance.col_desc"),
            t("maintenance.col_return"),
            t("maintenance.col_step"),
            t("maintenance.col_actions")
        ])

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(5, 220)
        self._table.verticalHeader().setDefaultSectionSize(48)

        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)

        layout.addWidget(self._table)

        self._empty_lbl = QLabel(t("maintenance.no_data"))
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setFont(QFont("Hanken Grotesk", 11))
        self._empty_lbl.setStyleSheet("color: #6B7264;")
        self._empty_lbl.hide()
        layout.addWidget(self._empty_lbl)

    def retranslate_ui(self):
        """Update strings and table headers when language changes."""
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)
        self._title_lbl.setText(t("maintenance.title"))
        self._last_refresh_lbl.setText(t("maintenance.last_refresh", time=datetime.now().strftime('%H:%M')))
        if self._add_btn:
            self._add_btn.setText(f"+ {t('maintenance.add')}")
        self._filter_lbl.setText(t("maintenance.filter_status"))
        self._empty_lbl.setText(t("maintenance.no_data"))

        cur_data = self._status_filter.currentData()
        self._status_filter.blockSignals(True)
        self._status_filter.clear()
        self._status_filter.addItem(t("maintenance.filter_active"), "active")
        self._status_filter.addItem(t("maintenance.filter_completed"), "completed")
        self._status_filter.addItem(t("maintenance.filter_all"), "all")
        idx = self._status_filter.findData(cur_data)
        if idx >= 0:
            self._status_filter.setCurrentIndex(idx)
        self._status_filter.blockSignals(False)

        self._table.setHorizontalHeaderLabels([
            t("maintenance.col_vehicle"),
            t("maintenance.col_type"),
            t("maintenance.col_desc"),
            t("maintenance.col_return"),
            t("maintenance.col_step"),
            t("maintenance.col_actions")
        ])
        self.refresh_data()

    def set_filter(self, text: str):
        text = text.lower()
        for row in range(self._table.rowCount()):
            match = False
            for col in range(self._table.columnCount()):
                item = self._table.item(row, col)
                if item and text in item.text().lower():
                    match = True
            self._table.setRowHidden(row, not match)

    def _on_add_clicked(self):
        dialog = MaintenanceFormDialog(None, self)
        dialog.saved.connect(self.maintenance_add_requested.emit)
        dialog.exec()

    def refresh_data(self):
        session = get_local_session()
        try:
            filter_mode = self._status_filter.currentData() or "active"
            query = session.query(LocalMaintenance)
            if filter_mode == "active":
                query = query.filter(LocalMaintenance.status == "ACTIVE")
            elif filter_mode == "completed":
                query = query.filter(LocalMaintenance.status == "COMPLETED")

            maintenances = query.order_by(LocalMaintenance.created_at.desc()).all()
            self._table.setRowCount(len(maintenances))
            self._last_refresh_lbl.setText(t("maintenance.last_refresh", time=datetime.now().strftime('%H:%M')))

            if len(maintenances) == 0:
                self._empty_lbl.show()
                self._table.hide()
            else:
                self._empty_lbl.hide()
                self._table.show()

            for i, m in enumerate(maintenances):
                v = session.query(LocalVehicle).filter_by(id=m.vehicle_id).first()
                v_name = f"{v.brand} {v.model} ({v.registration})" if v else (m.vehicle_id or "—")

                # 0. Véhicule
                self._table.setItem(i, 0, QTableWidgetItem(v_name))

                # 1. Type
                type_key = f"maintenance.type_{m.type.lower()}" if m.type else ""
                translated_type = t(type_key) if type_key else (m.type or "—")
                self._table.setItem(i, 1, QTableWidgetItem(translated_type))

                # 2. Description
                self._table.setItem(i, 2, QTableWidgetItem(m.description or "—"))

                # 3. Retour Prévu
                return_date = "—"
                if m.expected_end_datetime:
                    try:
                        
                        from app.utils.datetime_utils import parse_datetime_utc
                        dt = parse_datetime_utc(m.expected_end_datetime)
                        return_date = dt.astimezone().strftime("%Y-%m-%d")
                    except Exception:
                        return_date = str(m.expected_end_datetime)[:10]
                self._table.setItem(i, 3, QTableWidgetItem(return_date))

                # 4. Étape (Badge)
                step = m.step or "DIAGNOSTIC"
                step_display = t(f"maintenance_steps.{step}")

                badge_widget = QWidget()
                bw_layout = QHBoxLayout(badge_widget)
                bw_layout.setContentsMargins(4, 2, 4, 2)
                badge_lbl = QLabel(step_display)
                badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                badge_lbl.setFont(QFont("Hanken Grotesk", 9, QFont.Weight.Bold))

                if step in ("EN ATTENTE", "DIAGNOSTIC"):
                    badge_lbl.setProperty("class", "badge_warning")
                elif step in ("REPARATION", "CONTROLE"):
                    badge_lbl.setProperty("class", "badge_info")
                else:
                    badge_lbl.setProperty("class", "badge_success")

                bw_layout.addWidget(badge_lbl)
                self._table.setCellWidget(i, 4, badge_widget)

                # 5. Actions (Étape suivante / Terminer)
                if m.status == "ACTIVE" and self._user_role in ("ADMIN", "MANAGER"):
                    act_widget = QWidget()
                    act_layout = QHBoxLayout(act_widget)
                    act_layout.setContentsMargins(4, 4, 4, 4)
                    act_layout.setSpacing(6)

                    if step != "TERMINE":
                        next_btn = QPushButton(t("maintenance.action_next_step"))
                        next_btn.setFont(QFont("Hanken Grotesk", 9, QFont.Weight.Bold))
                        next_btn.setStyleSheet("background-color: #F0F4EF; color: #2D5233; border: 1px solid #D5DFD3; border-radius: 4px; padding: 4px 8px;")
                        next_btn.clicked.connect(lambda _, mid=m.id, cur_s=step: self._advance_step(mid, cur_s))
                        act_layout.addWidget(next_btn)

                    finish_btn = QPushButton(t("maintenance.action_finish"))
                    finish_btn.setFont(QFont("Hanken Grotesk", 9, QFont.Weight.Bold))
                    finish_btn.setStyleSheet("background-color: #E8F3E6; color: #235821; border: 1px solid #C4DFC0; border-radius: 4px; padding: 4px 8px;")
                    finish_btn.clicked.connect(lambda _, mid=m.id: self._finish_maintenance(mid))
                    act_layout.addWidget(finish_btn)

                    self._table.setCellWidget(i, 5, act_widget)
                else:
                    self._table.setCellWidget(i, 5, QWidget())

        finally:
            session.close()

    def _advance_step(self, maint_id: str, current_step: str = None):
        session = get_local_session()
        if current_step is None:
            m = session.query(LocalMaintenance).filter_by(id=maint_id).first()
            current_step = m.step if m else "DIAGNOSTIC"
        session.close()

        steps = ["EN ATTENTE", "DIAGNOSTIC", "REPARATION", "CONTROLE", "TERMINE"]
        try:
            curr_idx = steps.index(current_step)
            next_step = steps[curr_idx + 1] if curr_idx + 1 < len(steps) else "TERMINE"
        except ValueError:
            next_step = "REPARATION"

        session = get_local_session()
        try:
            m = session.query(LocalMaintenance).filter_by(id=maint_id).first()
            if m:
                now_iso = datetime.now(timezone.utc).isoformat()
                m.step = next_step
                m.updated_at = now_iso
                m.version += 1

                queue = SyncQueue(session, self._device_id, self._user_id)
                queue.enqueue("maintenance", m.id, "UPDATE", {"id": m.id, "step": next_step})
                session.commit()

            self.refresh_data()
            self.maintenance_updated.emit()
        finally:
            session.close()

    def _finish_maintenance(self, maint_id: str):
        session = get_local_session()
        try:
            m = session.query(LocalMaintenance).filter_by(id=maint_id).first()
            if m:
                now_iso = datetime.now(timezone.utc).isoformat()
                m.status = "COMPLETED"
                m.step = "TERMINE"
                m.actual_end_datetime = now_iso
                m.updated_at = now_iso
                m.version += 1

                vehicle = session.query(LocalVehicle).filter_by(id=m.vehicle_id).first()
                if vehicle and vehicle.status == "MAINTENANCE":
                    vehicle.status = "AVAILABLE"
                    vehicle.updated_at = now_iso
                    vehicle.version += 1

                queue = SyncQueue(session, self._device_id, self._user_id)
                queue.enqueue("maintenance", m.id, "UPDATE", {"id": m.id, "status": "COMPLETED", "step": "TERMINE"})
                if vehicle:
                    queue.enqueue("vehicle", vehicle.id, "UPDATE", {"id": vehicle.id, "status": "AVAILABLE"})

                session.commit()

            self.refresh_data()
            self.maintenance_updated.emit()
        finally:
            session.close()
