"""
Dashboard view — 1:1 Stitch ATELIER BERLIN LOCATION CAR Dashboard Overview.
Styled after Stitch Design with full French & Arabic localization support.
"""
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QGroupBox, QPushButton, QProgressBar, QComboBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from app.i18n import t, is_rtl


class OperationalStatCard(QFrame):
    """A card showing operational statistics styled after Soft Pastel Executive."""
    def __init__(self, title: str, count: str = "0", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setProperty("card", "true")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(105)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        # Title
        self._title_lbl = QLabel(title)
        self._title_lbl.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.Medium))
        self._title_lbl.setStyleSheet("color: #637060;")
        layout.addWidget(self._title_lbl)

        # Big number
        self._count_lbl = QLabel(count)
        self._count_lbl.setFont(QFont("Hanken Grotesk", 24, QFont.Weight.Bold))
        self._count_lbl.setStyleSheet("color: #1A221A;")
        layout.addWidget(self._count_lbl)

        # Optional subtitle
        if subtitle:
            self._sub_lbl = QLabel(subtitle)
            self._sub_lbl.setFont(QFont("Hanken Grotesk", 10))
            self._sub_lbl.setStyleSheet("color: #909C8E;")
            layout.addWidget(self._sub_lbl)
        else:
            layout.addStretch()

    def set_data(self, count: str):
        self._count_lbl.setText(count)

    def set_title(self, title: str):
        self._title_lbl.setText(title)


class ExecutiveFleetCard(QFrame):
    """A card showing vehicle category counts styled after Soft Pastel Executive."""
    def __init__(self, title: str, count: str = "0", has_progress: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("fleetCard")
        self.setProperty("card", "true")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(95)
        self._has_progress = has_progress
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        # Title
        self._title_lbl = QLabel(title)
        self._title_lbl.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.Medium))
        self._title_lbl.setStyleSheet("color: #637060;")
        layout.addWidget(self._title_lbl)

        # Big number row
        num_row = QHBoxLayout()
        self._count_lbl = QLabel(count)
        self._count_lbl.setFont(QFont("Hanken Grotesk", 24, QFont.Weight.Bold))
        self._count_lbl.setStyleSheet("color: #1A221A;")
        num_row.addWidget(self._count_lbl)
        num_row.addStretch()

        if self._has_progress:
            self._ratio_lbl = QLabel("0/0")
            self._ratio_lbl.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
            self._ratio_lbl.setStyleSheet("color: #637060;")
            num_row.addWidget(self._ratio_lbl)

        layout.addLayout(num_row)

        if self._has_progress:
            self._prog_bar = QProgressBar()
            self._prog_bar.setFixedHeight(6)
            self._prog_bar.setTextVisible(False)
            self._prog_bar.setRange(0, 100)
            self._prog_bar.setValue(0)
            layout.addWidget(self._prog_bar)
        else:
            layout.addStretch()

    def set_title(self, title: str):
        self._title_lbl.setText(title)

    def set_count(self, count_val: str, current: int = 0, total: int = 0):
        self._count_lbl.setText(count_val)
        if self._has_progress and total > 0:
            self._ratio_lbl.setText(f"{current}/{total}")
            pct = int((current / total) * 100) if total > 0 else 0
            self._prog_bar.setValue(pct)


class DashboardWidget(QWidget):
    """Main dashboard with real data and full live localization."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_period = "week"
        self._overview_data = {}
        self._top_vehicles_data = []
        self._setup_ui()

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(18)

        # ─────────────────────────────────────────────────────────────
        # Header: Title (Tableau de bord) + Dernière actualisation
        # ─────────────────────────────────────────────────────────────
        header_layout = QHBoxLayout()
        header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._title_lbl = QLabel(t("dashboard.title"))
        self._title_lbl.setFont(QFont("Libre Caslon Text", 20, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet("color: #1E4D38;")
        header_layout.addWidget(self._title_lbl)
        header_layout.addStretch()

        self._last_refresh_lbl = QLabel(t("dashboard.last_refresh", time=datetime.now().strftime('%H:%M')))
        self._last_refresh_lbl.setFont(QFont("Hanken Grotesk", 10))
        self._last_refresh_lbl.setStyleSheet("color: #6B7264;")
        header_layout.addWidget(self._last_refresh_lbl)
        layout.addLayout(header_layout)

        # ─────────────────────────────────────────────────────────────
        # 1. Operational Stats Row
        # ─────────────────────────────────────────────────────────────
        filter_layout = QHBoxLayout()
        self._period_lbl = QLabel(t("dashboard.period"))
        self._period_lbl.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
        self._period_lbl.setStyleSheet("color: #6B7264;")

        self._period_combo = QComboBox()
        self._period_combo.addItem(t("dashboard.period_today"), "today")
        self._period_combo.addItem(t("dashboard.period_week"), "week")
        self._period_combo.addItem(t("dashboard.period_month"), "month")
        self._period_combo.setCurrentIndex(1)  # Default: week
        self._period_combo.currentIndexChanged.connect(self._on_period_changed)

        filter_layout.addStretch()
        filter_layout.addWidget(self._period_lbl)
        filter_layout.addWidget(self._period_combo)
        layout.addLayout(filter_layout)

        perf_grid = QGridLayout()
        perf_grid.setSpacing(14)

        self._card_revenue = OperationalStatCard(t("dashboard.revenue"), "0 DH")
        self._card_day = OperationalStatCard(t("dashboard.week_reservations"), "0")
        self._card_maintenance = OperationalStatCard(t("dashboard.active_maintenances"), "0")

        perf_grid.addWidget(self._card_revenue, 0, 0)
        perf_grid.addWidget(self._card_day, 0, 1)
        perf_grid.addWidget(self._card_maintenance, 0, 2)
        layout.addLayout(perf_grid)

        # ─────────────────────────────────────────────────────────────
        # 2. Fleet Status Row
        # ─────────────────────────────────────────────────────────────
        fleet_grid = QGridLayout()
        fleet_grid.setSpacing(14)

        self._card_available = ExecutiveFleetCard(t("dashboard.available_fleet"), "0")
        self._card_rented = ExecutiveFleetCard(t("dashboard.rented_fleet"), "0", has_progress=True)
        self._card_reserved = ExecutiveFleetCard(t("dashboard.reserved_fleet"), "0")
        self._card_fleet_maintenance = ExecutiveFleetCard(t("dashboard.maintenance_fleet"), "0")

        fleet_grid.addWidget(self._card_available, 0, 0)
        fleet_grid.addWidget(self._card_rented, 0, 1)
        fleet_grid.addWidget(self._card_reserved, 0, 2)
        fleet_grid.addWidget(self._card_fleet_maintenance, 0, 3)
        layout.addLayout(fleet_grid)

        # ─────────────────────────────────────────────────────────────
        # 3. Top 5 Véhicules les plus loués
        # ─────────────────────────────────────────────────────────────
        self._top_box = QGroupBox(t("dashboard.top_rented"))
        self._top_box.setFont(QFont("Hanken Grotesk", 12, QFont.Weight.Bold))
        top_layout = QVBoxLayout(self._top_box)
        top_layout.setContentsMargins(14, 14, 14, 14)

        self._top_container = QWidget()
        self._top_layout = QVBoxLayout(self._top_container)
        self._top_layout.setContentsMargins(0, 0, 0, 0)
        self._top_layout.setSpacing(6)
        top_layout.addWidget(self._top_container)
        top_layout.addStretch()

        layout.addWidget(self._top_box)

    def retranslate_ui(self):
        """Live update all strings when application language changes."""
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)
        self._title_lbl.setText(t("dashboard.title"))
        self._last_refresh_lbl.setText(t("dashboard.last_refresh", time=datetime.now().strftime('%H:%M')))
        self._period_lbl.setText(t("dashboard.period"))

        current_idx = self._period_combo.currentIndex()
        self._period_combo.blockSignals(True)
        self._period_combo.clear()
        self._period_combo.addItem(t("dashboard.period_today"), "today")
        self._period_combo.addItem(t("dashboard.period_week"), "week")
        self._period_combo.addItem(t("dashboard.period_month"), "month")
        self._period_combo.setCurrentIndex(max(0, current_idx))
        self._period_combo.blockSignals(False)

        self._card_revenue.set_title(t("dashboard.revenue"))
        self._card_maintenance.set_title(t("dashboard.active_maintenances"))
        self._card_available.set_title(t("dashboard.available_fleet"))
        self._card_rented.set_title(t("dashboard.rented_fleet"))
        self._card_reserved.set_title(t("dashboard.reserved_fleet"))
        self._card_fleet_maintenance.set_title(t("dashboard.maintenance_fleet"))
        self._top_box.setTitle(t("dashboard.top_rented"))

        self._on_period_changed()
        self._render_top_vehicles()

    def _set_period(self, period: str):
        self._current_period = period

    def refresh_data(self, overview: dict, top_vehicles: list = None):
        """Refresh all real dashboard data from database."""
        self._overview_data = overview or {}
        self._top_vehicles_data = top_vehicles or []
        self._last_refresh_lbl.setText(t("dashboard.last_refresh", time=datetime.now().strftime('%H:%M')))

        active_maintenances = self._overview_data.get("active_maintenances", 0)
        self._card_maintenance.set_data(str(active_maintenances))

        self._on_period_changed()
        self._render_top_vehicles()

    def _on_period_changed(self, index=0):
        period_data = self._period_combo.currentData() or "week"
        if period_data == "today":
            self._current_period = "today"
            rev = self._overview_data.get("today_revenue", 0.0)
            locs = self._overview_data.get("day_locations", self._overview_data.get("locations", 0))
            self._card_day.set_title(t("dashboard.today_reservations"))
        elif period_data == "week":
            self._current_period = "week"
            rev = self._overview_data.get("week_revenue", self._overview_data.get("today_revenue", 0.0))
            locs = self._overview_data.get("week_locations", self._overview_data.get("day_locations", 0))
            self._card_day.set_title(t("dashboard.week_reservations"))
        elif period_data == "month":
            self._current_period = "month"
            rev = self._overview_data.get("month_revenue", self._overview_data.get("today_revenue", 0.0))
            locs = self._overview_data.get("month_locations", self._overview_data.get("day_locations", 0))
            self._card_day.set_title(t("dashboard.month_reservations"))
        else:
            self._current_period = "week"
            rev = 0.0
            locs = 0
            self._card_day.set_title(t("dashboard.reservations_default"))

        try:
            self._card_revenue.set_data(f"{float(rev):.2f} DH")
            self._card_day.set_data(str(locs))
        except Exception:
            self._card_revenue.set_data("0.00 DH")
            self._card_day.set_data("0")

        avail = self._overview_data.get("available", 0)
        rented = self._overview_data.get("rented", 0)
        reserved = self._overview_data.get("reserved", 0)
        maint = self._overview_data.get("maintenance", 0)
        total = avail + rented + reserved + maint

        self._card_available.set_count(str(avail))
        self._card_rented.set_count(str(rented), current=rented, total=total)
        self._card_reserved.set_count(str(reserved))
        self._card_fleet_maintenance.set_count(str(maint))

    def _render_top_vehicles(self):
        while self._top_layout.count():
            item = self._top_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._top_vehicles_data:
            empty_lbl = QLabel(t("dashboard.no_rentals"))
            empty_lbl.setFont(QFont("Hanken Grotesk", 10))
            empty_lbl.setStyleSheet("color: #6B7264;")
            self._top_layout.addWidget(empty_lbl)
        else:
            max_rentals = max([v.get("rental_count", 0) for v in self._top_vehicles_data]) if self._top_vehicles_data else 1
            max_rentals = max_rentals or 1

            from app.ui.theme import get_current_palette
            p = get_current_palette()
            ranks = [p["PRIMARY"], p["PRIMARY_HOVER"], p["SECONDARY"], p["TEXT_SECONDARY"], p["TEXT_TERTIARY"]]
            for i, v in enumerate(self._top_vehicles_data[:5]):
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(8, 6, 8, 6)

                rank_color = ranks[i] if i < len(ranks) else ranks[-1]
                rank_lbl = QLabel(f"#{i+1}")
                rank_lbl.setStyleSheet(f"color: {rank_color}; font-weight: bold;")
                rank_lbl.setFixedWidth(28)

                name_lbl = QLabel(f"{v.get('brand', '')} {v.get('model', '')} ({v.get('registration', '')})")
                name_lbl.setStyleSheet(f"color: {p['TEXT_PRIMARY']};")

                count_lbl = QLabel(f"{v.get('rental_count', 0)} {t('dashboard.rentals_unit')}")
                count_lbl.setStyleSheet(f"color: {p['TEXT_SECONDARY']};")

                bar = QFrame()
                bar.setStyleSheet(f"background-color: {rank_color}; border-radius: 2px;")
                width_pct = int((v.get("rental_count", 0) / max_rentals) * 100)
                bar.setFixedWidth(max(10, int(180 * width_pct / 100)))
                bar.setFixedHeight(4)

                h.addWidget(rank_lbl)
                h.addWidget(name_lbl, 2)
                h.addWidget(count_lbl, 1)
                h.addWidget(bar)
                h.addStretch()

                self._top_layout.addWidget(row)
