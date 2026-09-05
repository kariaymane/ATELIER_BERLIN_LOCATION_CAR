"""
Main Application Window for ATELIER BERLIN LOCATION CAR Car Rental System.
Offline-first architecture with automatic background synchronization and full localization.
"""
import uuid
import logging
import asyncio
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QLabel, QLineEdit, QPushButton,
    QStatusBar, QMessageBox, QComboBox, QMenu, QApplication, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer, QEvent, QThread, Signal
from PySide6.QtGui import QFont, QAction

from app.i18n import t, is_rtl, set_language, load_translations, get_language
from app.services.event_bus import get_event_bus
from app.state.domain_store import get_domain_store
from app.state.boundary_clock import BoundaryClock
from app.config import (
    API_BASE_URL, THEMES, DEFAULT_THEME, get_saved_theme, save_theme,
    get_saved_language, save_language, SYNC_INTERVAL_SECONDS
)
from app.database import get_local_session
from app.models.user import LocalUser
from app.models.vehicle import LocalVehicle
from app.models.vehicle_image import LocalVehicleImage
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.services.api_client import ApiClient
from app.ui.widgets.sidebar import Sidebar
from app.ui.dashboard import DashboardWidget
from app.ui.vehicles.vehicle_list import VehicleListWidget
from app.ui.vehicles.vehicle_form import VehicleFormDialog
from app.ui.vehicles.vehicle_hover_preview import get_hover_preview, get_existing_hover_preview
from app.ui.reservations.reservation_list import ReservationWidget
from app.ui.maintenance.maintenance_list import MaintenanceWidget
from app.ui.clients.client_list import ClientsWidget
from app.ui.clients.client_details import ClientDetailsDialog
from app.ui.settings.settings_widget import SettingsWidget

logger = logging.getLogger(__name__)


class SyncThread(QThread):
    """Runs a full SyncEngine cycle in a background thread.

    The engine is asyncio-based; it runs on its own event loop inside this
    thread so the Qt UI thread is never blocked by network I/O.
    """
    sync_finished = Signal(dict)

    def __init__(self, device_id: str, access_token: str, refresh_token: str, force_bootstrap: bool = False, parent=None):
        super().__init__(parent)
        self._device_id = device_id
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._force_bootstrap = force_bootstrap

    def run(self):
        from app.sync.engine import SyncEngine
        report: dict = {}
        try:
            engine = SyncEngine(self._device_id, self._access_token, self._refresh_token)
            connected = asyncio.run(engine.check_connection())
            report["is_online"] = connected
            if connected and self._access_token:
                if self._force_bootstrap:
                    try:
                        asyncio.run(engine.bootstrap())
                    except Exception as eb:
                        logger.warning("Bootstrap note: %s", eb)
                result = asyncio.run(engine.sync())
                if "is_online" in result:
                    report["is_online"] = result["is_online"]
                report.update({k: v for k, v in result.items() if k != "is_online"})
                report["access_token"] = engine._access_token
                report["refresh_token"] = engine._refresh_token
        except Exception as e:
            logger.debug("Sync thread note: %s", e)
            report["is_online"] = False
        self.sync_finished.emit(report)


def _safely_cancel_hover():
    preview = get_existing_hover_preview()
    if preview is not None:
        try:
            preview.cancel_and_hide()
        except Exception:
            pass


class MainWindow(QMainWindow):
    """Main application window with sidebar navigation, clean settings, and auto-sync."""

    def __init__(self, user_data: dict):
        super().__init__()
        self._user_data = user_data
        self._access_token = user_data.get("access_token", "")
        self._refresh_token = user_data.get("refresh_token", "")
        self._current_theme = get_saved_theme()
        self._device_id = self._get_device_id()
        self._is_online = not user_data.get("offline", False)

        # Load saved language
        current_lang = get_saved_language()
        set_language(current_lang)

        self.setWindowTitle(t("app_name"))
        # RESPONSIVE ROOT CAUSE FIX. The old floor was 1200x750: on a 1366x768
        # or 1280x720 laptop the usable desktop area (minus title bar, panel
        # and taskbar) is SHORTER than 750, so Qt could not honour the size and
        # the shell was forced past the screen edge — the clipped sidebar and
        # cut-off header in the reported screenshot. Every page now reflows and
        # scrolls, so the window only needs to stay usable, not stay large.
        self.setMinimumSize(900, 560)

        # Cache user locally for offline login
        self._cache_user_locally(user_data)

        # Setup API Client BEFORE UI construction: page widgets (reservations)
        # receive it during _setup_ui().
        self._api = ApiClient(API_BASE_URL)
        self._api.set_tokens(self._access_token, self._refresh_token)

        # Canonical local domain-state layer. Every main view renders FROM this
        # snapshot; none derives a competing global state. (Increment 2)
        self._store = get_domain_store()
        self._store_unsub = self._store.subscribe(self._on_domain_changed)

        # ONE temporal mechanism: recompute + republish at each reservation /
        # maintenance interval boundary, with no user action. (Increment 3)
        self._boundary_clock = BoundaryClock(self._store)

        self._setup_ui()
        self._apply_theme(self._current_theme)

        # Authoritative Live Server Dashboard State
        self._authoritative_server_overview = None
        self._authoritative_server_top_vehicles = None
        self._authoritative_server_snapshot = None
        # Which payload the dashboard is currently painting from:
        # "dto" (snapshot endpoint), "overview" (legacy flat), or None (local
        # mirror). Exactly one is ever used — they are never blended.
        self._dashboard_source_kind = None
        self._has_server_dashboard = False
        self._dashboard_generation = 0

        # Setup Real-time WebSocket Client
        try:
            from app.services.realtime_client import RealtimeEventsClient
            self._realtime_client = RealtimeEventsClient(self, access_token=self._access_token)
            self._realtime_client.event_received.connect(self._on_realtime_event)
            self._realtime_client.start()
        except Exception as e:
            logger.debug("Realtime client init: %s", e)

        # Setup sync timer (automatic background synchronization)
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._run_sync)
        self._sync_timer.start(SYNC_INTERVAL_SECONDS * 1000)

        # Start the temporal clock — it subscribes to the store and arms one
        # single-shot timer for the next reservation/maintenance boundary.
        try:
            self._boundary_clock.start()
        except Exception as e:
            logger.debug("BoundaryClock start: %s", e)

        # Initial data load
        QTimer.singleShot(100, self._initial_load)

        # Legacy pulse -> canonical store reload. `data_refreshed` is retained
        # only as a trigger (mutation handlers, background sync/uploads,
        # existing regression tests). It no longer fans out views by hand;
        # `DomainStore.reload()` publishes a revisioned snapshot and the
        # subscriber `_on_domain_changed` performs the isolated fan-out.
        get_event_bus().data_refreshed.connect(self._on_global_data_refreshed)

    def _on_realtime_event(self, event: dict):
        if not hasattr(self, "_immediate_sync_timer"):
            self._immediate_sync_timer = QTimer(self)
            self._immediate_sync_timer.setSingleShot(True)
            self._immediate_sync_timer.timeout.connect(self._run_sync)
        self._immediate_sync_timer.start(250)

    def _get_device_id(self) -> str:
        from app.config import DATA_DIR
        device_file = DATA_DIR / "device_id.txt"
        if device_file.exists():
            return device_file.read_text().strip()
        device_id = f"desktop-{uuid.uuid4().hex[:12]}"
        device_file.write_text(device_id)
        return device_id

    def _cache_user_locally(self, user_data: dict):
        if user_data.get("offline"):
            return

        user_id = user_data.get("user_id", "")
        if not user_id:
            return

        session = get_local_session()
        try:
            now = datetime.now(timezone.utc).isoformat()
            email = user_data.get("email", "")
            username = user_data.get("username", user_data.get("full_name", "user"))
            existing = session.query(LocalUser).filter(
                (LocalUser.id == user_id) |
                (LocalUser.email == email) |
                (LocalUser.username == username)
            ).first()
            if existing:
                existing.role = user_data.get("role", existing.role)
                existing.full_name = user_data.get("full_name", existing.full_name)
                existing.email = email or existing.email
                existing.username = username or existing.username
                existing.updated_at = now
            else:
                local_user = LocalUser(
                    id=user_id,
                    email=email,
                    username=username,
                    password_hash="",
                    full_name=user_data.get("full_name", ""),
                    role=user_data.get("role", "EMPLOYEE"),
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                session.add(local_user)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to cache user: %s", e)
        finally:
            session.close()

    def _setup_ui(self):
        if is_rtl():
            QApplication.instance().setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        else:
            QApplication.instance().setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        central = QWidget()
        central.setObjectName("main_container")
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Sidebar
        role = self._user_data.get("role", "EMPLOYEE")
        self._sidebar = Sidebar(user_role=role)
        self._sidebar.page_changed.connect(self._switch_page)
        self._sidebar.logout_requested.connect(self._logout)
        main_layout.addWidget(self._sidebar)

        # 2. Content area
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # ── Top bar / Header (Right-aligned: Search | Refresh | Profile) ──
        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(20, 10, 20, 10)
        topbar_layout.setSpacing(12)
        topbar_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Expanding spacer pushes all controls to the far right
        topbar_layout.addStretch(1)

        # Global search bar — shrinks with the window instead of pinning
        # 260px and pushing the refresh/profile controls off the right edge.
        self._global_search = QLineEdit()
        self._global_search.setPlaceholderText(t("topbar.search_placeholder"))
        self._global_search.setMinimumWidth(120)
        self._global_search.setMaximumWidth(320)
        self._global_search.setFixedHeight(36)
        self._global_search.setSizePolicy(QSizePolicy.Policy.Expanding,
                                          QSizePolicy.Policy.Fixed)
        self._global_search.setFont(QFont("Hanken Grotesk", 11))
        self._global_search.textChanged.connect(self._on_global_search)
        topbar_layout.addWidget(self._global_search, 1)

        # Refresh button
        self._refresh_btn = QPushButton(t("topbar.refresh"))
        self._refresh_btn.setFixedHeight(36)
        self._refresh_btn.setMinimumWidth(96)
        self._refresh_btn.setMaximumWidth(160)
        self._refresh_btn.setSizePolicy(QSizePolicy.Policy.Preferred,
                                        QSizePolicy.Policy.Fixed)
        self._refresh_btn.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        topbar_layout.addWidget(self._refresh_btn)

        # User Avatar + Dropdown — always visible; the name is what gives way.
        user_name = self._user_data.get('full_name', 'Profil')
        self._user_btn = QPushButton(f"👤 {user_name} ▾")
        self._user_btn.setFixedHeight(36)
        self._user_btn.setMinimumWidth(60)
        self._user_btn.setMaximumWidth(220)
        self._user_btn.setSizePolicy(QSizePolicy.Policy.Preferred,
                                     QSizePolicy.Policy.Fixed)
        self._user_btn.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))

        self._user_menu = QMenu(self._user_btn)
        self._profile_action = self._user_menu.addAction(t("topbar.profile"), self._show_profile)
        self._logout_action = self._user_menu.addAction(t("topbar.logout"), self._logout)
        self._user_btn.setMenu(self._user_menu)
        topbar_layout.addWidget(self._user_btn)

        content_layout.addWidget(topbar)

        # ── Stacked pages ──
        self._stack = QStackedWidget()
        self._pages = {}

        # 1. Dashboard
        self._dashboard = DashboardWidget()
        # ONE provider -> ONE snapshot -> every card. The revenue-only provider
        # stays wired for the legacy flat-overview path (BoundaryClock, tests).
        self._dashboard.set_snapshot_provider(self._dashboard_snapshot_provider)
        self._dashboard.set_revenue_provider(self._revenue_provider)
        self._add_page("dashboard", self._dashboard)

        # 2. Vehicles
        self._vehicle_list = VehicleListWidget(user_role=role)
        self._vehicle_list.add_requested.connect(self._on_add_vehicle)
        self._vehicle_list.vehicle_selected.connect(self._on_edit_vehicle)
        self._vehicle_list.maintenance_requested.connect(self._on_maintenance_requested)
        self._vehicle_list.delete_requested.connect(self._on_delete_vehicle)
        self._add_page("vehicles", self._vehicle_list)

        # 3. Reservations
        self._reservations = ReservationWidget(self._device_id, self._user_data.get("user_id"), user_role=role, api_client=self._api)
        self._reservations.reservation_created.connect(self._on_reservation_updated)
        self._add_page("reservations", self._reservations)

        # 4. Maintenance
        self._maintenance = MaintenanceWidget(self._device_id, self._user_data.get("user_id"), user_role=role)
        self._maintenance.maintenance_updated.connect(self._on_maintenance_updated)
        self._maintenance.maintenance_add_requested.connect(self._save_maintenance)
        self._add_page("maintenance", self._maintenance)

        # 5. Clients (live canonical data from the API)
        self._clients_page = ClientsWidget(api_client=self._api)
        self._clients_page.client_selected.connect(self._open_client_details)
        self._add_page("clients", self._clients_page)


        # 6. Settings
        self._settings = SettingsWidget(user_data=self._user_data)
        self._settings.theme_changed.connect(self._apply_theme)
        self._settings.language_changed.connect(self._change_language)
        self._add_page("settings", self._settings)

        content_layout.addWidget(self._stack, 1)
        main_layout.addLayout(content_layout, 1)

        # Status bar
        status_bar = QStatusBar()
        status_bar.setStyleSheet("QStatusBar { padding-bottom: 10px; }")
        self.setStatusBar(status_bar)
        status_msg = t("sync.online") if self._is_online else t("sync.offline")
        status_bar.showMessage(status_msg)

        self._switch_page("dashboard")

    def _add_page(self, key: str, widget: QWidget):
        idx = self._stack.addWidget(widget)
        self._pages[key] = idx

    def _switch_page(self, page_key: str):
        get_hover_preview().cancel_and_hide()
        idx = self._pages.get(page_key, 0)
        self._stack.setCurrentIndex(idx)
        self._current_page_key = page_key
        self._sidebar._set_active(page_key)

        # Every entrypoint below publishes a fresh revision through the store
        # before rendering, so a tab visit always shows current truth even if
        # an earlier fan-out to that view had failed (self-heal).
        if page_key == "vehicles":
            self._load_vehicles_from_local()
        elif page_key == "dashboard":
            self._refresh_dashboard(fetch_server=True, request_revenue=True)
        elif page_key == "clients":
            self._clients_page.refresh_data()
        elif page_key == "reservations":
            self._reservations.refresh_data()
        elif page_key == "maintenance":
            self._maintenance.refresh_data()

    def _open_client_details(self, client_id: str):
        """Open the canonical Client Details view for the selected client."""
        row = None
        for c in getattr(self._clients_page, "_clients", []):
            if str(c.get("id")) == str(client_id):
                row = c
                break
        if row is None:
            row = {"id": client_id}
        dialog = ClientDetailsDialog(row, api_client=self._api, parent=self)
        dialog.exec()
        # After closing (possible mutations elsewhere), refresh live state.
        self._clients_page.refresh_data()


    def _change_language(self, lang: str):
        set_language(lang)
        save_language(lang)
        load_translations()

        if is_rtl():
            QApplication.instance().setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        else:
            QApplication.instance().setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        self.retranslate_ui()

    def retranslate_ui(self):
        """Update every single component across the entire window immediately."""
        self.setWindowTitle(t("app_name"))
        status_msg = t("sync.online") if self._is_online else t("sync.offline")
        self.statusBar().showMessage(status_msg)

        # Topbar elements
        self._global_search.setPlaceholderText(t("topbar.search_placeholder"))
        self._refresh_btn.setText(t("topbar.refresh"))
        self._profile_action.setText(t("topbar.profile"))
        self._logout_action.setText(t("topbar.logout"))

        # Sidebar & Pages
        self._sidebar.retranslate_ui()
        self._dashboard.retranslate_ui()
        self._vehicle_list.retranslate_ui()
        self._reservations.retranslate_ui()
        self._maintenance.retranslate_ui()
        self._clients_page.retranslate_ui()
        self._settings.retranslate_ui()
        get_hover_preview().retranslate_ui()

        # Update page title
        cur_key = getattr(self, "_current_page_key", "dashboard")
        self._switch_page(cur_key)

    def _on_global_search(self, text):
        current_idx = self._stack.currentIndex()
        for key, idx in self._pages.items():
            if idx == current_idx:
                if key == "vehicles":
                    self._vehicle_list.set_filter(text)
                elif key == "reservations":
                    self._reservations.set_filter(text)
                elif key == "maintenance":
                    self._maintenance.set_filter(text)
                break

    def _apply_theme(self, theme: str):
        from app.ui.theme import get_app_stylesheet
        self._current_theme = theme
        save_theme(theme)
        stylesheet = get_app_stylesheet(theme)
        QApplication.instance().setStyleSheet(stylesheet)

    # ──── Data Loading ────

    def _initial_load(self):
        # Prime the canonical snapshot, then sync. The reload publishes to every
        # subscribed view; no per-view kick-off needed.
        self._store.reload()
        self._run_sync()

    def _load_vehicles_from_local(self):
        """Render the Vehicles page FROM the canonical snapshot.

        Called both as a direct entrypoint (tab switch, tests) and from the
        domain fan-out. As a direct entrypoint it asks the store to publish a
        fresh revision first; that reload's fan-out re-enters this method to do
        the actual render, so the outer call then returns without
        double-rendering. When reached from the fan-out, reload() is a
        re-entrant no-op and this method renders directly. Either way the
        snapshot already carries each vehicle's canonical EFFECTIVE status
        (app.utils.fleet_status) — identical to the Dashboard and the backend.
        This method never queries SQLite or re-derives status itself.
        """
        try:
            rev_before = self._store.revision
            self._store.reload()
            if self._store.revision != rev_before:
                return  # reload() published a new revision; the fan-out already rendered
            vehicles = [dict(v) for v in self._store.snapshot.vehicles]
            self._vehicle_list.load_vehicles(vehicles)
        except Exception as e:
            logger.error("Failed to render vehicles from domain snapshot: %s", e, exc_info=True)

    def _refresh_dashboard(self, fetch_server: bool = False, request_revenue: bool = False):
        """Render the Dashboard, and optionally go and get a fresher snapshot.

        Two steps, deliberately separate:

        1. RENDER NOW from the best payload already held, so a domain fan-out
           never blanks the screen while a request is in flight.
        2. When ``fetch_server`` is set (tab visit, manual refresh, end of a
           sync cycle), ask for a fresh authoritative snapshot — coalesced,
           because one sync can publish several revisions in a row.

        What this method no longer does is assemble an overview by hand. The
        previous version merged the server response with fleet keys re-derived
        from the local SQLite mirror, which is exactly how the screen ended up
        showing counts that contradicted both the database and each other.
        """
        self._render_dashboard_from_best_known()

        if fetch_server:
            timer = getattr(self, "_dashboard_refresh_timer", None)
            if timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(self._dashboard.request_snapshot)
                self._dashboard_refresh_timer = timer
            timer.start(120)

    def _render_dashboard_from_best_known(self):
        """Paint from the freshest payload in hand — no network, no merging.

        Precedence: the last authoritative server snapshot, then the legacy
        server overview, then the local mirror (explicitly marked as cache).
        Exactly one of them is used; they are never blended, because a blended
        dashboard is one whose cards describe different data.
        """
        kind = getattr(self, "_dashboard_source_kind", None)
        if not self._is_online:
            # Genuinely disconnected: the operator's own offline edits are the
            # freshest truth available, so show the mirror (labelled as cache)
            # rather than a frozen server payload that predates them.
            kind = None
        try:
            if kind == "dto" and getattr(self, "_authoritative_server_snapshot", None):
                self._dashboard.apply_snapshot(self._authoritative_server_snapshot)
                return
            if kind == "overview" and getattr(self, "_authoritative_server_overview", None):
                # Prefer the store's copy: it holds the SAME server payload
                # (taken verbatim) but ``recompute_effective`` keeps its
                # time-derived figures current when the clock crosses a
                # reservation, maintenance or midnight boundary. Falling back
                # to the frozen fetch-time copy is what used to make the
                # Dashboard contradict the Vehicles list after a boundary.
                snap = self._store.snapshot
                overview = (dict(snap.overview) if (snap.is_live and snap.overview)
                            else dict(self._authoritative_server_overview))
                top = (list(snap.top_vehicles or [])
                       or list(getattr(self, "_authoritative_server_top_vehicles", None) or []))
                self._dashboard.refresh_data(overview, top,
                                             request_revenue=False, is_live=True)
                return

            from app.sync.dashboard_snapshot import build_local_snapshot
            # The store's clock, not the wall clock: tests (and the temporal
            # recompute path) drive the store from an injected ``now_fn``, and
            # the snapshot must describe the same instant as the rows it reads.
            self._dashboard.apply_snapshot(
                build_local_snapshot(self._store.snapshot,
                                     period=self._dashboard.current_period(),
                                     now=self._store.now())
            )
        except Exception as e:
            logger.error("Dashboard render failed: %s", e, exc_info=True)

    def _dashboard_snapshot_provider(self, period: str, from_date: date,
                                     to_date_inclusive: date):
        """(period, from, to) -> the canonical dashboard DTO.

        Runs on the Dashboard's worker thread. PostgreSQL is the source of
        truth: the server snapshot is used verbatim, never merged key-by-key
        with locally derived numbers. The local mirror is consulted ONLY when
        the server cannot be reached, and the DTO it produces is stamped
        ``source="local"`` so the UI labels it as cache rather than truth.
        Returning None means "unknown" and the Dashboard shows "—", never 0.
        """
        from app.services.api_client import ServerContractMismatchError

        if self._is_online and self._access_token:
            try:
                dto = self._api.get_dashboard_summary(
                    period,
                    from_date.isoformat() if period == "custom" else None,
                    to_date_inclusive.isoformat() if period == "custom" else None,
                )
                if dto:
                    self._on_server_snapshot(dto)
                    return dto
            except ServerContractMismatchError as e:
                # A deployed backend older than this client. Never silently
                # degrade to a local number that would look authoritative.
                logger.error("Dashboard contract mismatch: %s", e)
            except Exception as e:
                logger.info("Dashboard snapshot fetch failed (offline?): %s", e)

            if self._is_online and getattr(self, "_has_server_dashboard", False):
                # A transient failure while nominally online, with authoritative
                # server figures already in hand. Returning a locally recomputed
                # snapshot here would REPLACE them with the SQLite mirror — a
                # downgrade dressed as a refresh, and the exact reversion this
                # architecture forbids. Report "could not refresh" instead and
                # let the Dashboard keep what it has. (Once the window knows it
                # is truly offline, the mirror IS the best answer and the
                # fallback below runs.)
                return None

        try:
            from app.sync.dashboard_snapshot import build_local_snapshot
            return build_local_snapshot(
                self._store.snapshot,
                period=period,
                custom_from=from_date if period == "custom" else None,
                custom_to_inclusive=to_date_inclusive if period == "custom" else None,
            )
        except Exception as e:
            logger.error("Local dashboard snapshot failed: %s", e, exc_info=True)
            return None

    def _on_server_snapshot(self, dto: dict):
        """Record the latest authoritative server snapshot (worker thread).

        Kept as plain state for the sync/reversion regression tests; the
        rendering itself is done by the Dashboard from the DTO it received.
        """
        self._authoritative_server_snapshot = dict(dto)
        self._dashboard_source_kind = "dto"
        self._has_server_dashboard = True

    def _revenue_provider(self, from_date: date, to_date_inclusive: date):
        """(revenue, source) — legacy revenue-only path.

        Retained for callers and tests that predate the snapshot DTO. It asks
        the SAME backend engine (``/dashboard/revenue``) and falls back to the
        SAME shared pro-rata spec over the local mirror, so it can never
        produce a third number.
        """
        from app.services.api_client import ServerContractMismatchError
        if self._is_online and self._access_token:
            try:
                data = self._api.get_revenue_range(
                    from_date.isoformat(), to_date_inclusive.isoformat()
                )
                if data and data.get("revenue") is not None:
                    return float(data["revenue"]), "server"
            except ServerContractMismatchError as e:
                logger.error("Server contract mismatch on revenue range: %s", e)
            except Exception as e:
                logger.info("revenue range fetch failed: %s", e)

        try:
            from app.sync.dashboard_cache import revenue_between_rows
            rows = list(self._store.snapshot.reservations or [])
            rev, _days = revenue_between_rows(
                rows, from_date, to_date_inclusive + timedelta(days=1)
            )
            return rev, "local"
        except Exception as e:
            logger.error("local revenue computation failed: %s", e)
            return None, "error"

    def _on_dashboard_stats(self, overview: dict, top_vehicles: list, generation: int = 0):
        """Apply a legacy ``/dashboard/stats`` payload (UI thread).

        PostgreSQL is authoritative: the server figures are rendered VERBATIM.
        The previous version overwrote the server's fleet keys with counts
        re-derived from the local SQLite mirror, so a stale or partially
        synced cache could silently contradict the database on screen — the
        root cause this rebuild removes.
        """
        current_gen = getattr(self, "_dashboard_generation", 0)
        if current_gen > 0 and generation < current_gen:
            logger.info("Dropping stale dashboard stats generation %s (current: %s)",
                        generation, current_gen)
            return

        overview = dict(overview)
        snap = self._store.update_server_dashboard(overview, top_vehicles,
                                                   generation=generation)

        self._authoritative_server_overview = dict(overview)
        self._last_server_overview = dict(overview)
        self._dashboard_source_kind = "overview"
        if top_vehicles:
            self._authoritative_server_top_vehicles = list(top_vehicles)
            self._last_server_top_vehicles = list(top_vehicles)
        self._has_server_dashboard = True

        top = (top_vehicles
               or getattr(self, "_authoritative_server_top_vehicles", None)
               or getattr(self, "_last_server_top_vehicles", None)
               or [dict(v) for v in self._store.snapshot.top_vehicles])
        self._dashboard.refresh_data(overview, top, request_revenue=False, is_live=True)

    def _run_sync(self, force_bootstrap: bool = False):
        """Execute the sync cycle in a background thread (never blocks UI)."""
        thread = getattr(self, "_sync_thread", None)
        if thread is not None:
            try:
                if thread.isRunning():
                    self._sync_pending = True
                    return  # previous cycle still running — mark pending to avoid losing events
            except RuntimeError:
                pass  # C++ object already deleted — safe to start a new one
            self._sync_thread = None
        self._sync_pending = False
        thread = SyncThread(
            self._device_id, self._access_token, self._refresh_token,
            force_bootstrap=force_bootstrap, parent=self
        )
        thread.sync_finished.connect(self._on_sync_finished)
        thread.finished.connect(self._on_sync_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._sync_thread = thread
        thread.start()

    def _on_sync_thread_finished(self):
        """Release the Python reference once the thread truly finished.

        deleteLater destroys the C++ object asynchronously; clearing the
        attribute here prevents any later isRunning() access on a deleted
        object (which previously killed the sync loop silently).
        """
        self._sync_thread = None
        if getattr(self, "_sync_pending", False):
            self._sync_pending = False
            self._run_sync()

    def _on_sync_finished(self, report: dict):
        """Handle background sync results on the UI thread."""
        try:
            is_connected = bool(report.get("is_online"))
            if is_connected:
                was_offline = not self._is_online
                self._is_online = True

                new_access = report.get("access_token")
                if new_access and new_access != self._access_token:
                    self._access_token = new_access
                    self._refresh_token = report.get("refresh_token", self._refresh_token)
                    if self._api:
                        self._api.set_tokens(self._access_token, self._refresh_token)
                    if hasattr(self, "_realtime_client") and self._realtime_client:
                        self._realtime_client.update_token(self._access_token)

                push_res = report.get("push", {})
                pull_res = report.get("pull", {})
                upload_res = report.get("uploads", {})
                # Unconditionally trigger global data_refreshed on sync completion:
                # Guarantees that DomainStore reloads and fans out to all views
                # (Vehicles, Reservations, Maintenance, Clients, Dashboard) so no stale state lingers.
                get_event_bus().data_refreshed.emit()

                # Surface server-rejected reservations visibly (never silent).
                for conflict in push_res.get("conflicts") or []:
                    if conflict.get("entity_type") == "reservation":
                        self.statusBar().showMessage(
                            t("reservations.rejected_by_server"), 8000)

                status_text = t("sync.reconnected") if was_offline else t("sync.online")
                self.statusBar().showMessage(status_text, 4000)

                if getattr(self, "_current_page_key", "dashboard") == "dashboard":
                    self._refresh_dashboard(fetch_server=True, request_revenue=True)
            else:
                self._is_online = False
                self.statusBar().showMessage(t("sync.offline"))
                # Strict Server Authority: DO NOT clobber live server state on offline/glitch.
                # DomainStore and Dashboard retain their latest authoritative server figures.
        except Exception as e:
            logger.debug("Sync result handling note: %s", e)
        finally:
            # Always restore the refresh button, whether sync succeeded or not.
            self._restore_refresh_btn()

    def _on_refresh_clicked(self):
        """Single canonical manual refresh — same pipeline as auto-refresh.

        The sync thread pulls server deltas, then ``_on_sync_finished``
        triggers ``DomainStore.reload()`` which fans out to every view.
        If a sync is already in flight, mark it pending so a single follow-up
        cycle executes immediately upon completion — never drops clicks or races.
        """
        self._manual_refresh_requested = True
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText(t("topbar.refreshing"))

        # Immediately fetch authoritative live server metrics without blocking on background sync
        if getattr(self, "_current_page_key", "dashboard") == "dashboard":
            self._refresh_dashboard(fetch_server=True, request_revenue=True)

        thread = getattr(self, "_sync_thread", None)
        try:
            if thread is not None and thread.isRunning():
                self._sync_pending = True
                return  # sync already running — follow-up is scheduled
        except RuntimeError:
            pass

        try:
            self._run_sync(force_bootstrap=True)
        except TypeError:
            self._run_sync()

    def _restore_refresh_btn(self):
        """Restore the topbar refresh button after a sync cycle completes."""
        try:
            self._refresh_btn.setEnabled(True)
            status_text = t("topbar.updated") if self._is_online else t("sync.offline")
            self._refresh_btn.setText(status_text)
            QTimer.singleShot(2000, lambda: self._refresh_btn.setText(t("topbar.refresh")))
        except RuntimeError:
            pass  # widget already destroyed during shutdown

    def _show_profile(self):
        name = self._user_data.get('full_name', 'Utilisateur')
        email = self._user_data.get('email', '')
        QMessageBox.information(self, t("topbar.profile"), t("common.profile_msg", name=name, email=email))

    def _logout(self):
        if self._api and self._api.is_online and self._access_token:
            import httpx
            try:
                with httpx.Client(timeout=2.0) as client:
                    client.post(
                        f"{API_BASE_URL}/api/v1/auth/logout",
                        json={"refresh_token": self._refresh_token or ""},
                        headers={"Authorization": f"Bearer {self._access_token}"}
                    )
            except Exception:
                pass
        self._access_token = None
        self._refresh_token = None

        import os
        import sys
        self.close()
        os.execl(sys.executable, sys.executable, *sys.argv)

    # ──── CRUD Handlers ────

    def _on_add_vehicle(self):
        dialog = VehicleFormDialog(api_client=self._api, parent=self)
        dialog.saved.connect(self._create_vehicle)
        dialog.exec()

    def _save_vehicle(self, data: dict):
        self._create_vehicle(data)

    def _register_vehicle_image_uploads(self, vehicle_id: str, data: dict):
        """Register durable pending-upload records for offline images.

        Runs on its own session AFTER the entity is safely persisted —
        ``register_pending_upload`` self-commits, so it cannot participate in
        the ``DomainStore.mutate()`` transaction.
        """
        from app.sync.uploads import register_pending_upload
        markers = set()
        if (data.get("image_url") or "").startswith("pending_uploads/"):
            markers.add(data["image_url"])
        for u in data.get("images") or []:
            if str(u).startswith("pending_uploads/"):
                markers.add(str(u))
        if not markers:
            return
        session = get_local_session()
        try:
            for marker in markers:
                register_pending_upload(
                    session, marker=marker, entity_type="vehicle",
                    entity_id=vehicle_id, upload_type="VEHICLE_IMAGE",
                    remote_endpoint="/api/v1/vehicles/upload-image",
                    field_name="image_url",
                )
        finally:
            session.close()

    def _create_vehicle(self, data: dict):
        vehicle_id = data.get("id") or str(uuid.uuid4())
        data["id"] = vehicle_id
        now_iso = datetime.now(timezone.utc).isoformat()

        def _apply(session):
            v = LocalVehicle(
                id=vehicle_id,
                registration=data["registration"],
                vin=data.get("vin"),
                brand=data["brand"],
                model=data["model"],
                year=data.get("year", 2024),
                color=data.get("color", "Noir"),
                fuel_type=data.get("fuel_type", "GASOLINE"),
                transmission=data.get("transmission", "MANUAL"),
                current_mileage=data.get("current_mileage", 0),
                purchase_mileage=data.get("purchase_mileage", 0),
                purchase_price=data.get("purchase_price", 0.0),
                daily_rental_price=data.get("daily_rental_price", 0.0),
                status=data.get("status", "AVAILABLE"),
                image_url=data.get("image_url"),
                assurance_expiry=data.get("assurance_expiry"),
                vignette_expiry=data.get("vignette_expiry"),
                visite_technique_expiry=data.get("visite_technique_expiry"),
                carte_grise_expiry=data.get("carte_grise_expiry"),
                autres_label=data.get("autres_label"),
                autres_expiry=data.get("autres_expiry"),
                notes=data.get("notes"),
                created_at=now_iso,
                updated_at=now_iso,
                version=1
            )
            session.add(v)
            from app.sync.queue import SyncQueue
            SyncQueue(session, self._device_id, self._user_data.get("user_id")).enqueue(
                "vehicle", vehicle_id, "CREATE", data)

        # Canonical write path: one transaction → store reload → every view
        # converges. On failure: rollback, NO publish, visible error.
        try:
            self._store.mutate(_apply)
        except Exception as e:
            logger.error("Erreur lors de l'ajout du véhicule: %s", e, exc_info=True)
            QMessageBox.critical(self, t("common.error"), f"Erreur lors de l'ajout: {e}")
            return
        self._register_vehicle_image_uploads(vehicle_id, data)
        self._run_sync()
        self.statusBar().showMessage(t("vehicles.form_success_create"), 3000)

    def _on_edit_vehicle(self, vehicle_id: str):
        from app.ui.vehicles.vehicle_hover_preview import get_hover_preview
        get_hover_preview().hide_preview()

        session = get_local_session()
        v_data = None
        try:
            v = session.query(LocalVehicle).filter_by(id=vehicle_id).first()
            if not v:
                return
            v_data = {
                "id": v.id,
                "registration": v.registration,
                "vin": v.vin,
                "brand": v.brand,
                "model": v.model,
                "year": v.year,
                "color": v.color,
                "fuel_type": v.fuel_type,
                "transmission": v.transmission,
                "current_mileage": v.current_mileage,
                "purchase_mileage": v.purchase_mileage,
                "purchase_price": v.purchase_price,
                "daily_rental_price": v.daily_rental_price,
                "status": v.status,
                "image_url": v.image_url,
                "images": [img.image_url for img in v.images],
                "assurance_expiry": v.assurance_expiry,
                "vignette_expiry": v.vignette_expiry,
                "visite_technique_expiry": v.visite_technique_expiry,
                "carte_grise_expiry": v.carte_grise_expiry,
                "autres_label": v.autres_label,
                "autres_expiry": v.autres_expiry,
                "notes": v.notes,
            }
        except Exception as e:
            logger.error("Failed to load vehicle %s for edit: %s", vehicle_id, e, exc_info=True)
        finally:
            session.close()

        if v_data is None:
            QMessageBox.critical(self, t("common.error"),
                                 "Impossible de charger ce véhicule. Consultez les journaux.")
            return

        dialog = VehicleFormDialog(vehicle_data=v_data, api_client=self._api, parent=self)
        dialog.saved.connect(self._update_vehicle)
        dialog.exec()

    def _update_vehicle(self, data: dict):
        vehicle_id = data.get("id")
        now_iso = datetime.now(timezone.utc).isoformat()

        def _apply(session):
            v = session.query(LocalVehicle).filter_by(id=vehicle_id).first()
            if not v:
                return
            v.registration = data["registration"]
            v.brand = data["brand"]
            v.model = data["model"]
            v.year = data.get("year", v.year)
            v.color = data.get("color", v.color)
            v.fuel_type = data.get("fuel_type", v.fuel_type)
            v.transmission = data.get("transmission", v.transmission)
            v.current_mileage = data.get("current_mileage", v.current_mileage)
            v.purchase_mileage = data.get("purchase_mileage", v.purchase_mileage)
            v.purchase_price = data.get("purchase_price", v.purchase_price)
            v.daily_rental_price = data.get("daily_rental_price", v.daily_rental_price)
            v.status = data.get("status", v.status)
            v.image_url = data.get("image_url", v.image_url)
            v.assurance_expiry = data.get("assurance_expiry")
            if "images" in data:
                session.execute(__import__('sqlalchemy').delete(LocalVehicleImage).where(LocalVehicleImage.vehicle_id == v.id))
                for idx, u in enumerate(data["images"]):
                    img = LocalVehicleImage(id=str(uuid.uuid4()), vehicle_id=v.id, image_url=u, sort_order=idx)
                    session.add(img)
            v.vignette_expiry = data.get("vignette_expiry")
            v.visite_technique_expiry = data.get("visite_technique_expiry")
            v.carte_grise_expiry = data.get("carte_grise_expiry")
            v.autres_label = data.get("autres_label")
            v.autres_expiry = data.get("autres_expiry")
            v.notes = data.get("notes")
            v.updated_at = now_iso
            v.version += 1

            from app.sync.queue import SyncQueue
            SyncQueue(session, self._device_id, self._user_data.get("user_id")).enqueue(
                "vehicle", vehicle_id, "UPDATE", data)

        try:
            self._store.mutate(_apply)
        except Exception as e:
            logger.error("Erreur lors de la modification: %s", e, exc_info=True)
            error_msg = str(e).lower()
            if "readonly database" in error_msg:
                user_msg = "Impossible d'enregistrer les modifications. Le dossier de données est en lecture seule."
            else:
                user_msg = f"Une erreur technique est survenue lors de la modification. Consultez les journaux pour plus de détails."
            QMessageBox.critical(self, t("common.error"), user_msg)
            return
        self._register_vehicle_image_uploads(vehicle_id, data)
        self._run_sync()
        self.statusBar().showMessage(t("vehicles.form_success_edit"), 3000)

    def _on_delete_vehicle(self, vehicle_id: str):
        # Read-only lookup for the confirm dialog text (own short-lived session).
        rs = get_local_session()
        try:
            v = rs.query(LocalVehicle).filter_by(id=vehicle_id).first()
            if not v:
                return
            registration = v.registration
        finally:
            rs.close()

        reply = QMessageBox.question(
            self,
            t("vehicles.confirm_delete_title"),
            t("vehicles.confirm_delete_msg", reg=registration),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def _apply(session):
            v = session.query(LocalVehicle).filter_by(id=vehicle_id).first()
            if not v:
                return
            from app.sync.queue import SyncQueue
            SyncQueue(session, self._device_id, self._user_data.get("user_id")).enqueue(
                "vehicle", vehicle_id, "DELETE", {"id": vehicle_id})
            session.delete(v)

        try:
            self._store.mutate(_apply)
        except Exception as e:
            logger.error("Erreur lors de la suppression: %s", e, exc_info=True)
            error_msg = str(e).lower()
            if "readonly database" in error_msg:
                user_msg = "Impossible d'enregistrer les modifications. Le dossier de données est en lecture seule."
            else:
                user_msg = f"Une erreur technique est survenue lors de la suppression. Consultez les journaux pour plus de détails."
            QMessageBox.critical(self, t("common.error"), user_msg)
            return
        self._run_sync()

    def _on_maintenance_requested(self, vehicle_id: str):
        session = get_local_session()
        v_dict = None
        try:
            v = session.query(LocalVehicle).filter_by(id=vehicle_id).first()
            if not v:
                return
            v_dict = {
                "id": v.id,
                "brand": v.brand,
                "model": v.model,
                "registration": v.registration
            }
        except Exception as e:
            logger.error("Failed to load vehicle %s for maintenance: %s", vehicle_id, e, exc_info=True)
        finally:
            session.close()

        if v_dict is None:
            QMessageBox.critical(self, t("common.error"),
                                 "Impossible de charger ce véhicule. Consultez les journaux.")
            return

        from app.ui.maintenance.maintenance_list import MaintenanceFormDialog
        dialog = MaintenanceFormDialog(v_dict, self)
        dialog.saved.connect(self._create_maintenance_record)
        dialog.exec()

    def _save_maintenance(self, data: dict):
        self._create_maintenance_record(data)

    def _create_maintenance_record(self, data: dict):
        m_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        data["id"] = m_id
        result = {"cancelled": 0}

        def _apply(session):
            m = LocalMaintenance(
                id=m_id,
                vehicle_id=data.get("vehicle_id", ""),
                type=data.get("type", "Entretien"),
                title=data.get("title"),
                description=data.get("description"),
                diagnosis=data.get("diagnosis"),
                repair_description=data.get("repair_description"),
                start_datetime=data.get("start_datetime", now_iso),
                expected_end_datetime=data.get("expected_end_datetime"),
                actual_end_datetime=data.get("actual_end_datetime"),
                mileage=data.get("mileage"),
                location=data.get("location"),
                technician_name=data.get("technician_name"),
                invoice_number=data.get("invoice_number"),
                oil_brand=data.get("oil_brand"),
                oil_viscosity=data.get("oil_viscosity"),
                oil_quantity=data.get("oil_quantity"),
                oil_filter_changed=data.get("oil_filter_changed", False),
                air_filter_changed=data.get("air_filter_changed", False),
                fuel_filter_changed=data.get("fuel_filter_changed", False),
                cabin_filter_changed=data.get("cabin_filter_changed", False),
                estimated_cost=data.get("estimated_cost", 0.0),
                parts_cost=data.get("parts_cost", 0.0),
                labor_cost=data.get("labor_cost", 0.0),
                other_cost=data.get("other_cost", 0.0),
                actual_cost=data.get("actual_cost", 0.0),
                status="ACTIVE",
                step=data.get("step", "DIAGNOSTIC"),
                created_at=now_iso,
                updated_at=now_iso,
                version=1
            )
            session.add(m)

            from app.models.maintenance import LocalMaintenancePart
            for p in data.get("parts", []):
                session.add(LocalMaintenancePart(
                    id=str(uuid.uuid4()),
                    maintenance_id=m_id,
                    part_name=p["part_name"],
                    quantity=p["quantity"],
                    unit_price=p["unit_price"],
                    total_price=p["total_price"],
                    notes=p.get("notes"),
                    created_at=now_iso,
                    updated_at=now_iso
                ))

            from app.sync.queue import SyncQueue
            queue = SyncQueue(session, self._device_id, self._user_data.get("user_id"))
            queue.enqueue("maintenance", m_id, "CREATE", data)

            # CANONICAL RULE: maintenance wins over reservations. In the SAME
            # transaction, cancel every RESERVED / ACTIVE reservation of this
            # vehicle whose period overlaps the maintenance window. The
            # reservation row is preserved (status + machine reason), never
            # deleted or hidden. DomainStore.mutate() commits it as one unit,
            # then publishes one revision so every view converges.
            from app.models.reservation import LocalReservation
            from app.utils.datetime_utils import (
                parse_datetime_utc, reservations_overlap,
                BLOCKING_RESERVATION_STATUSES,
            )
            m_start = parse_datetime_utc(m.start_datetime)
            m_end = parse_datetime_utc(
                data.get("expected_end_datetime")
                or data.get("actual_end_datetime")
                or data.get("start_datetime")
            )
            if m_start and m_end and m_end > m_start:
                conflicting = session.query(LocalReservation).filter(
                    LocalReservation.vehicle_id == data.get("vehicle_id", ""),
                    LocalReservation.status.in_(BLOCKING_RESERVATION_STATUSES),
                ).all()
                for res in conflicting:
                    r_start = parse_datetime_utc(res.start_datetime)
                    r_end = parse_datetime_utc(res.end_datetime)
                    if reservations_overlap(m_start, m_end, r_start, r_end):
                        res.status = "CANCELLED"
                        res.cancellation_reason = "MAINTENANCE"
                        res.updated_at = now_iso
                        res.version = (res.version or 1) + 1
                        queue.enqueue("reservation", res.id, "UPDATE", {
                            "id": res.id,
                            "status": "CANCELLED",
                            "cancellation_reason": "MAINTENANCE",
                        })
                        result["cancelled"] += 1

        try:
            self._store.mutate(_apply)
        except Exception as e:
            logger.error("Erreur lors de la création de la maintenance: %s", e, exc_info=True)
            QMessageBox.critical(
                self, t("common.error"),
                "Une erreur technique est survenue lors de l'enregistrement de la maintenance. "
                "Consultez les journaux pour plus de détails.",
            )
            return
        self._run_sync()
        if result["cancelled"]:
            self.statusBar().showMessage(
                t("maintenance.reservation_cancelled_toast", n=result["cancelled"]), 4000)
        else:
            self.statusBar().showMessage("Maintenance enregistrée", 3000)

    def _on_global_data_refreshed(self):
        """Legacy trigger: rebuild the canonical snapshot.

        Committed domain mutations now converge through ``DomainStore.mutate()``
        directly. This slot remains for the *external* change sources that
        cannot: background sync push/pull applied off-thread
        (``_on_sync_finished``), the pending-upload processor
        (``sync/uploads.py``), the conflict-revert path (``sync/engine.py``),
        and the manual refresh button. Each asks the store to re-read SQLite
        and publish one revision; ``_on_domain_changed`` then fans out.
        """
        try:
            self._store.reload()
        except Exception as e:
            logger.error("DomainStore reload failed: %s", e, exc_info=True)

    def _on_domain_changed(self, snapshot, revision):
        """Canonical fan-out — invoked by DomainStore on every published
        revision. Each view is refreshed in isolation: one view raising must
        NOT stop the others, and no silent failure may leave a tab stale (the
        next revision or a tab visit re-heals it).
        """
        for label, fn in (
            ("vehicles", self._load_vehicles_from_local),
            ("dashboard", self._refresh_dashboard),
            ("reservations", self._reservations.refresh_data),
            ("maintenance", self._maintenance.refresh_data),
            ("clients", self._clients_page.refresh_data),
        ):
            try:
                fn()
            except Exception as e:
                logger.error("Domain fan-out to %s failed at revision %s: %s",
                             label, revision, e, exc_info=True)
        self._last_applied_revision = revision

    def _on_reservation_updated(self):
        # The reservation widget already committed through DomainStore.mutate()
        # (or refresh_data()'s reload) — the snapshot is published and every
        # view has converged. Only the background sync push remains.
        self._run_sync()

    def _on_maintenance_updated(self):
        # As above: the maintenance widget committed through
        # DomainStore.mutate(); just push to the server.
        self._run_sync()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            _safely_cancel_hover()
        super().changeEvent(event)

    def hideEvent(self, event):
        _safely_cancel_hover()
        super().hideEvent(event)

    def closeEvent(self, event):
        _safely_cancel_hover()
        # Stop the temporal clock (cancels its pending timer, no leaked threads).
        try:
            if getattr(self, "_boundary_clock", None):
                self._boundary_clock.stop()
        except Exception:
            pass
        # Detach from the domain store so a destroyed window is never called
        # back into (which would touch deleted C++ widgets).
        try:
            if getattr(self, "_store_unsub", None):
                self._store_unsub()
                self._store_unsub = None
        except Exception:
            pass
        if hasattr(self, "_sync_timer"):
            try:
                self._sync_timer.stop()
            except Exception:
                pass
        if hasattr(self, "_realtime_client"):
            try:
                self._realtime_client.stop()
            except Exception:
                pass
        super().closeEvent(event)
