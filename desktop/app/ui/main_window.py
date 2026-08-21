"""
Main Application Window for ATELIER BERLIN LOCATION CAR Car Rental System.
Offline-first architecture with automatic background synchronization and full localization.
"""
import uuid
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QLabel, QLineEdit, QPushButton,
    QStatusBar, QMessageBox, QComboBox, QMenu, QApplication
)
from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QFont, QAction

from app.i18n import t, is_rtl, set_language, load_translations, get_language
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
from app.sync.engine import SyncEngine
from app.ui.widgets.sidebar import Sidebar
from app.ui.dashboard import DashboardWidget
from app.ui.vehicles.vehicle_list import VehicleListWidget
from app.ui.vehicles.vehicle_form import VehicleFormDialog
from app.ui.vehicles.vehicle_hover_preview import get_hover_preview, get_existing_hover_preview
from app.ui.reservations.reservation_list import ReservationWidget
from app.ui.maintenance.maintenance_list import MaintenanceWidget
from app.ui.settings.settings_widget import SettingsWidget

logger = logging.getLogger(__name__)


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
        self.setMinimumSize(1200, 750)

        # Cache user locally for offline login
        self._cache_user_locally(user_data)

        self._setup_ui()
        self._apply_theme(self._current_theme)

        # Setup API Client
        self._api = ApiClient(API_BASE_URL)
        self._api.set_tokens(self._access_token, self._refresh_token)

        # Setup Real-time WebSocket Client
        try:
            from app.services.realtime_client import RealtimeEventsClient
            self._realtime_client = RealtimeEventsClient(self)
            self._realtime_client.event_received.connect(self._on_realtime_event)
            self._realtime_client.start()
        except Exception as e:
            logger.debug("Realtime client init: %s", e)

        # Setup sync timer (automatic background synchronization)
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._run_sync)
        self._sync_timer.start(SYNC_INTERVAL_SECONDS * 1000)

        # Initial data load
        QTimer.singleShot(100, self._initial_load)

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

        # Global search bar
        self._global_search = QLineEdit()
        self._global_search.setPlaceholderText(t("topbar.search_placeholder"))
        self._global_search.setFixedWidth(260)
        self._global_search.setFixedHeight(36)
        self._global_search.setFont(QFont("Hanken Grotesk", 11))
        self._global_search.textChanged.connect(self._on_global_search)
        topbar_layout.addWidget(self._global_search)

        # Refresh button
        self._refresh_btn = QPushButton(t("topbar.refresh"))
        self._refresh_btn.setFixedSize(140, 36)
        self._refresh_btn.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        topbar_layout.addWidget(self._refresh_btn)

        # User Avatar + Dropdown
        user_name = self._user_data.get('full_name', 'Profil')
        self._user_btn = QPushButton(f"👤 {user_name} ▾")
        self._user_btn.setFixedHeight(36)
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
        self._add_page("dashboard", self._dashboard)

        # 2. Vehicles
        self._vehicle_list = VehicleListWidget(user_role=role)
        self._vehicle_list.add_requested.connect(self._on_add_vehicle)
        self._vehicle_list.vehicle_selected.connect(self._on_edit_vehicle)
        self._vehicle_list.maintenance_requested.connect(self._on_maintenance_requested)
        self._vehicle_list.delete_requested.connect(self._on_delete_vehicle)
        self._add_page("vehicles", self._vehicle_list)

        # 3. Reservations
        self._reservations = ReservationWidget(self._device_id, self._user_data.get("user_id"), user_role=role)
        self._reservations.reservation_created.connect(self._on_reservation_updated)
        self._add_page("reservations", self._reservations)

        # 4. Maintenance
        self._maintenance = MaintenanceWidget(self._device_id, self._user_data.get("user_id"), user_role=role)
        self._maintenance.maintenance_updated.connect(self._on_maintenance_updated)
        self._maintenance.maintenance_add_requested.connect(self._save_maintenance)
        self._add_page("maintenance", self._maintenance)

        # 5. Settings
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

        if page_key == "vehicles":
            self._load_vehicles_from_local()
        elif page_key == "dashboard":
            self._refresh_dashboard()
        elif page_key == "reservations":
            self._reservations.refresh_data()
        elif page_key == "maintenance":
            self._maintenance.refresh_data()


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
        self._load_vehicles_from_local()
        self._refresh_dashboard()
        self._reservations.refresh_data()
        self._maintenance.refresh_data()
        self._run_sync()

    def _load_vehicles_from_local(self):
        session = get_local_session()
        try:
            vehicles = session.query(LocalVehicle).all()
            vehicle_dicts = []
            for v in vehicles:
                try:
                    images_list = [img.image_url for img in v.images] if hasattr(v, 'images') else []
                except Exception as e:
                    images_list = []
                    print("Error getting images:", e)

                vehicle_dicts.append({
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
                    "images": images_list,
                    "assurance_expiry": v.assurance_expiry,
                    "vignette_expiry": v.vignette_expiry,
                    "visite_technique_expiry": v.visite_technique_expiry,
                    "carte_grise_expiry": v.carte_grise_expiry,
                    "autres_label": v.autres_label,
                    "autres_expiry": v.autres_expiry,
                    "notes": v.notes,
                })
            self._vehicle_list.load_vehicles(vehicle_dicts)
        except Exception as e:
            logger.error("Failed to load vehicles from local db: %s", e)
        finally:
            session.close()

    def _refresh_dashboard(self):
        if self._is_online and self._access_token:
            import requests
            from app.config import API_BASE_URL, API_VERSION
            try:
                headers = {"Authorization": f"Bearer {self._access_token}"}
                resp_stats = requests.get(f"{API_BASE_URL}/api/{API_VERSION}/dashboard/stats", headers=headers, timeout=5)
                resp_perf = requests.get(f"{API_BASE_URL}/api/{API_VERSION}/dashboard/vehicle-performance", headers=headers, timeout=5)
                if resp_stats.status_code == 200:
                    data = resp_stats.json()
                    overview = {
                        "total_vehicles": data.get("total_vehicles", 0),
                        "available": data.get("available", 0),
                        "rented": data.get("rented", 0),
                        "reserved": data.get("reserved", 0),
                        "maintenance": data.get("maintenance", 0),
                        "active_maintenances": data.get("active_maintenance_tickets", 0),
                        "day_locations": data.get("today_rentals", 0),
                        "today_revenue": data.get("today_revenue", 0.0),
                        "week_locations": data.get("week_rentals", 0),
                        "week_revenue": data.get("week_revenue", 0.0),
                        "month_locations": data.get("month_rentals", 0),
                        "month_revenue": data.get("month_revenue", 0.0),
                    }
                    top_vehicles = resp_perf.json() if resp_perf.status_code == 200 else []
                    self._dashboard.refresh_data(overview, top_vehicles)
                    return
            except Exception as e:
                print("Dashboard API fetch failed, falling back to offline:", e)
        overview = { "total_vehicles": 0, "available": 0, "rented": 0, "reserved": 0, "maintenance": 0, "active_maintenances": 0, "day_locations": 0, "today_revenue": 0.0, "week_locations": 0, "week_revenue": 0.0, "month_locations": 0, "month_revenue": 0.0 }
        self._dashboard.refresh_data(overview, [])
    def _run_sync(self):
        """Execute non-blocking automatic background sync cycle."""
        engine = SyncEngine(self._device_id, self._access_token, self._refresh_token)
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            is_connected = loop.run_until_complete(engine.check_connection())

            if is_connected:
                was_offline = not self._is_online
                self._is_online = True
                if self._access_token:
                    report = loop.run_until_complete(engine.sync())
                    if engine._access_token != self._access_token:
                        self._access_token = engine._access_token
                        self._refresh_token = engine._refresh_token
                        if self._api:
                            self._api.set_tokens(self._access_token, self._refresh_token)
                    push_res = report.get("push", {})
                    pull_res = report.get("pull", {})
                    if push_res.get("pushed", 0) > 0 or len(pull_res.get("items", [])) > 0:
                        self._load_vehicles_from_local()
                        self._refresh_dashboard()
                        self._reservations.refresh_data()
                        self._maintenance.refresh_data()

                status_text = t("sync.reconnected") if was_offline else t("sync.online")
                self.statusBar().showMessage(status_text, 4000)
            else:
                self._is_online = False
                self.statusBar().showMessage(t("sync.offline"))

            loop.close()
        except Exception as e:
            self._is_online = False
            self.statusBar().showMessage(t("sync.offline"))
            logger.debug("Sync cycle note: %s", e)

    def _on_refresh_clicked(self):
        self._refresh_btn.setText(t("topbar.refreshing"))
        self._run_sync()
        self._load_vehicles_from_local()
        self._refresh_dashboard()
        self._reservations.refresh_data()
        self._maintenance.refresh_data()
        self._refresh_btn.setText(t("topbar.updated"))
        QTimer.singleShot(2000, lambda: self._refresh_btn.setText(t("topbar.refresh")))

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

    def _create_vehicle(self, data: dict):
        session = get_local_session()
        try:
            vehicle_id = data.get("id") or str(uuid.uuid4())
            data["id"] = vehicle_id
            now_iso = datetime.now(timezone.utc).isoformat()

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
            queue = SyncQueue(session, self._device_id, self._user_data.get("user_id"))
            queue.enqueue("vehicle", vehicle_id, "CREATE", data)

            session.commit()
            self._load_vehicles_from_local()
            self._refresh_dashboard()
            self._run_sync()
            self.statusBar().showMessage(t("vehicles.form_success_create"), 3000)
        except Exception as e:
            session.rollback()
            QMessageBox.critical(self, t("common.error"), f"Erreur lors de l'ajout: {e}")
        except Exception as e:
            print("ERROR IN LOAD:", e)
        finally:
            session.close()

    def _on_edit_vehicle(self, vehicle_id: str):
        from app.ui.vehicles.vehicle_hover_preview import get_hover_preview
        get_hover_preview().hide_preview()

        session = get_local_session()
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
            print("ERROR IN LOAD:", e)
        finally:
            session.close()

        dialog = VehicleFormDialog(vehicle_data=v_data, api_client=self._api, parent=self)
        dialog.saved.connect(self._update_vehicle)
        dialog.exec()

    def _update_vehicle(self, data: dict):
        session = get_local_session()
        try:
            vehicle_id = data.get("id")
            v = session.query(LocalVehicle).filter_by(id=vehicle_id).first()
            if not v:
                return

            now_iso = datetime.now(timezone.utc).isoformat()
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
            queue = SyncQueue(session, self._device_id, self._user_data.get("user_id"))
            queue.enqueue("vehicle", vehicle_id, "UPDATE", data)

            session.commit()
            self._load_vehicles_from_local()
            self._refresh_dashboard()
            self._run_sync()
            self.statusBar().showMessage(t("vehicles.form_success_edit"), 3000)
        except Exception as e:
            session.rollback()
            logger.error("Erreur lors de la modification: %s", e, exc_info=True)
            error_msg = str(e).lower()
            if "readonly database" in error_msg:
                user_msg = "Impossible d'enregistrer les modifications. Le dossier de données est en lecture seule."
            else:
                user_msg = f"Une erreur technique est survenue lors de la modification. Consultez les journaux pour plus de détails."
            QMessageBox.critical(self, t("common.error"), user_msg)
        except Exception as e:
            print("ERROR IN LOAD:", e)
        finally:
            session.close()

    def _on_delete_vehicle(self, vehicle_id: str):
        session = get_local_session()
        try:
            v = session.query(LocalVehicle).filter_by(id=vehicle_id).first()
            if not v:
                return

            reply = QMessageBox.question(
                self,
                t("vehicles.confirm_delete_title"),
                t("vehicles.confirm_delete_msg", reg=v.registration),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                from app.sync.queue import SyncQueue
                queue = SyncQueue(session, self._device_id, self._user_data.get("user_id"))
                queue.enqueue("vehicle", vehicle_id, "DELETE", {"id": vehicle_id})

                session.delete(v)
                session.commit()
                self._load_vehicles_from_local()
                self._refresh_dashboard()
                self._run_sync()
        except Exception as e:
            session.rollback()
            logger.error("Erreur lors de la suppression: %s", e, exc_info=True)
            error_msg = str(e).lower()
            if "readonly database" in error_msg:
                user_msg = "Impossible d'enregistrer les modifications. Le dossier de données est en lecture seule."
            else:
                user_msg = f"Une erreur technique est survenue lors de la suppression. Consultez les journaux pour plus de détails."
            QMessageBox.critical(self, t("common.error"), user_msg)
        except Exception as e:
            print("ERROR IN LOAD:", e)
        finally:
            session.close()

    def _on_maintenance_requested(self, vehicle_id: str):
        session = get_local_session()
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
            print("ERROR IN LOAD:", e)
        finally:
            session.close()

        from app.ui.maintenance.maintenance_list import MaintenanceFormDialog
        dialog = MaintenanceFormDialog(v_dict, self)
        dialog.saved.connect(self._create_maintenance_record)
        dialog.exec()

    def _save_maintenance(self, data: dict):
        self._create_maintenance_record(data)

    def _create_maintenance_record(self, data: dict):
        session = get_local_session()
        try:
            m_id = str(uuid.uuid4())
            now_iso = datetime.now(timezone.utc).isoformat()

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
                part = LocalMaintenancePart(
                    id=str(uuid.uuid4()),
                    maintenance_id=m_id,
                    part_name=p["part_name"],
                    quantity=p["quantity"],
                    unit_price=p["unit_price"],
                    total_price=p["total_price"],
                    notes=p.get("notes"),
                    created_at=now_iso,
                    updated_at=now_iso
                )
                session.add(part)

            vehicle = session.query(LocalVehicle).filter_by(id=data["vehicle_id"]).first()
            if vehicle:
                vehicle.status = "MAINTENANCE"
                vehicle.updated_at = now_iso
                vehicle.version += 1

            from app.sync.queue import SyncQueue
            queue = SyncQueue(session, self._device_id, self._user_data.get("user_id"))
            data["id"] = m_id
            queue.enqueue("maintenance", m_id, "CREATE", data)
            if vehicle:
                queue.enqueue("vehicle", vehicle.id, "UPDATE", {"id": vehicle.id, "status": "MAINTENANCE"})

            session.commit()

            if self._current_view == "maintenance":
                self._views["maintenance"].refresh_data()
            if self._current_view == "dashboard":
                self._views["dashboard"].refresh_data()
            if self._current_view == "vehicles":
                self._views["vehicles"].refresh_data()
        except Exception as e:
            print("Error creating maintenance:", e)
        finally:
            session.close()

    def _on_reservation_updated(self):
        self._load_vehicles_from_local()
        self._refresh_dashboard()
        self._run_sync()

    def _on_maintenance_updated(self):
        self._load_vehicles_from_local()
        self._refresh_dashboard()
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
