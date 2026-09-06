"""
Dashboard — rebuilt 2026-09-05 on ONE authoritative snapshot.

DATA CONTRACT
-------------
This widget renders EXCLUSIVELY from a single canonical DTO
(``shared/dashboard_reference.build_snapshot``): revenue, réservations du
jour, maintenances en cours, the four fleet buckets and the Top-5 all come
from one payload generated against one ``now`` on one database read. The
widget performs NO business arithmetic of its own — it formats numbers it was
given. That is what makes two cards structurally unable to disagree.

Two adapters feed ``_dto``:

  ``apply_snapshot(dto)``      the real path — server DTO, or the offline port
                               over the DomainStore (stamped source="local").
  ``refresh_data(overview,…)`` legacy flat-overview adapter, kept for the
                               existing regression suite and the temporal
                               (BoundaryClock) path. A pure key mapping — it
                               computes nothing.

NEVER A FAKE ZERO
-----------------
``apply_unavailable(reason)`` is called when the dashboard cannot be obtained.
Every figure then shows "—" and a red banner explains why. An unreachable API
is NOT zero revenue and NOT an empty fleet; rendering 0 in that case is the
single most dangerous thing this screen can do, so there is no code path that
turns a fetch failure into a number.

RESPONSIVE LAYOUT
-----------------
No fixed pixel positions and no oversized minimum widths. The page lives in a
vertical QScrollArea; the KPI and fleet rows use ``ResponsiveGrid``, which
derives its column count from the width actually available and stretches the
cards to fill it. Long labels elide with a tooltip rather than forcing the row
wider than the viewport. Verified at 1280x720, 1366x768, 1600x900 and
1920x1080 by ``desktop/tests/test_dashboard_responsive.py``.
"""
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QDate, QThread, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGroupBox, QPushButton,
    QComboBox, QScrollArea, QDateEdit, QSizePolicy, QApplication,
)

from app.i18n import t, is_rtl
from app.ui.widgets.flow_layout import FlowLayout
from app.ui.widgets.responsive_grid import ResponsiveGrid

# The 8 preset periods + custom. Names match shared/money_time.PERIOD_NAMES.
_REVENUE_PERIODS = (
    "today", "yesterday", "week", "last_week",
    "month", "last_month", "year", "last_year", "custom",
)

# Shown wherever a value is genuinely UNKNOWN (never for a real zero).
UNKNOWN = "—"

_BUSINESS_TZ_NAME = "Africa/Casablanca"


def _business_today() -> date:
    """Today in the business timezone — never the OS timezone.

    The period presets must agree with the server's Africa/Casablanca day
    boundaries; deriving them from ``date.today()`` on a machine in another
    zone silently asks the backend for the wrong day.
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(_BUSINESS_TZ_NAME)).date()
    except Exception:
        return date.today()


def _preset_date_bounds(name: str, today: date):
    """(from_date, to_date_INCLUSIVE) for a preset — mirrors
    shared.money_time.period_bounds with the end made inclusive, which is the
    form the operator sees ("Du 01/09 au 30/09") and the form the API's
    ``to=`` parameter takes."""
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


def _fmt_money(value, currency: str = "DH") -> str:
    """1234567.5 -> '1 234 567.50 DH' (thin-space groups, French convention)."""
    return f"{float(value):,.2f} {currency}".replace(",", " ")


def _fmt_int(value) -> str:
    return str(int(value))


# ── small responsive building blocks ─────────────────────────────────────


class ElidedLabel(QLabel):
    """A single-line label that shortens with "…" instead of forcing its row
    wider than the viewport. The full text is always available as a tooltip,
    so nothing is ever lost — only visually abbreviated at extreme widths."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setMinimumWidth(24)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text: str):  # noqa: N802 (Qt override)
        self._full = text or ""
        self.setToolTip(self._full)
        self._apply_elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self):
        fm = QFontMetrics(self.font())
        width = max(0, self.width() - 2)
        if width <= 0:
            super().setText(self._full)
            return
        super().setText(fm.elidedText(self._full, Qt.TextElideMode.ElideRight, width))


class RankBar(QWidget):
    """A proportional bar that fills whatever width it is given.

    The previous implementation used ``setFixedWidth(180 * pct / 100)``, an
    absolute pixel size that overflowed narrow windows and left dead space in
    wide ones. This paints across its own geometry instead, so it is correct
    at every resolution with no arithmetic on the caller's side.
    """

    def __init__(self, ratio: float = 0.0, color: str = "#1E4D38", parent=None):
        super().__init__(parent)
        self._ratio = max(0.0, min(1.0, float(ratio)))
        self._color = color
        self.setFixedHeight(6)
        self.setMinimumWidth(30)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_ratio(self, ratio: float, color: str = None):
        self._ratio = max(0.0, min(1.0, float(ratio)))
        if color:
            self._color = color
        self.update()

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        h = self.height()
        p.setBrush(QColor("#E2E6DC"))
        p.drawRoundedRect(0, 0, self.width(), h, h / 2, h / 2)
        w = int(self.width() * self._ratio)
        if w > 0:
            p.setBrush(QColor(self._color))
            p.drawRoundedRect(0, 0, max(w, h), h, h / 2, h / 2)
        p.end()


class StatCard(QFrame):
    """One KPI tile: a title, a big value, an optional footnote.

    Sized by the layout, never by itself: a small minimum width plus an
    Expanding horizontal policy lets ``ResponsiveGrid`` give it exactly the
    share of the row that fits, at any window size.
    """

    def __init__(self, title: str, value: str = UNKNOWN, footnote: str = "",
                 accent: str = "#1A221A", parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setProperty("card", "true")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(104)
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)

        self._title_lbl = ElidedLabel(title)
        self._title_lbl.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Medium))
        self._title_lbl.setStyleSheet("color: #637060;")
        lay.addWidget(self._title_lbl)

        # `_count_lbl` keeps its historical name: the regression suite reads it.
        self._count_lbl = ElidedLabel(value)
        self._count_lbl.setFont(QFont("Hanken Grotesk", 24, QFont.Weight.Bold))
        self._count_lbl.setStyleSheet(f"color: {accent};")
        lay.addWidget(self._count_lbl)

        self._foot_lbl = ElidedLabel(footnote)
        self._foot_lbl.setFont(QFont("Hanken Grotesk", 9))
        self._foot_lbl.setStyleSheet("color: #909C8E;")
        self._foot_lbl.setVisible(bool(footnote))
        lay.addWidget(self._foot_lbl)
        lay.addStretch()

    def set_title(self, title: str):
        self._title_lbl.setText(title)

    def set_value(self, value: str, footnote: str = None):
        self._count_lbl.setText(value)
        if footnote is not None:
            self._foot_lbl.setText(footnote)
            self._foot_lbl.setVisible(bool(footnote))

    # Historical aliases used across the existing regression suite.
    def set_data(self, value: str):
        self.set_value(value)

    def set_count(self, value: str, current: int = 0, total: int = 0):
        self.set_value(value)

    def value_text(self) -> str:
        return self._count_lbl.full_text()


# ── worker ───────────────────────────────────────────────────────────────


class SnapshotWorker(QThread):
    """Fetches ONE dashboard snapshot off the UI thread.

    ``done`` carries (dto, error, req_id): exactly one of dto/error is set.
    A superseded request is discarded by ``req_id`` so a slow earlier reply
    can never overwrite a newer one.
    """
    done = Signal(object, str, int)

    def __init__(self, provider, period: str, from_date: date, to_date: date,
                 req_id: int, parent=None):
        super().__init__(parent)
        self._provider = provider
        self._period = period
        self._from = from_date
        self._to = to_date
        self._req_id = req_id

    def run(self):
        try:
            dto = self._provider(self._period, self._from, self._to)
            if dto:
                self.done.emit(dto, "", self._req_id)
            else:
                self.done.emit(None, "unavailable", self._req_id)
        except Exception as e:  # noqa: BLE001 — surfaced to the operator
            self.done.emit(None, str(e) or e.__class__.__name__, self._req_id)


class RevenueRangeWorker(QThread):
    """Legacy revenue-only worker, retained for the flat-overview adapter and
    the existing regression suite. The rebuilt path fetches revenue inside the
    single snapshot instead."""
    done = Signal(float, str, int)

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


# Legacy aliases — older modules/tests import these names.
OperationalStatCard = StatCard
ExecutiveFleetCard = StatCard


# ── the dashboard ────────────────────────────────────────────────────────


class DashboardWidget(QWidget):
    """The Dashboard. One snapshot in, every card out."""

    #: minimum width at which a KPI card is still readable
    KPI_MIN_WIDTH = 240
    #: minimum width at which a fleet card is still readable
    FLEET_MIN_WIDTH = 190

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dto = None                 # the ONE canonical payload
        self._overview_data = {}         # legacy flat projection (regression suite)
        self._top_vehicles_data = []
        self._snapshot_provider = None
        self._revenue_provider = None
        self._snapshot_worker = None
        self._revenue_worker = None
        self._snapshot_req_id = 0
        self._revenue_req_id = 0
        self._is_live_data = True
        self._is_live_revenue = False
        self._setup_ui()

    # ── providers ────────────────────────────────────────────────────────
    def set_snapshot_provider(self, provider):
        """provider(period, from_date, to_date_inclusive) -> DTO dict.

        Returns the canonical snapshot, or None / raises when it cannot be
        obtained — which becomes the explicit "données indisponibles" state,
        never a zero.
        """
        self._snapshot_provider = provider

    def set_revenue_provider(self, provider):
        """Legacy: provider(from_date, to_date) -> (revenue|None, source)."""
        self._revenue_provider = provider

    # ── construction ─────────────────────────────────────────────────────
    def _setup_ui(self):
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight
        )
        # The window can legitimately be narrower than the content is wide;
        # a small minimum here is what keeps the shell from being forced past
        # the screen edge (the root cause of the clipped-sidebar screenshot).
        self.setMinimumWidth(320)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Horizontal scrolling stays OFF: every row reflows, so needing it
        # would be a layout bug rather than a legitimate state.
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer.addWidget(self._scroll)

        content = QWidget()
        content.setMinimumWidth(300)
        self._scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(16)

        # ── header (wraps on narrow windows) ────────────────────────────
        header = FlowLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.m_hSpace = 12
        header.m_vSpace = 6
        self._title_lbl = QLabel(t("dashboard.title"))
        self._title_lbl.setFont(QFont("Libre Caslon Text", 19, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet("color: #1E4D38;")
        header.addWidget(self._title_lbl)

        self._last_refresh_lbl = QLabel(
            t("dashboard.last_refresh", time=datetime.now().strftime("%H:%M"))
        )
        self._last_refresh_lbl.setFont(QFont("Hanken Grotesk", 10))
        self._last_refresh_lbl.setStyleSheet("color: #6B7264;")
        header.addWidget(self._last_refresh_lbl)
        layout.addLayout(header)

        # ── status banner (hidden unless offline / error / integrity) ───
        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.DemiBold))
        self._banner.setContentsMargins(12, 8, 12, 8)
        self._banner.setVisible(False)
        layout.addWidget(self._banner)

        # ── 1. Chiffre d'affaires ───────────────────────────────────────
        self._revenue_panel = self._build_revenue_panel()
        layout.addWidget(self._revenue_panel)

        # ── 2. KPI row ──────────────────────────────────────────────────
        self._kpi_grid = ResponsiveGrid(min_item_width=self.KPI_MIN_WIDTH,
                                        h_spacing=14, v_spacing=14)
        self._card_day = StatCard(t("dashboard.today_reservations"), UNKNOWN)
        self._card_maintenance = StatCard(t("dashboard.active_maintenances"), UNKNOWN)
        self._kpi_grid.addWidget(self._card_day)
        self._kpi_grid.addWidget(self._card_maintenance)
        layout.addLayout(self._kpi_grid)

        # ── 3. Fleet row — the three operational buckets ────────────────
        self._fleet_grid = ResponsiveGrid(min_item_width=self.FLEET_MIN_WIDTH,
                                          h_spacing=14, v_spacing=14)
        self._card_available = StatCard(t("dashboard.available_fleet"), UNKNOWN)
        self._card_rented = StatCard(t("dashboard.rented_fleet"), UNKNOWN)
        self._card_fleet_maintenance = StatCard(t("dashboard.maintenance_fleet"), UNKNOWN)
        for c in (self._card_available, self._card_rented, self._card_fleet_maintenance):
            self._fleet_grid.addWidget(c)
        layout.addLayout(self._fleet_grid)

        self._fleet_total_lbl = QLabel("")
        self._fleet_total_lbl.setFont(QFont("Hanken Grotesk", 9))
        self._fleet_total_lbl.setStyleSheet("color: #909C8E;")
        self._fleet_total_lbl.setWordWrap(True)
        layout.addWidget(self._fleet_total_lbl)

        # ── 4. Top 5 ────────────────────────────────────────────────────
        self._top_box = QGroupBox(t("dashboard.top_rented"))
        self._top_box.setFont(QFont("Hanken Grotesk", 12, QFont.Weight.Bold))
        self._top_box.setSizePolicy(QSizePolicy.Policy.Preferred,
                                    QSizePolicy.Policy.Preferred)
        top_layout = QVBoxLayout(self._top_box)
        top_layout.setContentsMargins(14, 14, 14, 14)
        self._top_container = QWidget()
        self._top_layout = QVBoxLayout(self._top_container)
        self._top_layout.setContentsMargins(0, 0, 0, 0)
        self._top_layout.setSpacing(4)
        top_layout.addWidget(self._top_container)
        layout.addWidget(self._top_box)
        layout.addStretch()

        self._render_top_vehicles()

    def _build_revenue_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("revenuePanel")
        panel.setProperty("card", "true")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        v = QVBoxLayout(panel)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(8)

        # Row 1: title + period selector (wraps when narrow)
        top = FlowLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.m_hSpace = 10
        top.m_vSpace = 6
        self._revenue_title_lbl = QLabel(t("dashboard.revenue"))
        self._revenue_title_lbl.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.Bold))
        self._revenue_title_lbl.setStyleSheet("color: #637060;")
        top.addWidget(self._revenue_title_lbl)

        self._period_combo = QComboBox()
        self._period_combo.setMinimumContentsLength(12)
        self._period_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        for name in _REVENUE_PERIODS:
            self._period_combo.addItem(t(f"dashboard.rev_period_{name}"), name)
        self._period_combo.setCurrentIndex(_REVENUE_PERIODS.index("month"))
        self._period_combo.currentIndexChanged.connect(self._on_period_changed)
        top.addWidget(self._period_combo)
        v.addLayout(top)

        # Row 2: the number
        self._revenue_value_lbl = ElidedLabel(UNKNOWN)
        self._revenue_value_lbl.setFont(QFont("Hanken Grotesk", 26, QFont.Weight.Bold))
        self._revenue_value_lbl.setStyleSheet("color: #1A221A;")
        v.addWidget(self._revenue_value_lbl)

        # Row 3: custom Du / Au pickers (only for "Personnalisé")
        self._custom_row = QWidget()
        cr = FlowLayout()
        cr.setContentsMargins(0, 0, 0, 0)
        cr.m_hSpace = 8
        cr.m_vSpace = 6
        self._custom_row.setLayout(cr)
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
        self._custom_row.setVisible(False)
        v.addWidget(self._custom_row)

        # Row 4: effective range, freshness, refresh (wraps when narrow)
        foot = FlowLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.m_hSpace = 10
        foot.m_vSpace = 6
        self._range_lbl = QLabel("")
        self._range_lbl.setFont(QFont("Hanken Grotesk", 9))
        self._range_lbl.setStyleSheet("color: #909C8E;")
        foot.addWidget(self._range_lbl)
        self._rev_updated_lbl = QLabel("")
        self._rev_updated_lbl.setFont(QFont("Hanken Grotesk", 9))
        self._rev_updated_lbl.setStyleSheet("color: #909C8E;")
        foot.addWidget(self._rev_updated_lbl)
        self._rev_refresh_btn = QPushButton(t("dashboard.rev_refresh"))
        self._rev_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rev_refresh_btn.clicked.connect(self.request_snapshot)
        foot.addWidget(self._rev_refresh_btn)
        v.addLayout(foot)
        return panel

    # ── period selection ─────────────────────────────────────────────────
    def current_period(self) -> str:
        return self._period_combo.currentData() or "month"

    def selected_range(self):
        """(from_date, to_date_INCLUSIVE) for the current selection."""
        name = self.current_period()
        if name == "custom":
            f = self._date_from.date().toPython()
            t_ = self._date_to.date().toPython()
            return (f, t_) if f <= t_ else (t_, f)
        return _preset_date_bounds(name, _business_today())

    # Historical name kept for the existing suite.
    def _selected_range(self):
        return self.selected_range()

    def _on_period_changed(self, *_):
        """A period change re-fetches the WHOLE snapshot.

        Only the revenue window actually moves, but re-requesting the entire
        DTO keeps every card on one snapshot; patching the revenue label alone
        is how the screen used to end up mixing two different instants.
        """
        self._custom_row.setVisible(self.current_period() == "custom")
        self._update_range_label()
        self.request_snapshot()

    def _on_custom_dates_changed(self, *_):
        if self.current_period() == "custom":
            self._update_range_label()
            self.request_snapshot()

    def _update_range_label(self):
        f, t_incl = self.selected_range()
        self._range_lbl.setText(
            t("dashboard.rev_range", frm=f.strftime("%d/%m/%Y"),
              to=t_incl.strftime("%d/%m/%Y"))
        )

    # ── fetching ─────────────────────────────────────────────────────────
    def request_snapshot(self):
        """Ask the provider for a fresh snapshot for the current selection."""
        self._update_range_label()
        if self._snapshot_provider is None:
            # Legacy wiring (revenue-only provider): keep that path alive.
            self._request_revenue()
            return
        f, t_incl = self.selected_range()
        self._snapshot_req_id += 1
        req_id = self._snapshot_req_id
        w = SnapshotWorker(self._snapshot_provider, self.current_period(),
                           f, t_incl, req_id, parent=QApplication.instance())
        w.done.connect(self._on_snapshot_done)
        w.finished.connect(w.deleteLater)
        self._snapshot_worker = w
        w.start()

    def _on_snapshot_done(self, dto, error: str, req_id: int):
        if req_id and req_id != self._snapshot_req_id:
            return  # superseded by a newer request
        if dto:
            if (dto.get("source") or "server") != "server" and self._is_live_data:
                # A cache snapshot that was already in flight must not land on
                # top of live server data that arrived while it was travelling.
                # The local mirror is never allowed to downgrade the server.
                return
            self.apply_snapshot(dto)
        elif self._dto is not None or self._overview_data:
            # A failed REFRESH must not destroy figures we already have. The
            # numbers on screen stay (they were true when fetched); the banner
            # says the latest attempt failed. Blanking here would punish the
            # operator for a network blip.
            self.mark_stale(error or "unavailable")
        else:
            self.apply_unavailable(error or "unavailable")

    def mark_stale(self, reason: str = ""):
        """Keep the displayed figures, flag that they could not be refreshed."""
        self._show_banner(t("dashboard.banner_stale", reason=reason or "?"), level="warn")

    # ── rendering — the ONE path ─────────────────────────────────────────
    def apply_snapshot(self, dto: dict):
        """Render every card from ONE canonical DTO."""
        if not dto:
            self.apply_unavailable("empty snapshot")
            return
        self._dto = dto
        is_live = (dto.get("source") or "server") == "server"
        self._is_live_data = is_live
        self._overview_data = self._legacy_projection(dto)
        self._top_vehicles_data = [
            {
                "vehicle_id": v.get("vehicle_id"),
                "registration": v.get("registration", ""),
                "brand": v.get("brand", ""),
                "model": v.get("model", ""),
                "rental_count": v.get("rental_count", 0),
                "total_revenue": v.get("revenue", 0.0),
            }
            for v in (dto.get("top_vehicles") or [])
        ]

        rev = dto.get("revenue") or {}
        currency = "DH" if (rev.get("currency") or "MAD") == "MAD" else rev.get("currency")
        self._revenue_value_lbl.setText(_fmt_money(rev.get("amount", 0.0), currency))
        self._is_live_revenue = is_live
        self._range_lbl.setText(
            t("dashboard.rev_range",
              frm=_fmt_iso_date(rev.get("period_start")),
              to=_fmt_iso_date(rev.get("period_end_inclusive")))
        )

        today = dto.get("reservations_today") or {}
        self._card_day.set_title(t("dashboard.today_reservations"))
        self._card_day.set_value(
            _fmt_int(today.get("count", 0)),
            t("dashboard.reservations_footnote",
              ending=today.get("ending_today", 0),
              in_progress=today.get("in_progress", 0)),
        )

        maint = dto.get("maintenance") or {}
        self._card_maintenance.set_value(
            _fmt_int(maint.get("active_tickets", 0)),
            t("dashboard.maintenance_footnote",
              vehicles=maint.get("vehicles_in_maintenance", 0)),
        )

        self._render_fleet_cards()
        self._render_top_vehicles()
        self._render_status(dto)

    def apply_unavailable(self, reason: str = ""):
        """The dashboard could not be obtained.

        Every figure becomes "—" and the banner says why. This is deliberately
        NOT a zero: an unreachable API is not an empty agency, and showing 0 DH
        of revenue because a request timed out is a business-critical lie.
        """
        self._dto = None
        self._overview_data = {}
        self._top_vehicles_data = []
        self._is_live_data = False
        self._is_live_revenue = False
        self._revenue_value_lbl.setText(t("dashboard.rev_unavailable"))
        for card in (self._card_day, self._card_maintenance, self._card_available,
                     self._card_rented, self._card_fleet_maintenance):
            card.set_value(UNKNOWN, "")
        self._fleet_total_lbl.setText("")
        self._render_top_vehicles(unavailable=True)
        self._rev_updated_lbl.setText("")
        self._show_banner(
            t("dashboard.banner_unavailable", reason=reason or "?"), level="error"
        )
        self._last_refresh_lbl.setText(
            f"{t('dashboard.last_refresh', time=datetime.now().strftime('%H:%M'))} "
            f"({t('dashboard.state_unavailable')})"
        )
        self._last_refresh_lbl.setStyleSheet("color: #DC2626; font-weight: 600;")

    def _render_status(self, dto: dict):
        stamp = _fmt_iso_time(dto.get("generated_at")) or datetime.now().strftime("%H:%M:%S")
        base = t("dashboard.last_refresh", time=stamp)
        if self._is_live_data:
            self._last_refresh_lbl.setText(f"{base} ({t('dashboard.state_live')})")
            self._last_refresh_lbl.setStyleSheet("color: #1E4D38; font-weight: 500;")
            self._rev_updated_lbl.setText(t("dashboard.rev_updated", time=stamp))
            self._rev_updated_lbl.setStyleSheet("color: #909C8E;")
        else:
            self._last_refresh_lbl.setText(f"{base} ({t('dashboard.state_unavailable')})")
            self._last_refresh_lbl.setStyleSheet("color: #DC2626; font-weight: 600;")
            self._rev_updated_lbl.setText("")

        integrity = dto.get("integrity") or {}
        if integrity and not integrity.get("ok", True):
            self._show_banner(
                t("dashboard.banner_integrity",
                  detail="; ".join(integrity.get("violations", []))[:300]),
                level="error",
            )
        elif not self._is_live_data:
            self._show_banner(t("dashboard.banner_unavailable", reason="Serveur indisponible"), level="error")
        else:
            self._hide_banner()

    def _show_banner(self, text: str, level: str = "warn"):
        colors = {
            "error": ("#FEF2F2", "#DC2626"),
            "warn": ("#FFFBEB", "#B45309"),
        }
        bg, fg = colors.get(level, colors["warn"])
        self._banner.setText(text)
        self._banner.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border-radius: 8px;"
        )
        self._banner.setVisible(True)

    def _hide_banner(self):
        self._banner.setVisible(False)
        self._banner.setText("")

    def _render_fleet_cards(self):
        """The four buckets, plus the reconciliation line under them.

        A missing key renders "—", never 0 — the four categories are a
        partition of the fleet and an absent one means "unknown", which is
        information the operator needs rather than a fabricated zero.
        """
        d = self._overview_data

        def show(key):
            val = d.get(key)
            return UNKNOWN if val is None else _fmt_int(val)

        self._card_available.set_value(show("available"))
        self._card_rented.set_value(show("rented"))
        self._card_fleet_maintenance.set_value(show("maintenance"))

        parts = [d.get(k) for k in ("available", "rented", "maintenance")]
        total = d.get("total_vehicles")
        if total is not None and all(p is not None for p in parts):
            self._fleet_total_lbl.setText(
                t("dashboard.fleet_reconciliation",
                  ready=parts[0], rented=parts[1],
                  maintenance=parts[2], total=total)
            )
        else:
            self._fleet_total_lbl.setText("")

    def _render_top_vehicles(self, unavailable: bool = False):
        while self._top_layout.count():
            item = self._top_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if unavailable:
            self._top_layout.addWidget(self._muted_label(t("dashboard.rev_unavailable")))
            return
        if not self._top_vehicles_data:
            self._top_layout.addWidget(self._muted_label(t("dashboard.no_rentals")))
            return

        from app.ui.theme import get_current_palette
        p = get_current_palette()
        ranks = [p["PRIMARY"], p["PRIMARY_HOVER"], p["SECONDARY"],
                 p["TEXT_SECONDARY"], p["TEXT_TERTIARY"]]
        max_rentals = max(v.get("rental_count", 0) for v in self._top_vehicles_data) or 1

        for i, v in enumerate(self._top_vehicles_data[:5]):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(6, 4, 6, 4)
            h.setSpacing(10)
            color = ranks[i] if i < len(ranks) else ranks[-1]

            rank_lbl = QLabel(f"#{i + 1}")
            rank_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")
            rank_lbl.setFixedWidth(26)
            h.addWidget(rank_lbl)

            name = " ".join(x for x in (v.get("brand", ""), v.get("model", "")) if x)
            reg = v.get("registration", "")
            name_lbl = ElidedLabel(f"{name} ({reg})" if reg else name or UNKNOWN)
            name_lbl.setStyleSheet(f"color: {p['TEXT_PRIMARY']};")
            h.addWidget(name_lbl, 4)

            rev = float(v.get("total_revenue", 0.0) or 0.0)
            count = v.get("rental_count", 0)
            text = f"{count} {t('dashboard.rentals_unit')}"
            if rev > 0:
                text += f" • {rev:,.0f} DH".replace(",", " ")
            count_lbl = ElidedLabel(text)
            count_lbl.setStyleSheet(f"color: {p['TEXT_SECONDARY']};")
            h.addWidget(count_lbl, 3)

            h.addWidget(RankBar(count / max_rentals, color), 3)
            self._top_layout.addWidget(row)

    def _muted_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Hanken Grotesk", 10))
        lbl.setStyleSheet("color: #6B7264;")
        lbl.setWordWrap(True)
        return lbl

    # ── legacy adapter (flat overview) ───────────────────────────────────
    def refresh_data(self, overview: dict, top_vehicles: list = None,
                     request_revenue: bool = False, is_live: bool = True):
        """Render from the legacy flat overview shape.

        A pure key mapping onto the same render path — it computes nothing.
        Retained for the BoundaryClock/DomainStore temporal path and the
        existing regression suite; the primary path is ``apply_snapshot``.
        """
        self._overview_data = dict(overview or {})
        self._top_vehicles_data = list(top_vehicles or [])
        self._is_live_data = is_live

        stamp = datetime.now().strftime("%H:%M")
        base = t("dashboard.last_refresh", time=stamp)
        if is_live:
            self._last_refresh_lbl.setText(f"{base} ({t('dashboard.state_live')})")
            self._last_refresh_lbl.setStyleSheet("color: #1E4D38; font-weight: 500;")
            self._hide_banner()
        else:
            self._last_refresh_lbl.setText(f"{base} ({t('dashboard.state_cached')})")
            self._last_refresh_lbl.setStyleSheet("color: #909C8E;")
            self._show_banner(t("dashboard.banner_offline"), level="warn")

        maint = self._overview_data.get(
            "active_maintenance_tickets",
            self._overview_data.get(
                "active_maintenances", self._overview_data.get("maintenance")),
        )
        self._card_maintenance.set_value(
            UNKNOWN if maint is None else _fmt_int(maint), ""
        )
        self._render_reservations_card()
        self._render_fleet_cards()

        name = self.current_period()
        rev_key = f"{name}_revenue"
        if is_live and self._overview_data.get(rev_key) is not None:
            self._revenue_value_lbl.setText(_fmt_money(self._overview_data[rev_key]))
            self._is_live_revenue = True
            self._rev_updated_lbl.setText(
                t("dashboard.rev_updated", time=datetime.now().strftime("%H:%M:%S"))
            )
            self._rev_updated_lbl.setStyleSheet("color: #909C8E;")

        if request_revenue:
            self._request_revenue()
        self._render_top_vehicles()

    def _render_reservations_card(self):
        """Legacy path only: the flat overview carries per-period rental counts
        rather than a canonical "today" figure, so the card follows the
        selected period there. ``apply_snapshot`` always shows TODAY."""
        name = self.current_period()
        key = {"today": "today", "week": "week",
               "month": "month", "year": "year"}.get(name)
        if key:
            value = self._overview_data.get(
                f"{key}_rentals", self._overview_data.get(f"{key}_locations"))
            self._card_day.set_title(t(f"dashboard.{key}_reservations"))
        else:
            value = None
            self._card_day.set_title(t("dashboard.reservations_default"))
        self._card_day.set_value(UNKNOWN if value is None else _fmt_int(value), "")

    def _legacy_projection(self, dto: dict) -> dict:
        """DTO -> the flat overview keys the rest of the desktop still reads."""
        v = dto.get("vehicles") or {}
        rev = dto.get("revenue") or {}
        today = dto.get("reservations_today") or {}
        maint = dto.get("maintenance") or {}
        out = {
            "total_vehicles": v.get("total"),
            "available": v.get("ready_to_rent"),
            "rented": v.get("active_rental"),
            "maintenance": v.get("maintenance"),
            "reserved": v.get("reserved", 0),
            "active_maintenance_tickets": maint.get("active_tickets"),
            "active_maintenances": maint.get("active_tickets"),
            "active_rentals": today.get("in_progress"),
            "today_rentals": today.get("starting_today"),
            "today_returns": today.get("ending_today"),
        }
        # The four standing windows travel inside the SAME snapshot, so the
        # flat keys are a projection, not a second fetch.
        for name, block in (dto.get("periods") or {}).items():
            out[f"{name}_revenue"] = block.get("revenue")
            out[f"{name}_rentals"] = block.get("rentals")
        period = rev.get("period")
        if period and period != "custom":
            out[f"{period}_revenue"] = rev.get("amount")
            out[f"{period}_rentals"] = rev.get("rentals")
        return out

    # ── legacy revenue-only path ─────────────────────────────────────────
    def _request_revenue(self):
        self._update_range_label()
        if self._revenue_provider is None:
            return
        f, t_incl = self.selected_range()
        self._revenue_req_id += 1
        req_id = self._revenue_req_id
        self._revenue_request_date = f
        w = RevenueRangeWorker(self._revenue_provider, f, t_incl, req_id,
                               parent=QApplication.instance())
        w.done.connect(self._on_revenue_done)
        w.finished.connect(w.deleteLater)
        self._revenue_worker = w
        w.start()

    def _on_revenue_done(self, revenue: float, source: str, req_id: int = 0):
        if req_id and req_id != self._revenue_req_id:
            return
        if source == "local" and self._is_live_revenue:
            return
        if revenue < 0 or source == "error":
            self._revenue_value_lbl.setText(t("dashboard.rev_unavailable"))
            self._rev_updated_lbl.setText("")
            return
        self._revenue_value_lbl.setText(_fmt_money(revenue))
        stamp = datetime.now().strftime("%H:%M:%S")
        if source == "server":
            self._is_live_revenue = True
            self._rev_updated_lbl.setText(t("dashboard.rev_updated", time=stamp))
            self._rev_updated_lbl.setStyleSheet("color: #909C8E;")
        elif source == "mismatch":
            self._is_live_revenue = False
            self._rev_updated_lbl.setText(t("dashboard.rev_mismatch", time=stamp))
            self._rev_updated_lbl.setStyleSheet("color: #DC2626; font-weight: bold;")
        else:
            self._is_live_revenue = False
            self._rev_updated_lbl.setText(t("dashboard.rev_updated_local", time=stamp))
            self._rev_updated_lbl.setStyleSheet("color: #909C8E;")

    # ── lifecycle / i18n ─────────────────────────────────────────────────
    def closeEvent(self, event):  # noqa: N802 (Qt override)
        for attr in ("_snapshot_worker", "_revenue_worker"):
            w = getattr(self, attr, None)
            try:
                if w is not None and w.isRunning():
                    w.wait(2000)
            except RuntimeError:
                pass
        super().closeEvent(event)

    def retranslate_ui(self):
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight
        )
        self._title_lbl.setText(t("dashboard.title"))
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
        self._card_day.set_title(t("dashboard.today_reservations"))
        self._card_maintenance.set_title(t("dashboard.active_maintenances"))
        self._card_available.set_title(t("dashboard.available_fleet"))
        self._card_rented.set_title(t("dashboard.rented_fleet"))
        self._card_fleet_maintenance.set_title(t("dashboard.maintenance_fleet"))
        self._top_box.setTitle(t("dashboard.top_rented"))

        if self._dto is not None:
            self.apply_snapshot(self._dto)
        else:
            self._render_fleet_cards()
            self._render_top_vehicles()
            self._update_range_label()

    # Retained for callers that used to force a period programmatically.
    def _set_period(self, period: str):
        for i in range(self._period_combo.count()):
            if self._period_combo.itemData(i) == period:
                self._period_combo.setCurrentIndex(i)
                return


def _fmt_iso_date(value) -> str:
    """'2026-09-01' -> '01/09/2026' (the ONE display format)."""
    if not value:
        return ""
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def _fmt_iso_time(value) -> str:
    """An ISO instant -> 'HH:MM:SS' — the SERVER's snapshot time, so
    "Mis à jour à" reports when the data was generated, not when this process
    happened to repaint."""
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value)).strftime("%H:%M:%S")
    except ValueError:
        return ""
