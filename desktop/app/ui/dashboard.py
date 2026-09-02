"""
Dashboard view — 1:1 Stitch ATELIER BERLIN LOCATION CAR Dashboard Overview.
Styled after Stitch Design with full French & Arabic localization support.
"""
from datetime import date, datetime, timedelta
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QGroupBox, QPushButton, QProgressBar, QComboBox,
    QScrollArea, QDateEdit
)
from PySide6.QtCore import Qt, QDate, QThread, Signal
from PySide6.QtGui import QFont
from app.i18n import t, is_rtl

# The 8 preset periods + custom. Names match shared/money_time.PERIOD_NAMES.
_REVENUE_PERIODS = (
    "today", "yesterday", "week", "last_week",
    "month", "last_month", "year", "last_year", "custom",
)


def _preset_date_bounds(name: str, today: date):
    """(from_date, to_date_inclusive) for a preset — mirrors
    shared.money_time.period_bounds (to made inclusive for the UI)."""
    if name == "today":
        return today, today
    if name == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if name == "week":
        s = today - timedelta(days=today.weekday())
        return s, s + timedelta(days=6)
    if name == "last_week":
        tw = today - timedelta(days=today.weekday())
        return tw - timedelta(days=7), tw - timedelta(days=1)
    if name == "month":
        s = today.replace(day=1)
        nm = date(s.year + 1, 1, 1) if s.month == 12 else date(s.year, s.month + 1, 1)
        return s, nm - timedelta(days=1)
    if name == "last_month":
        tm = today.replace(day=1)
        end = tm - timedelta(days=1)
        return end.replace(day=1), end
    if name == "year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    if name == "last_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    return today, today


class RevenueRangeWorker(QThread):
    """Fetches chiffre d'affaires for a date range off the UI thread.

    The provider (injected by MainWindow) tries the canonical backend
    endpoint first and falls back to the offline pro-rata computation over
    the DomainStore snapshot — so the number is ALWAYS the same rule.
    """
    done = Signal(float, str, int)  # (revenue, source, req_id)

    def __init__(self, provider, from_date: date, to_date: date, req_id: int, parent=None):
        super().__init__(parent)
        self._provider = provider
        self._from = from_date
        self._to = to_date
        self._req_id = req_id

    def run(self):
        try:
            rev, source = self._provider(self._from, self._to)
            self.done.emit(float(rev) if rev is not None else -1.0, source, self._req_id)
        except Exception:
            self.done.emit(-1.0, "error", self._req_id)


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
        self._current_period = "month"
        self._overview_data = {}
        self._top_vehicles_data = []
        self._revenue_provider = None      # set by MainWindow
        self._revenue_worker = None
        self._setup_ui()

    def set_revenue_provider(self, provider):
        """provider(from_date, to_date) -> (revenue: float|None, source: str).
        MainWindow injects one that hits the canonical backend endpoint and
        falls back to the offline pro-rata computation."""
        self._revenue_provider = provider

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        # The dashboard content (KPI rows, fleet cards, Top-5 list) can be taller
        # than a small / short window. Host it in a vertically-scrolling area so
        # nothing is clipped when the window is resized down. The FlowLayout rows
        # already reflow horizontally, so only vertical scroll is needed.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer.addWidget(self._scroll)

        content = QWidget()
        self._scroll.setWidget(content)

        layout = QVBoxLayout(content)
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
        # 1. Chiffre d'affaires — compact filter panel
        # ─────────────────────────────────────────────────────────────
        self._revenue_panel = self._build_revenue_panel()
        layout.addWidget(self._revenue_panel)

        from app.ui.widgets.flow_layout import FlowLayout
        
        perf_layout = FlowLayout()
        perf_layout.setContentsMargins(0, 0, 0, 0)
        perf_layout.m_hSpace = 14
        perf_layout.m_vSpace = 14

        # Revenue now lives in the dedicated panel above; these two stay.
        self._card_day = OperationalStatCard(t("dashboard.week_reservations"), "0")
        self._card_maintenance = OperationalStatCard(t("dashboard.active_maintenances"), "0")
        self._card_day.setMinimumWidth(240)
        self._card_maintenance.setMinimumWidth(240)

        perf_layout.addWidget(self._card_day)
        perf_layout.addWidget(self._card_maintenance)
        layout.addLayout(perf_layout)

        # ─────────────────────────────────────────────────────────────
        # 2. Fleet Status Row
        # ─────────────────────────────────────────────────────────────
        fleet_layout = FlowLayout()
        fleet_layout.setContentsMargins(0, 0, 0, 0)
        fleet_layout.m_hSpace = 14
        fleet_layout.m_vSpace = 14

        self._card_available = ExecutiveFleetCard(t("dashboard.available_fleet"), "0")
        # "Véhicules en location" shows ONLY the count of vehicles currently in
        # rental (canonical effective status RENTED) — no "/fleet" denominator,
        # no capacity ratio, no progress bar. It is a live business figure, not
        # a utilisation gauge.
        self._card_rented = ExecutiveFleetCard(t("dashboard.rented_fleet"), "0")
        self._card_reserved = ExecutiveFleetCard(t("dashboard.reserved_fleet"), "0")
        self._card_fleet_maintenance = ExecutiveFleetCard(t("dashboard.maintenance_fleet"), "0")

        self._card_available.setMinimumWidth(200)
        self._card_rented.setMinimumWidth(200)
        self._card_reserved.setMinimumWidth(200)
        self._card_fleet_maintenance.setMinimumWidth(200)

        fleet_layout.addWidget(self._card_available)
        fleet_layout.addWidget(self._card_rented)
        fleet_layout.addWidget(self._card_reserved)
        fleet_layout.addWidget(self._card_fleet_maintenance)
        layout.addLayout(fleet_layout)

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
        layout.addStretch()

    # ── Revenue panel ────────────────────────────────────────────────
    def _build_revenue_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("revenuePanel")
        panel.setProperty("card", "true")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        v = QVBoxLayout(panel)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(10)

        # Row 1: title + period combo (wraps on narrow windows via FlowLayout-free
        # simple HBox; the combo is small so this stays compact)
        top = QHBoxLayout()
        top.setSpacing(10)
        self._revenue_title_lbl = QLabel(t("dashboard.revenue"))
        self._revenue_title_lbl.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.Bold))
        self._revenue_title_lbl.setStyleSheet("color: #637060;")
        top.addWidget(self._revenue_title_lbl)
        top.addStretch()

        self._period_combo = QComboBox()
        self._period_combo.setMinimumContentsLength(14)
        for name in _REVENUE_PERIODS:
            self._period_combo.addItem(t(f"dashboard.rev_period_{name}"), name)
        self._period_combo.setCurrentIndex(_REVENUE_PERIODS.index("month"))
        self._period_combo.currentIndexChanged.connect(self._on_period_changed)
        top.addWidget(self._period_combo)
        v.addLayout(top)

        # Row 2: the big number
        self._revenue_value_lbl = QLabel("—")
        self._revenue_value_lbl.setFont(QFont("Hanken Grotesk", 26, QFont.Weight.Bold))
        self._revenue_value_lbl.setStyleSheet("color: #1A221A;")
        v.addWidget(self._revenue_value_lbl)

        # Row 3: custom Du / Au date pickers (hidden unless "Personnalisé")
        self._custom_row = QWidget()
        cr = QHBoxLayout(self._custom_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(8)
        self._from_lbl = QLabel(t("dashboard.rev_from"))
        self._from_lbl.setStyleSheet("color: #6B7264;")
        self._date_from = QDateEdit()
        self._date_from.setDisplayFormat("dd/MM/yyyy")
        self._date_from.setCalendarPopup(True)
        self._date_from.setDate(QDate.currentDate().addDays(-30))
        self._to_lbl = QLabel(t("dashboard.rev_to"))
        self._to_lbl.setStyleSheet("color: #6B7264;")
        self._date_to = QDateEdit()
        self._date_to.setDisplayFormat("dd/MM/yyyy")
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate.currentDate())
        self._date_from.dateChanged.connect(self._on_custom_dates_changed)
        self._date_to.dateChanged.connect(self._on_custom_dates_changed)
        for w in (self._from_lbl, self._date_from, self._to_lbl, self._date_to):
            cr.addWidget(w)
        cr.addStretch()
        self._custom_row.setVisible(False)
        v.addWidget(self._custom_row)

        # Row 4: effective range + last update + refresh
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self._range_lbl = QLabel("")
        self._range_lbl.setFont(QFont("Hanken Grotesk", 9))
        self._range_lbl.setStyleSheet("color: #909C8E;")
        foot.addWidget(self._range_lbl)
        foot.addStretch()
        self._rev_updated_lbl = QLabel("")
        self._rev_updated_lbl.setFont(QFont("Hanken Grotesk", 9))
        self._rev_updated_lbl.setStyleSheet("color: #909C8E;")
        foot.addWidget(self._rev_updated_lbl)
        self._rev_refresh_btn = QPushButton(t("dashboard.rev_refresh"))
        self._rev_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rev_refresh_btn.clicked.connect(self._request_revenue)
        foot.addWidget(self._rev_refresh_btn)
        v.addLayout(foot)
        return panel

    def _selected_range(self):
        """(from_date, to_date_inclusive) for the current selection."""
        name = self._period_combo.currentData() or "month"
        if name == "custom":
            f = self._date_from.date().toPython()
            t_ = self._date_to.date().toPython()
            return (f, t_) if f <= t_ else (t_, f)
        try:
            from zoneinfo import ZoneInfo
            today = datetime.now(ZoneInfo("Africa/Casablanca")).date()
        except Exception:
            today = date.today()
        return _preset_date_bounds(name, today)

    def _on_period_changed(self, *_):
        is_custom = (self._period_combo.currentData() == "custom")
        self._custom_row.setVisible(is_custom)
        self._render_reservations_card()
        self._request_revenue()

    def _on_custom_dates_changed(self, *_):
        if self._period_combo.currentData() == "custom":
            self._request_revenue()

    def _request_revenue(self):
        f, t_incl = self._selected_range()
        self._range_lbl.setText(
            t("dashboard.rev_range", frm=f.strftime("%d/%m/%Y"),
              to=t_incl.strftime("%d/%m/%Y"))
        )
        self._revenue_value_lbl.setText("…")
        if self._revenue_provider is None:
            return
        from PySide6.QtWidgets import QApplication
        self._revenue_req_id = getattr(self, "_revenue_req_id", 0) + 1
        # Parent to the QApplication (not this widget) so a widget teardown can
        # never destroy a still-running QThread; the bound-method connection is
        # auto-severed by Qt when this widget is destroyed.
        w = RevenueRangeWorker(
            self._revenue_provider, f, t_incl, self._revenue_req_id,
            parent=QApplication.instance(),
        )
        w.done.connect(self._on_revenue_done)
        w.finished.connect(w.deleteLater)
        self._revenue_worker = w
        w.start()

    def closeEvent(self, event):  # noqa: N802 (Qt override)
        w = getattr(self, "_revenue_worker", None)
        try:
            if w is not None and w.isRunning():
                w.wait(2000)
        except RuntimeError:
            pass
        super().closeEvent(event)

    def _on_revenue_done(self, revenue: float, source: str, req_id: int = 0):
        # Ignore results from a superseded request (rapid combo / date changes).
        if req_id and req_id != getattr(self, "_revenue_req_id", 0):
            return
        if revenue < 0 or source == "error":
            self._revenue_value_lbl.setText(t("dashboard.rev_unavailable"))
            self._rev_updated_lbl.setText("")
            return
        self._revenue_value_lbl.setText(f"{revenue:,.2f} DH".replace(",", " "))
        stamp = datetime.now().strftime("%H:%M:%S")
        key = "dashboard.rev_updated" if source == "server" else "dashboard.rev_updated_local"
        self._rev_updated_lbl.setText(t(key, time=stamp))

    def retranslate_ui(self):
        """Live update all strings when application language changes."""
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)
        self._title_lbl.setText(t("dashboard.title"))
        self._last_refresh_lbl.setText(t("dashboard.last_refresh", time=datetime.now().strftime('%H:%M')))

        self._revenue_title_lbl.setText(t("dashboard.revenue"))
        cur = self._period_combo.currentIndex()
        self._period_combo.blockSignals(True)
        self._period_combo.clear()
        for name in _REVENUE_PERIODS:
            self._period_combo.addItem(t(f"dashboard.rev_period_{name}"), name)
        self._period_combo.setCurrentIndex(max(0, cur))
        self._period_combo.blockSignals(False)
        self._from_lbl.setText(t("dashboard.rev_from"))
        self._to_lbl.setText(t("dashboard.rev_to"))
        self._rev_refresh_btn.setText(t("dashboard.rev_refresh"))

        self._card_day.set_title(t("dashboard.week_reservations"))
        self._card_maintenance.set_title(t("dashboard.active_maintenances"))
        self._card_available.set_title(t("dashboard.available_fleet"))
        self._card_rented.set_title(t("dashboard.rented_fleet"))
        self._card_reserved.set_title(t("dashboard.reserved_fleet"))
        self._card_fleet_maintenance.set_title(t("dashboard.maintenance_fleet"))
        self._top_box.setTitle(t("dashboard.top_rented"))

        self._render_fleet_cards()
        self._request_revenue()
        self._render_top_vehicles()

    def _set_period(self, period: str):
        self._current_period = period

    def refresh_data(self, overview: dict, top_vehicles: list = None,
                     request_revenue: bool = False):
        """Apply the fleet/maintenance figures + Top-5.

        Revenue is fetched independently by the panel. When ``request_revenue``
        is True the chiffre d'affaires is re-fetched for the current date
        range; otherwise the panel keeps its last known value. This avoids the
        "…" flicker that occurred when every domain fan-out (auto-sync,
        BoundaryClock, tab switch) unconditionally started a revenue worker.
        """
        self._overview_data = overview or {}
        self._top_vehicles_data = top_vehicles or []
        self._last_refresh_lbl.setText(t("dashboard.last_refresh", time=datetime.now().strftime('%H:%M')))

        maint = self._overview_data.get(
            "active_maintenance_tickets",
            self._overview_data.get("active_maintenances",
                                    self._overview_data.get("maintenance", 0)),
        )
        self._card_maintenance.set_data(str(maint))
        # "réservations" card follows the revenue period selection
        self._render_reservations_card()
        self._render_fleet_cards()
        if request_revenue:
            self._request_revenue()
        self._render_top_vehicles()

    def _render_reservations_card(self):
        name = self._period_combo.currentData() or "month"
        key = {"today": "today", "week": "week", "month": "month",
               "year": "year"}.get(name)
        if key:
            locs = self._overview_data.get(
                f"{key}_rentals", self._overview_data.get(f"{key}_locations", 0))
            self._card_day.set_title(t(f"dashboard.{key}_reservations"))
        else:
            locs = "—"
            self._card_day.set_title(t("dashboard.reservations_default"))
        self._card_day.set_data(str(locs))

    def _render_fleet_cards(self):
        d = self._overview_data
        self._card_available.set_count(str(d.get("available", 0)))
        self._card_rented.set_count(str(d.get("rented", 0)))
        self._card_reserved.set_count(str(d.get("reserved", 0)))
        self._card_fleet_maintenance.set_count(str(d.get("maintenance", 0)))

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
