"""
Vehicle list widget — shows all vehicles as modern cards with search, status filters, and price filters.
Includes premium hover detail preview on mouse hover and refined ATELIER BERLIN LOCATION CAR styling.
Full French and Arabic translation and RTL layout support.
"""
import os
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QPushButton, QLineEdit, QComboBox, QLabel, QDialog, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QEvent, QPoint
from PySide6.QtGui import QFont, QColor, QPixmap, QPainter, QPainterPath, QCursor
from app.i18n import t, is_rtl
from app.config import API_BASE_URL
from app.ui.vehicles.vehicle_hover_preview import get_hover_preview, get_existing_hover_preview
import shiboken6

def _safely_cancel_hover():
    preview = get_existing_hover_preview()
    if preview is not None and not shiboken6.isValid(preview):
        return
    if preview is not None:
        try:
            preview.cancel_and_hide()
        except RuntimeError:
            pass



class VehicleDetailModal(QDialog):
    """View details of a vehicle including multi-photo gallery, specs, and document statuses."""
    def __init__(self, vehicle: dict, parent=None):
        super().__init__(parent)
        self.vehicle = vehicle
        brand = vehicle.get('brand', '')
        model = vehicle.get('model', '')
        full_name = f"{brand} {model}".strip()
        self.setWindowTitle(t("vehicles.modal_details_title", name=full_name))
        self.setMinimumWidth(600)
        self._img_connected = False
        self._selected_photo_idx = 0

        # Parse all image URLs
        raw = vehicle.get("image_url") or ""
        self._image_urls = [u.strip() for u in raw.split(",") if u.strip()] if raw else []
        self._loaded_pixmaps = {}  # url -> QPixmap

        self._setup_ui()

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        # ── PHOTO GALLERY SECTION ──
        if self._image_urls:
            # Large main photo
            self._main_photo = QLabel()
            self._main_photo.setFixedSize(550, 280)
            self._main_photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._main_photo.setStyleSheet("""
                border-radius: 10px;
                background-color: #F2F5F0;
                border: 1px solid #D5DDD3;
            """)
            layout.addWidget(self._main_photo, alignment=Qt.AlignmentFlag.AlignCenter)

            # Navigation + thumbnail row
            if len(self._image_urls) > 1:
                nav_row = QHBoxLayout()
                nav_row.setSpacing(8)

                prev_btn = QPushButton("◀")
                prev_btn.setFixedSize(32, 32)
                prev_btn.setFont(QFont("Hanken Grotesk", 12))
                prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                prev_btn.setStyleSheet("""
                    QPushButton { background: #E8F3E6; border: 1px solid #B5CDB0; border-radius: 6px; color: #1E4D38; }
                    QPushButton:hover { background: #D4E8D0; }
                """)
                prev_btn.clicked.connect(lambda: self._navigate_photo(-1))
                nav_row.addWidget(prev_btn)

                # Thumbnails
                self._thumb_labels = []
                for i, url in enumerate(self._image_urls):
                    thumb_lbl = QLabel()
                    thumb_lbl.setFixedSize(64, 44)
                    thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    thumb_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
                    thumb_lbl.setStyleSheet("""
                        border-radius: 6px;
                        background-color: #F2F5F0;
                        border: 1px solid #D5DDD3;
                    """)
                    thumb_lbl.mousePressEvent = lambda ev, idx=i: self._select_photo(idx)
                    nav_row.addWidget(thumb_lbl)
                    self._thumb_labels.append(thumb_lbl)

                next_btn = QPushButton("▶")
                next_btn.setFixedSize(32, 32)
                next_btn.setFont(QFont("Hanken Grotesk", 12))
                next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                next_btn.setStyleSheet("""
                    QPushButton { background: #E8F3E6; border: 1px solid #B5CDB0; border-radius: 6px; color: #1E4D38; }
                    QPushButton:hover { background: #D4E8D0; }
                """)
                next_btn.clicked.connect(lambda: self._navigate_photo(1))
                nav_row.addWidget(next_btn)

                nav_row.addStretch()
                layout.addLayout(nav_row)

                # Photo counter
                self._photo_counter = QLabel(f"1 / {len(self._image_urls)}")
                self._photo_counter.setFont(QFont("Hanken Grotesk", 9))
                self._photo_counter.setStyleSheet("color: #6B7264;")
                self._photo_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(self._photo_counter)

            # Load all images
            from app.services.image_cache import get_image_cache
            cache = get_image_cache()
            cache.image_loaded.connect(self._on_image_loaded)
            self._img_connected = True
            for url in self._image_urls:
                full = f"{self.vehicle.get('id')}_{cache._build_url(url)}"
                self._loaded_pixmaps[full] = None  # placeholder
                cache.get_image(url, str(self.vehicle.get('id')))

        else:
            # No photos
            no_photo = QLabel("🚗")
            no_photo.setFixedSize(140, 95)
            no_photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_photo.setFont(QFont("Hanken Grotesk", 32))
            no_photo.setStyleSheet("border-radius: 8px; background-color: #F2F5F0; border: 1px solid #D5DDD3;")
            layout.addWidget(no_photo, alignment=Qt.AlignmentFlag.AlignCenter)

        # ── VEHICLE HEADER INFO ──
        header = QHBoxLayout()
        header.setSpacing(12)
        title_box = QVBoxLayout()
        name = QLabel(f"{self.vehicle.get('brand', '')} {self.vehicle.get('model', '')}".strip())
        name.setFont(QFont("Libre Caslon Text", 18, QFont.Weight.Bold))
        name.setStyleSheet("color: #1E4D38;")

        reg_parts = [str(self.vehicle.get('registration', ''))]
        if self.vehicle.get('year'):
            reg_parts.append(str(self.vehicle.get('year')))
        if self.vehicle.get('fuel_type'):
            fuel_label = t(f"fuel.{self.vehicle.get('fuel_type')}")
            reg_parts.append(fuel_label)
        reg = QLabel(" · ".join(reg_parts))
        reg.setFont(QFont("Hanken Grotesk", 11))
        reg.setStyleSheet("color: #6B7264;")

        price_val = self.vehicle.get('daily_rental_price', 0)
        curr = "DH" if not is_rtl() else "د.م"
        price = QLabel(f"{price_val:.0f} {curr} {t('vehicles.per_day')}" if isinstance(price_val, (int, float)) else f"{price_val} {curr} {t('vehicles.per_day')}")
        price.setFont(QFont("Hanken Grotesk", 12, QFont.Weight.Bold))
        price.setStyleSheet("color: #1E4D38;")

        title_box.addWidget(name)
        title_box.addWidget(reg)
        title_box.addWidget(price)
        header.addLayout(title_box)
        header.addStretch()
        layout.addLayout(header)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("color: #E2E5DE;")
        layout.addWidget(div)

        # Specifications
        specs_lbl = QLabel(t("vehicles.modal_specs"))
        specs_lbl.setFont(QFont("Hanken Grotesk", 12, QFont.Weight.Bold))
        specs_lbl.setStyleSheet("color: #1E4D38;")
        layout.addWidget(specs_lbl)

        specs_box = QVBoxLayout()
        specs = []
        if self.vehicle.get("vin"):
            specs.append((t("vehicles.modal_vin"), self.vehicle.get("vin")))
        if self.vehicle.get("transmission"):
            trans_lbl = t(f"transmission.{self.vehicle.get('transmission')}")
            specs.append((t("vehicles.modal_trans"), trans_lbl))
        if self.vehicle.get("current_mileage") is not None:
            unit = "km" if not is_rtl() else "كم"
            specs.append((t("vehicles.modal_mileage"), f"{self.vehicle.get('current_mileage'):,} {unit}".replace(",", " ")))
        if self.vehicle.get("color"):
            specs.append((t("vehicles.modal_color"), self.vehicle.get("color")))
        if self.vehicle.get("status"):
            specs.append((t("vehicles.modal_status"), t(f"status.{self.vehicle.get('status')}")))

        for k, v in specs:
            row = QHBoxLayout()
            lbl_k = QLabel(k)
            lbl_k.setFont(QFont("Hanken Grotesk", 10))
            lbl_k.setStyleSheet("color: #6B7264;")
            lbl_v = QLabel(str(v))
            lbl_v.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
            lbl_v.setStyleSheet("color: #2D3748;")
            row.addWidget(lbl_k)
            row.addStretch()
            row.addWidget(lbl_v)
            specs_box.addLayout(row)
        layout.addLayout(specs_box)

        # Documents & Expiration
        from datetime import datetime, timedelta
        today_str = datetime.now().date().isoformat()
        thirty_str = (datetime.now().date() + timedelta(days=30)).isoformat()

        docs = [
            (t("vehicles.doc_assurance"), self.vehicle.get("assurance_expiry")),
            (t("vehicles.doc_vignette"), self.vehicle.get("vignette_expiry")),
            (t("vehicles.doc_visite"), self.vehicle.get("visite_technique_expiry")),
            (t("vehicles.doc_carte_grise"), self.vehicle.get("carte_grise_expiry")),
            (self.vehicle.get("autres_label") or "Autre Document", self.vehicle.get("autres_expiry"))
        ]

        has_docs = any(expiry for _, expiry in docs)
        if has_docs:
            div2 = QFrame()
            div2.setFrameShape(QFrame.Shape.HLine)
            div2.setStyleSheet("color: #E2E5DE;")
            layout.addWidget(div2)
            doc_lbl = QLabel(t("vehicles.modal_docs"))
            doc_lbl.setFont(QFont("Hanken Grotesk", 12, QFont.Weight.Bold))
            doc_lbl.setStyleSheet("color: #1E4D38;")
            layout.addWidget(doc_lbl)

            for doc_name, expiry in docs:
                if not expiry:
                    continue
                row = QHBoxLayout()
                lbl_doc_name = QLabel(doc_name)
                lbl_doc_name.setFont(QFont("Hanken Grotesk", 10))
                lbl_doc_name.setStyleSheet("color: #6B7264;")
                row.addWidget(lbl_doc_name)
                row.addStretch()

                expiry_date_str = str(expiry).split("T")[0]
                status_lbl = QLabel(expiry_date_str)
                status_lbl.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
                if expiry_date_str < today_str:
                    status_lbl.setText(f"{expiry_date_str} ({t('vehicles.doc_expired')})")
                    status_lbl.setStyleSheet("color: #DC2626;")
                elif expiry_date_str <= thirty_str:
                    status_lbl.setText(f"{expiry_date_str} ({t('vehicles.doc_soon')})")
                    status_lbl.setStyleSheet("color: #D97706;")
                else:
                    status_lbl.setStyleSheet("color: #16A34A;")
                row.addWidget(status_lbl)
                layout.addLayout(row)

        layout.addStretch()
        close_btn = QPushButton(t("common.close"))
        close_btn.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _navigate_photo(self, direction: int):
        """Navigate to previous (-1) or next (+1) photo."""
        if not self._image_urls:
            return
        new_idx = (self._selected_photo_idx + direction) % len(self._image_urls)
        self._select_photo(new_idx)

    def _select_photo(self, idx: int):
        """Select a photo by index and update the main display."""
        self._selected_photo_idx = idx
        self._update_main_photo()
        self._update_thumbnail_borders()
        if hasattr(self, "_photo_counter"):
            self._photo_counter.setText(f"{idx + 1} / {len(self._image_urls)}")

    def _update_main_photo(self):
        """Update the large main photo display."""
        if not self._image_urls or self._selected_photo_idx >= len(self._image_urls):
            return
        url = self._image_urls[self._selected_photo_idx]
        from app.services.image_cache import get_image_cache
        full_url = f"{self.vehicle.get('id')}_{get_image_cache()._build_url(url)}"
        pix = self._loaded_pixmaps.get(full_url)
        if pix and not pix.isNull():
            self._set_main_pixmap(pix)
        else:
            self._main_photo.setText("⏳")
            self._main_photo.setFont(QFont("Hanken Grotesk", 20))

    def _update_thumbnail_borders(self):
        """Highlight the selected thumbnail."""
        if not hasattr(self, "_thumb_labels"):
            return
        for i, lbl in enumerate(self._thumb_labels):
            if i == self._selected_photo_idx:
                lbl.setStyleSheet("""
                    border-radius: 6px;
                    background-color: #F2F5F0;
                    border: 2px solid #1E4D38;
                """)
            else:
                lbl.setStyleSheet("""
                    border-radius: 6px;
                    background-color: #F2F5F0;
                    border: 1px solid #D5DDD3;
                """)

    def _set_main_pixmap(self, pixmap: QPixmap):
        """Scale and set the pixmap on the main photo label with rounded corners."""
        target_size = self._main_photo.size()
        scaled = pixmap.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        rounded = QPixmap(target_size)
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, target_size.width(), target_size.height(), 10, 10)
        painter.setClipPath(path)
        x = (target_size.width() - scaled.width()) // 2
        y = (target_size.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()
        self._main_photo.setPixmap(rounded)
        self._main_photo.setText("")

    def _on_image_loaded(self, url: str, pixmap: QPixmap):
        if url not in self._loaded_pixmaps or pixmap.isNull():
            return
        self._loaded_pixmaps[url] = pixmap

        # Find which index this URL corresponds to
        from app.services.image_cache import get_image_cache
        cache = get_image_cache()
        for i, img_url in enumerate(self._image_urls):
            expected = f"{self.vehicle.get('id')}_{cache._build_url(img_url)}"
            if expected == url:
                # Update thumbnail
                if hasattr(self, "_thumb_labels") and i < len(self._thumb_labels):
                    scaled = pixmap.scaled(64, 44, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    self._thumb_labels[i].setPixmap(scaled)
                # Update main photo if this is the selected one
                if i == self._selected_photo_idx and hasattr(self, "_main_photo"):
                    self._set_main_pixmap(pixmap)
                break

    def closeEvent(self, event):
        if getattr(self, "_img_connected", False):
            from app.services.image_cache import get_image_cache
            try:
                get_image_cache().image_loaded.disconnect(self._on_image_loaded)
            except Exception:
                pass
            self._img_connected = False
        super().closeEvent(event)


class VehicleRow(QFrame):
    """
    A polished table row representing a vehicle with large thumbnail,
    clear hierarchy, hover detail preview, and action buttons.

    The hover preview is triggered ONLY when the cursor is over the vehicle
    info area (thumbnail, name, registration, year, price, status badge).
    Hovering over action buttons (View, Edit, Delete) does NOT trigger
    the preview and actively cancels any pending preview.
    """
    edit_requested = Signal(str)
    maintenance_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, data: dict, user_role: str = "EMPLOYEE", parent=None):
        super().__init__(parent)
        self.setObjectName("vehicleRow")
        self.setProperty("class", "surface")
        self._data = data
        self._user_role = user_role
        self.setFixedHeight(76)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._is_hovered = False
        self._on_action_btn = False  # True when cursor is on an action button
        self._img_connected = False
        self._action_buttons = []  # Will hold references to action QPushButtons

        self.setStyleSheet("""
            #vehicleRow {
                background-color: #FFFFFF;
                border: 1px solid #E2E5DE;
                border-radius: 8px;
                margin: 2px 0px;
            }
            #vehicleRow:hover {
                background-color: #F8FAF7;
                border: 1px solid #B5CDB0;
            }
        """)

        # Hover debounce timer (200ms)


        self._setup_ui()

        # Install event filter on row and all children EXCEPT action buttons
        self.installEventFilter(self)
        for child in self.findChildren(QLabel):
            child.installEventFilter(self)
        # Install a SEPARATE event filter on action buttons to suppress hover preview
        for btn in self._action_buttons:
            btn.installEventFilter(self)

    def _on_mouse_enter(self):
        """Called when mouse enters the vehicle info area (not action buttons)."""
        if self._on_action_btn:
            return  # Cursor is on an action button — do not trigger preview
        if not self._is_hovered:
            self._is_hovered = True
            get_hover_preview().on_row_enter(self, self._data)

    def _on_mouse_leave(self):
        if self._is_hovered:
            self._is_hovered = False
            get_hover_preview().on_row_leave(self, self._data)

    def _is_action_button(self, obj):
        """Check if obj is one of the action buttons (View, Edit, Delete)."""
        return obj in self._action_buttons

    def eventFilter(self, obj, ev):
        # Handle action button enter/leave specially
        if self._is_action_button(obj):
            if ev.type() in (QEvent.Type.Enter, QEvent.Type.HoverEnter):
                self._on_action_btn = True
                # Cancel any visible preview when hovering action buttons
                _safely_cancel_hover()
                return False  # Let the button handle its own event
            elif ev.type() in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
                self._on_action_btn = False
                # Do NOT re-trigger hover when leaving a button but still in the row
                return False
            return False

        # Normal info area children (QLabel, etc.)
        if ev.type() in (QEvent.Type.Enter, QEvent.Type.HoverEnter):
            self._on_mouse_enter()
        elif ev.type() in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
                self._on_mouse_leave()
        return super().eventFilter(obj, ev)

    def enterEvent(self, event):
        if not self._on_action_btn:
            self._on_mouse_enter()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._on_action_btn = False
            self._on_mouse_leave()
        super().leaveEvent(event)



    def cleanup(self):

        if getattr(self, "_img_connected", False):
            from app.services.image_cache import get_image_cache
            try:
                get_image_cache().image_loaded.disconnect(self._on_image_loaded)
            except Exception:
                pass
            self._img_connected = False

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        data = self._data
        status = data.get("status", "AVAILABLE")

        # 1. Large Thumbnail (84x56) + Brand/Model Hierarchy (Stretch 3)
        car_layout = QHBoxLayout()
        car_layout.setSpacing(12)

        self._thumb = QLabel()
        self._thumb.setFixedSize(84, 56)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet("""
            border-radius: 8px;
            background-color: #F2F5F0;
            border: 1px solid #D5DDD3;
        """)

        img_url = data.get("image_url") or ""
        # Use first photo if multiple (comma-separated)
        if "," in img_url:
            img_url = img_url.split(",")[0].strip()
        if img_url:
            from app.services.image_cache import get_image_cache
            cache = get_image_cache()
            self._current_img_url = f"{self._data.get('id')}_{cache._build_url(img_url)}"
            cache.image_loaded.connect(self._on_image_loaded)
            self._img_connected = True
            cache.get_image(img_url, str(self._data.get('id')))
        else:
            self._thumb.setText("🚗")
            self._thumb.setFont(QFont("Hanken Grotesk", 22))

        car_layout.addWidget(self._thumb)

        v_info = QVBoxLayout()
        v_info.setSpacing(3)
        v_info.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        brand_model_text = f"{data.get('brand', '')} {data.get('model', '')}".strip() or t("sidebar.vehicles")
        name = QLabel(brand_model_text)
        name.setFont(QFont("Libre Caslon Text", 13, QFont.Weight.Bold))
        name.setStyleSheet("color: #1E4D38;")

        sub_parts = []
        if data.get('color'):
            sub_parts.append(str(data.get('color')))
        if data.get('fuel_type'):
            fuel_label = t(f"fuel.{data.get('fuel_type')}")
            sub_parts.append(fuel_label)
        sub_text = " · ".join(sub_parts) if sub_parts else "Standard"

        sub_lbl = QLabel(sub_text)
        sub_lbl.setFont(QFont("Hanken Grotesk", 10))
        sub_lbl.setStyleSheet("color: #6B7264;")

        v_info.addWidget(name)
        v_info.addWidget(sub_lbl)
        car_layout.addLayout(v_info)
        layout.addLayout(car_layout, 3)

        # 2. Immatriculation (Stretch 2)
        reg_box = QVBoxLayout()
        reg_box.setSpacing(2)
        reg_box.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        reg = QLabel(str(data.get('registration', '—')))
        reg.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.Bold))
        reg.setStyleSheet("color: #2D3748;")
        reg_box.addWidget(reg)
        layout.addLayout(reg_box, 2)

        # 3. Année (Stretch 1)
        year_box = QVBoxLayout()
        year_box.setSpacing(2)
        year_box.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        year = QLabel(str(data.get('year', '—')))
        year.setFont(QFont("Hanken Grotesk", 11))
        year.setStyleSheet("color: #4A5568;")
        year_box.addWidget(year)
        layout.addLayout(year_box, 1)

        # 4. Prix/Jour (DH) (Stretch 1)
        price_box = QVBoxLayout()
        price_box.setSpacing(1)
        price_box.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        price_val = data.get('daily_rental_price', 0)
        curr = "DH" if not is_rtl() else "د.م"
        try:
            p_formatted = f"{float(price_val):.0f} {curr}"
        except (ValueError, TypeError):
            p_formatted = f"{price_val} {curr}"

        price = QLabel(p_formatted)
        price.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.Bold))
        price.setStyleSheet("color: #1E4D38;")

        price_sub = QLabel(t("vehicles.per_day"))
        price_sub.setFont(QFont("Hanken Grotesk", 9))
        price_sub.setStyleSheet("color: #8C9688;")

        price_box.addWidget(price)
        price_box.addWidget(price_sub)
        layout.addLayout(price_box, 1)

        # 5. Statut Badge (Stretch 2)
        status_box = QVBoxLayout()
        status_box.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        badge_text = t(f"status.{status}")
        badge = QLabel(badge_text)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedHeight(26)
        badge.setMinimumWidth(110)
        badge.setFont(QFont("Hanken Grotesk", 9, QFont.Weight.Bold))

        if status == "AVAILABLE":
            badge.setStyleSheet("""
                background-color: #E8F3E6;
                color: #235821;
                border: 1px solid #C4DFC0;
                border-radius: 13px;
                padding: 0px 8px;
            """)
        elif status == "RESERVED":
            badge.setStyleSheet("""
                background-color: #FEF3C7;
                color: #92400E;
                border: 1px solid #FCD34D;
                border-radius: 13px;
                padding: 0px 8px;
            """)
        elif status == "MAINTENANCE":
            badge.setStyleSheet("""
                background-color: #FEE2E2;
                color: #991B1B;
                border: 1px solid #FCA5A5;
                border-radius: 13px;
                padding: 0px 8px;
            """)
        else:
            badge.setStyleSheet("""
                background-color: #E0E7FF;
                color: #3730A3;
                border: 1px solid #C7D2FE;
                border-radius: 13px;
                padding: 0px 8px;
            """)

        status_box.addWidget(badge)
        layout.addLayout(status_box, 2)

        # 6. Polished Action Buttons: View, Edit, Delete (Stretch 1)
        act_box = QHBoxLayout()
        act_box.setSpacing(8)
        act_box.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # View Button (👁)
        view_btn = QPushButton("👁")
        view_btn.setObjectName("actionViewBtn")
        view_btn.setFixedSize(36, 36)
        view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        view_btn.setToolTip(t("vehicles.view_tooltip"))
        view_btn.setFont(QFont("Segoe UI Emoji", 14))
        view_btn.setStyleSheet("""
            QPushButton#actionViewBtn {
                background-color: #F0F4EF;
                border: 1px solid #D5DFD3;
                border-radius: 8px;
                color: #2D5233;
                padding: 0px;
            }
            QPushButton#actionViewBtn:hover {
                background-color: #E0EBDD;
                border: 1px solid #B7CBB3;
            }
            QPushButton#actionViewBtn:pressed {
                background-color: #D0DEC9;
            }
        """)
        view_btn.clicked.connect(self._show_details)
        act_box.addWidget(view_btn)

        # Edit Button (✏)
        edit_btn = QPushButton("✏")
        edit_btn.setObjectName("actionEditBtn")
        edit_btn.setFixedSize(36, 36)
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.setToolTip(t("vehicles.edit_tooltip"))
        edit_btn.setFont(QFont("Segoe UI Emoji", 14))
        edit_btn.setStyleSheet("""
            QPushButton#actionEditBtn {
                background-color: #F4F6F8;
                border: 1px solid #DDE2E6;
                border-radius: 8px;
                color: #334155;
                padding: 0px;
            }
            QPushButton#actionEditBtn:hover {
                background-color: #E2E8F0;
                border: 1px solid #CBD5E1;
            }
            QPushButton#actionEditBtn:pressed {
                background-color: #CBD5E1;
            }
            QPushButton#actionEditBtn:disabled {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                color: #CBD5E1;
            }
        """)
        if self._user_role in ("ADMIN", "MANAGER"):
            edit_btn.clicked.connect(self._on_edit_clicked)
        else:
            edit_btn.setEnabled(False)
        act_box.addWidget(edit_btn)

        # Delete Button (🗑)
        del_btn = QPushButton("🗑")
        del_btn.setObjectName("actionDelBtn")
        del_btn.setFixedSize(36, 36)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setToolTip(t("vehicles.delete_tooltip"))
        del_btn.setFont(QFont("Segoe UI Emoji", 14))
        del_btn.setStyleSheet("""
            QPushButton#actionDelBtn {
                background-color: #FEF2F2;
                border: 1px solid #FECACA;
                border-radius: 8px;
                color: #DC2626;
                padding: 0px;
            }
            QPushButton#actionDelBtn:hover {
                background-color: #FEE2E2;
                border: 1px solid #FCA5A5;
            }
            QPushButton#actionDelBtn:pressed {
                background-color: #FECACA;
            }
            QPushButton#actionDelBtn:disabled {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                color: #CBD5E1;
            }
        """)
        if self._user_role == "ADMIN":
            del_btn.clicked.connect(self._on_delete_clicked)
        else:
            del_btn.setEnabled(False)
        act_box.addWidget(del_btn)

        # Register action buttons so the event filter can exclude them from hover preview
        self._action_buttons = [view_btn, edit_btn, del_btn]

        layout.addLayout(act_box, 1)

    def _on_edit_clicked(self):

        self._is_hovered = False
        _safely_cancel_hover()
        self.edit_requested.emit(self._data.get("id"))

    def _on_delete_clicked(self):

        self._is_hovered = False
        _safely_cancel_hover()
        self.delete_requested.emit(self._data.get("id"))

    def _show_details(self):
        # Hide hover preview immediately BEFORE opening detail modal
        self._is_hovered = False
        _safely_cancel_hover()
        
        # Load fresh data before displaying
        from app.database import get_local_session
        from app.models.vehicle import LocalVehicle
        session = get_local_session()
        fresh_data = dict(self._data)
        try:
            v = session.query(LocalVehicle).filter_by(id=self._data.get("id")).first()
            if v:
                fresh_data = {
                    "id": v.id, "brand": v.brand, "model": v.model, "year": v.year,
                    "color": v.color, "current_mileage": v.current_mileage, "fuel_type": v.fuel_type,
                    "transmission": v.transmission,
                    # EFFECTIVE status only — the canonical value already carried
                    # by the DomainStore-backed row (self._data). Never re-read
                    # the raw ``v.status`` column here: it can hold a MAINTENANCE
                    # hint set ahead of the maintenance window and would
                    # contradict the Vehicles list badge and the Dashboard.
                    "status": self._data.get("status", v.status),
                    "daily_rental_price": v.daily_rental_price,
                    "image_url": getattr(v, "image_url", None),
                    "registration_number": getattr(v, "registration_number", None),
                    "vin_number": getattr(v, "vin_number", None)
                }
        finally:
            session.close()
            
        modal = VehicleDetailModal(fresh_data, self.window())
        modal.exec()

    def _on_image_loaded(self, url: str, pixmap: QPixmap):
        if getattr(self, "_current_img_url", None) == url and not pixmap.isNull():
            target_size = self._thumb.size()
            scaled = pixmap.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )

            rounded = QPixmap(target_size)
            rounded.fill(Qt.GlobalColor.transparent)

            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(0, 0, target_size.width(), target_size.height(), 8, 8)
            painter.setClipPath(path)

            x = (target_size.width() - scaled.width()) // 2
            y = (target_size.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()

            self._thumb.setPixmap(rounded)
            self._thumb.setText("")


class VehicleListWidget(QWidget):
    """Vehicle listing with cards, search, status filter, and price filter."""
    vehicle_selected = Signal(str)
    maintenance_requested = Signal(str)
    add_requested = Signal()
    delete_requested = Signal(str)

    def __init__(self, user_role: str = "EMPLOYEE", parent=None):
        super().__init__(parent)
        self._user_role = user_role
        self._vehicles_data = []
        self._cards = []
        self._selected_price_filter = None
        self._setup_ui()

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header with Editorial Serif title
        header = QHBoxLayout()
        self._title_lbl = QLabel(t("vehicles.title"))
        self._title_lbl.setFont(QFont("Libre Caslon Text", 20, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet("color: #1E4D38;")
        header.addWidget(self._title_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()

        if self._user_role in ("ADMIN", "MANAGER"):
            self._add_btn = QPushButton(f"+ {t('vehicles.add')}")
            self._add_btn.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.Bold))
            self._add_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            self._add_btn.setMinimumWidth(240)
            self._add_btn.adjustSize()
            self._add_btn.clicked.connect(self.add_requested.emit)
            header.addWidget(self._add_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        else:
            self._add_btn = None
        layout.addLayout(header)

        # Search and status filter bar
        bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(t("vehicles.search"))
        self._search.setFixedHeight(36)
        self._search.setFont(QFont("Hanken Grotesk", 11))
        self._search.textChanged.connect(self._filter_cards)
        bar.addWidget(self._search, 3)

        self._status_filter = QComboBox()
        self._status_filter.addItem(t("vehicles.all_statuses"), "")
        for st in ["AVAILABLE", "RESERVED", "RENTED", "MAINTENANCE"]:
            self._status_filter.addItem(t(f"status.{st}"), st)
        self._status_filter.setFixedHeight(36)
        self._status_filter.setFont(QFont("Hanken Grotesk", 11))
        self._status_filter.currentIndexChanged.connect(self._filter_cards)
        bar.addWidget(self._status_filter, 1)
        layout.addLayout(bar)

        # ── PRICE FILTER BAR ──
        self._price_filter_layout = QHBoxLayout()
        self._price_filter_layout.setSpacing(8)

        self._lbl_price_title = QLabel(t("vehicles.price_label"))
        self._lbl_price_title.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
        self._lbl_price_title.setStyleSheet("color: #6B7264;")
        self._price_filter_layout.addWidget(self._lbl_price_title)

        self._price_buttons = {}
        curr = "DH" if not is_rtl() else "د.م"
        price_options = [
            (t("vehicles.price_all"), None),
            (f"250 {curr}", 250),
            (f"300 {curr}", 300),
            (f"400 {curr}", 400),
            (f"450 {curr}", 450),
            (f"500 {curr}", 500)
        ]

        for label, val in price_options:
            btn = QPushButton(f"[ {label} ]")
            btn.setFixedHeight(30)
            btn.setFont(QFont("Hanken Grotesk", 10))
            btn.setCheckable(True)
            if val is None:
                btn.setChecked(True)

            self._apply_price_btn_style(btn, btn.isChecked())
            btn.clicked.connect(lambda checked, v=val: self._on_price_filter_clicked(v))
            self._price_filter_layout.addWidget(btn)
            self._price_buttons[val] = btn

        self._price_filter_layout.addStretch()
        layout.addLayout(self._price_filter_layout)

        # Header row for table
        self._table_header = QWidget()
        self._table_header.setFixedHeight(36)
        self._table_header.setStyleSheet("background-color: #EDF0EA; border-radius: 6px;")
        h_layout = QHBoxLayout(self._table_header)
        h_layout.setContentsMargins(14, 0, 14, 0)
        h_layout.setSpacing(12)

        def make_hdr_lbl(txt):
            lbl = QLabel(txt)
            lbl.setFont(QFont("Hanken Grotesk", 9, QFont.Weight.Bold))
            lbl.setStyleSheet("color: #4B5243; letter-spacing: 0.5px;")
            return lbl

        self._hdr_lbl1 = make_hdr_lbl(t("vehicles.col_vehicle"))
        self._hdr_lbl2 = make_hdr_lbl(t("vehicles.col_reg"))
        self._hdr_lbl3 = make_hdr_lbl(t("vehicles.col_year"))
        self._hdr_lbl4 = make_hdr_lbl(t("vehicles.col_price"))
        self._hdr_lbl5 = make_hdr_lbl(t("vehicles.col_status"))
        self._hdr_lbl6 = make_hdr_lbl(t("vehicles.col_actions"))

        h_layout.addWidget(self._hdr_lbl1, 3)
        h_layout.addWidget(self._hdr_lbl2, 2)
        h_layout.addWidget(self._hdr_lbl3, 1)
        h_layout.addWidget(self._hdr_lbl4, 1)
        h_layout.addWidget(self._hdr_lbl5, 2)
        h_layout.addWidget(self._hdr_lbl6, 1)
        layout.addWidget(self._table_header)

        # Scroll Area for Rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.verticalScrollBar().valueChanged.connect(lambda: _safely_cancel_hover())
        scroll.horizontalScrollBar().valueChanged.connect(lambda: _safely_cancel_hover())

        self._cards_container = QWidget()

        self._grid = QVBoxLayout(self._cards_container)
        self._grid.setContentsMargins(0, 4, 0, 4)
        self._grid.setSpacing(6)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self._cards_container)
        layout.addWidget(scroll)

        # Vehicle count label
        self._count_label = QLabel("")
        self._count_label.setFont(QFont("Hanken Grotesk", 10))
        self._count_label.setStyleSheet("color: #6B7264;")
        layout.addWidget(self._count_label)

    def hideEvent(self, event):
        _safely_cancel_hover()
        super().hideEvent(event)

    def leaveEvent(self, event):
        _safely_cancel_hover()
        super().leaveEvent(event)

    def retranslate_ui(self):
        """Live update strings and reload vehicle rows when language changes."""
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)
        self._title_lbl.setText(t("vehicles.title"))
        if self._add_btn:
            self._add_btn.setText(f"+ {t('vehicles.add')}")
            self._add_btn.setMinimumWidth(240)
            self._add_btn.updateGeometry()
            self._add_btn.adjustSize()
        self._search.setPlaceholderText(t("vehicles.search"))

        # Status combo
        cur_status = self._status_filter.currentData()
        self._status_filter.blockSignals(True)
        self._status_filter.clear()
        self._status_filter.addItem(t("vehicles.all_statuses"), "")
        for st in ["AVAILABLE", "RESERVED", "RENTED", "MAINTENANCE"]:
            self._status_filter.addItem(t(f"status.{st}"), st)
        idx = self._status_filter.findData(cur_status)
        if idx >= 0:
            self._status_filter.setCurrentIndex(idx)
        self._status_filter.blockSignals(False)

        # Price labels
        self._lbl_price_title.setText(t("vehicles.price_label"))
        curr = "DH" if not is_rtl() else "د.م"
        price_options = [
            (t("vehicles.price_all"), None),
            (f"250 {curr}", 250),
            (f"300 {curr}", 300),
            (f"400 {curr}", 400),
            (f"450 {curr}", 450),
            (f"500 {curr}", 500)
        ]
        for label, val in price_options:
            if val in self._price_buttons:
                self._price_buttons[val].setText(f"[ {label} ]")

        # Table header labels
        self._hdr_lbl1.setText(t("vehicles.col_vehicle"))
        self._hdr_lbl2.setText(t("vehicles.col_reg"))
        self._hdr_lbl3.setText(t("vehicles.col_year"))
        self._hdr_lbl4.setText(t("vehicles.col_price"))
        self._hdr_lbl5.setText(t("vehicles.col_status"))
        self._hdr_lbl6.setText(t("vehicles.col_actions"))

        # Re-render rows with updated localization
        self.load_vehicles(self._vehicles_data)

    def _apply_price_btn_style(self, btn: QPushButton, is_selected: bool):
        if is_selected:
            btn.setProperty("class", "primary")
        else:
            btn.setProperty("class", "")
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _on_price_filter_clicked(self, price_val):
        self._selected_price_filter = price_val
        for val, btn in self._price_buttons.items():
            is_active = (val == price_val)
            btn.setChecked(is_active)
            self._apply_price_btn_style(btn, is_active)
        self._filter_cards()

    def set_filter(self, text: str):
        self._search.setText(text)

    def load_vehicles(self, vehicles: list[dict]):
        """Populate the rows with vehicle data."""
        _safely_cancel_hover()
        self._vehicles_data = vehicles

        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                w = item.widget()
                if hasattr(w, "cleanup"):
                    w.cleanup()
                w.deleteLater()
        self._cards.clear()

        if not vehicles:
            empty_box = QWidget()
            e_layout = QVBoxLayout(empty_box)
            e_layout.setContentsMargins(0, 40, 0, 40)
            e_lbl = QLabel(t("vehicles.no_vehicles"))
            e_lbl.setFont(QFont("Hanken Grotesk", 13))
            e_lbl.setStyleSheet("color: #6B7264;")
            e_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e_layout.addWidget(e_lbl)
            self._grid.addWidget(empty_box)
        else:
            for v in vehicles:
                card = VehicleRow(v, self._user_role)
                card.edit_requested.connect(self.vehicle_selected.emit)
                card.maintenance_requested.connect(self.maintenance_requested.emit)
                card.delete_requested.connect(self.delete_requested.emit)
                self._grid.addWidget(card)
                self._cards.append((card, v))

        self._count_label.setText(t("vehicles.count_total", count=len(vehicles)))
        self._filter_cards()

    def _filter_cards(self):
        _safely_cancel_hover()
        search_text = self._search.text().lower()
        status_filter = self._status_filter.currentData()
        price_filter = self._selected_price_filter

        visible_count = 0

        for card, data in self._cards:
            match_search = True
            if search_text:
                full_text = f"{data.get('brand','')} {data.get('model','')} {data.get('registration','')} {data.get('year','')}".lower()
                if search_text not in full_text:
                    match_search = False

            match_status = True
            if status_filter and data.get("status") != status_filter:
                match_status = False

            match_price = True
            if price_filter is not None:
                v_price = float(data.get("daily_rental_price") or 0)
                if abs(v_price - price_filter) > 0.5:
                    match_price = False

            if match_search and match_status and match_price:
                card.show()
                visible_count += 1
            else:
                card.hide()

        self._count_label.setText(t("vehicles.count_label", count=visible_count))
