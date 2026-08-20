"""
Premium Vehicle Hover Detail Preview for Desktop PySide6.
Displays detailed vehicle specifications, real photo, pricing, and status on hover.
Fully localized for French and Arabic with RTL layout.

Key behaviors:
  - Preview appears directly adjacent to the hovered vehicle row.
  - Action buttons (View/Edit/Delete) do NOT trigger the preview.
  - Preview follows whichever row is currently hovered after a 200ms debounce.
  - User can move cursor from row → preview without it hiding.
  - Grace period of 180ms before hiding when cursor leaves both.
  - Never shown on edit/modification screens.
"""
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QApplication,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect
)
from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QPropertyAnimation, QEasingCurve
import shiboken6
from PySide6.QtGui import QFont, QPixmap, QColor, QPainter, QPainterPath, QCursor

from app.services.image_cache import get_image_cache
from app.i18n import t, is_rtl

logger = logging.getLogger(__name__)

_hover_preview_instance = None


def get_existing_hover_preview():
    """Return the singleton instance without creating it."""
    return _hover_preview_instance


def get_hover_preview():
    """Return the singleton instance of VehicleHoverPreview."""
    global _hover_preview_instance
    if _hover_preview_instance is None:
        _hover_preview_instance = VehicleHoverPreview()
    return _hover_preview_instance


class VehicleHoverPreview(QWidget):
    """
    Frameless, non-intrusive hover preview card for vehicles.
    Matches the ATELIER BERLIN LOCATION CAR / Pistache theme with RTL support.
    Dynamically positions itself next to the hovered row.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._current_vehicle = None
        self._current_vehicle_id = None
        self._current_img_url = None
        self._is_visible = False
        self._is_hovered = False

        self._pending_hover_vehicle_id = None
        self._pending_hover_row = None
        self._pending_vehicle_data = None

        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._on_show_timeout)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._check_and_hide)

        # 1. UI children (creates self.container)
        self._setup_ui()

        # Connect image cache signal
        try:
            get_image_cache().image_loaded.connect(self._on_image_loaded)
        except Exception as e:
            logger.debug("Failed to connect image_cache signal: %s", e)

        # 2. Graphics effect
        self._opacity_effect = QGraphicsOpacityEffect(self.container)
        self.container.setGraphicsEffect(self._opacity_effect)
        self._anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._anim.finished.connect(self._on_anim_finished)

        # 3. Final state
        self.hide()

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(0)

        self.container = QFrame()
        self.container.setObjectName("hoverPreviewContainer")
        self.container.setStyleSheet("""
            #hoverPreviewContainer {
                background-color: #FFFFFF;
                border: 1px solid #D5DDD3;
                border-radius: 12px;
            }
        """)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 16)
        container_layout.setSpacing(10)

        # Top Photo Banner
        self._photo = QLabel()
        self._photo.setFixedSize(382, 200)
        self._photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._photo.setStyleSheet("""
            border-top-left-radius: 11px;
            border-top-right-radius: 11px;
            background-color: #F2F5F0;
        """)
        container_layout.addWidget(self._photo)

        # Info Box
        self.info_layout = QVBoxLayout()
        self.info_layout.setContentsMargins(18, 4, 18, 0)
        self.info_layout.setSpacing(8)

        # Brand + Model Title
        self._name_lbl = QLabel()
        self._name_lbl.setFont(QFont("Libre Caslon Text", 16, QFont.Weight.Bold))
        self._name_lbl.setStyleSheet("color: #1E4D38;")
        self._name_lbl.setWordWrap(True)
        self.info_layout.addWidget(self._name_lbl)

        # Specs Rows Container
        self._specs_container = QVBoxLayout()
        self._specs_container.setSpacing(6)
        self.info_layout.addLayout(self._specs_container)

        container_layout.addLayout(self.info_layout)
        main_layout.addWidget(self.container)

    def retranslate_ui(self):
        """Update strings and layout direction on language change."""
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)
        if self._current_vehicle:
            self.set_vehicle(self._current_vehicle)

    def set_vehicle(self, vehicle: dict):
        """Populate the hover card with real vehicle data only."""
        self._current_vehicle = vehicle
        self._current_vehicle_id = vehicle.get("id")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        # 1. Image — use first URL if comma-separated
        img_url = vehicle.get("image_url") or ""
        if "," in img_url:
            img_url = img_url.split(",")[0].strip()
        if img_url:
            cache = get_image_cache()
            self._current_img_url = f"{self._current_vehicle_id}_{cache._build_url(img_url)}"
            self._photo.clear()
            self._photo.setStyleSheet("""
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
                background-color: #F2F5F0;
            """)
            cache.get_image(img_url, self._current_vehicle_id)
        else:
            self._current_img_url = None
            self._photo.setPixmap(QPixmap())
            self._photo.setText(t("vehicles.photo_unavailable"))
            self._photo.setFont(QFont("Hanken Grotesk", 13))
            self._photo.setStyleSheet("""
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
                background-color: #F4F6F3;
                color: #7A8477;
            """)

        # 2. Title (Brand + Model)
        brand = vehicle.get("brand", "")
        model = vehicle.get("model", "")
        full_name = f"{brand} {model}".strip() or t("sidebar.vehicles")
        self._name_lbl.setText(full_name)

        # 3. Dynamic Spec Rows (Real Data Only)
        self._clear_layout(self._specs_container)

        def add_spec_row(icon_text: str, label_text: str, value_text: str, is_highlight: bool = False):
            if not value_text or str(value_text).strip() == "":
                return
            row = QHBoxLayout()
            row.setSpacing(10)
            row.setContentsMargins(0, 0, 0, 0)

            icn = QLabel(icon_text)
            icn.setFont(QFont("Segoe UI Emoji", 11))
            icn.setFixedWidth(22)
            icn.setAlignment(Qt.AlignmentFlag.AlignCenter)

            lbl = QLabel(label_text)
            lbl.setFont(QFont("Hanken Grotesk", 10))
            lbl.setStyleSheet("color: #6B7264;")

            val = QLabel(str(value_text))
            val.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
            if is_highlight:
                val.setStyleSheet("color: #1E4D38; font-weight: bold;")
            else:
                val.setStyleSheet("color: #2D3748;")
            val.setWordWrap(True)

            row.addWidget(icn)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(val)
            self._specs_container.addLayout(row)

        # Immatriculation
        reg = vehicle.get("registration")
        if reg:
            add_spec_row("🪪", t("vehicles.spec_reg"), str(reg))

        # Année
        year = vehicle.get("year")
        if year:
            add_spec_row("📅", t("vehicles.spec_year"), str(year))

        # Carburant
        fuel = vehicle.get("fuel_type")
        if fuel:
            fuel_label = t(f"fuel.{fuel}")
            add_spec_row("⛽", t("vehicles.spec_fuel"), fuel_label)

        # Tarif / jour
        price = vehicle.get("daily_rental_price")
        if price is not None:
            try:
                price_val = float(price)
                p_text = f"{price_val:.0f} DH {t('vehicles.per_day')}" if not is_rtl() else f"{price_val:.0f} د.م {t('vehicles.per_day')}"
                add_spec_row("💰", t("vehicles.spec_price"), p_text, is_highlight=True)
            except (ValueError, TypeError):
                add_spec_row("💰", t("vehicles.spec_price"), f"{price} {t('vehicles.per_day')}", is_highlight=True)

        # Statut
        status = vehicle.get("status")
        if status:
            display_status = t(f"status.{status}")
            add_spec_row("📍", t("vehicles.spec_status"), display_status)

        # Optional: Kilométrage (ONLY if present)
        mileage = vehicle.get("current_mileage")
        if mileage is not None and str(mileage).strip() != "":
            try:
                m_int = int(mileage)
                unit = "km" if not is_rtl() else "كم"
                formatted_m = f"{m_int:,} {unit}".replace(",", " ")
                add_spec_row("🚘", t("vehicles.modal_mileage"), formatted_m)
            except (ValueError, TypeError):
                add_spec_row("🚘", t("vehicles.modal_mileage"), f"{mileage}")

        # Optional: Couleur (ONLY if present)
        color = vehicle.get("color")
        if color:
            add_spec_row("🎨", t("vehicles.modal_color"), str(color))

        # Optional: Transmission (ONLY if present)
        transmission = vehicle.get("transmission")
        if transmission:
            trans_lbl = t(f"transmission.{transmission}")
            add_spec_row("⚙️", t("vehicles.modal_trans"), trans_lbl)

        # Optional: Notes / Maintenance
        notes = vehicle.get("notes")
        if notes and str(notes).strip():
            add_spec_row("🔧", t("vehicles.modal_notes"), str(notes))

        self.container.adjustSize()
        self.adjustSize()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _on_image_loaded(self, url: str, pixmap: QPixmap):
        if self._current_img_url == url and not pixmap.isNull():
            target_size = self._photo.size()
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
            path.addRoundedRect(0, 0, target_size.width(), target_size.height(), 11, 11)
            path.addRect(0, target_size.height() - 11, target_size.width(), 11)
            painter.setClipPath(path)

            x = (target_size.width() - scaled.width()) // 2
            y = (target_size.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()

            self._photo.setPixmap(rounded)
            self._photo.setText("")
            self._photo.setStyleSheet("background-color: transparent;")

    # ─── ROW INTERACTION ───

    def on_row_enter(self, row, vehicle_data: dict):
        """Called when mouse enters a vehicle row's info area (NOT action buttons)."""
        vehicle_id = vehicle_data.get("id")

        # Stop any pending hides because we are hovering something
        self._hide_timer.stop()

        # Register the new pending vehicle
        self._pending_hover_vehicle_id = vehicle_id
        self._pending_hover_row = row
        self._pending_vehicle_data = vehicle_data

        if self._is_visible and self._current_vehicle_id == vehicle_id:
            # Already visible for this vehicle, do nothing
            return
        elif self._is_visible and self._current_vehicle_id != vehicle_id:
            # Moved to a different row while preview is visible — immediately update
            self._show_timer.stop()
            self.show_for_row(row, vehicle_data)
        else:
            # Start timer to show preview
            self._show_timer.start(200)

    def _on_show_timeout(self):
        """Fired when hover time is reached."""
        if not self._pending_hover_row or not self._pending_hover_vehicle_id:
            return

        # Verify the row hasn't been destroyed
        try:
            # Check if C++ object is still valid
            if not self._pending_hover_row.isVisible():
                return
        except RuntimeError:
            return

        self.show_for_row(self._pending_hover_row, self._pending_vehicle_data)

    def on_row_leave(self, row=None, vehicle_data: dict = None):
        """Called when mouse leaves a vehicle row."""
        vehicle_id = vehicle_data.get("id") if vehicle_data else None

        # If we just left the pending row, cancel the show timer
        if vehicle_id == self._pending_hover_vehicle_id:
            self._show_timer.stop()
            self._pending_hover_vehicle_id = None
            self._pending_hover_row = None
            self._pending_vehicle_data = None

        if not vehicle_data or self._current_vehicle_id == vehicle_id:
            self._hide_timer.start(120)

    def _check_and_hide(self):
        """Only hide if cursor is not over the preview."""
        if not self.underMouse():
            self.hide_preview(immediate=False)

    def cancel_and_hide(self):
        """Immediately cancel timers and hide preview without delay."""
        if shiboken6.isValid(self._show_timer):
            try:
                self._show_timer.stop()
            except RuntimeError:
                pass
        self._pending_hover_vehicle_id = None
        self._pending_hover_row = None
        self._pending_vehicle_data = None
        if shiboken6.isValid(self):
            try:
                self.hide_preview(immediate=True)
            except RuntimeError:
                pass

    # ─── POSITIONING — KEY FIX ───

    def show_for_row(self, row, vehicle_data: dict):
        """Position the preview directly under (or above) the hovered row, aligned horizontally with the mouse."""
        self._hide_timer.stop()
        self.set_vehicle(vehicle_data)

        # Ensure the popup processes its layout to get correct sizeHint
        self.adjustSize()
        pw = self.width()
        ph = self.height()

        row_global_pos = row.mapToGlobal(QPoint(0, 0))
        row_h = row.height()

        # Get mouse position globally
        mouse_pos = QCursor.pos()
        mouse_x = mouse_pos.x()

        # Get application window geometry
        win = row.window()
        win_global_pos = win.mapToGlobal(QPoint(0, 0))
        win_rect = QRect(win_global_pos, win.size())

        # Get screen geometry for boundary clamping
        screen = QApplication.screenAt(row_global_pos) or QApplication.primaryScreen()
        screen_rect = screen.availableGeometry() if screen else win_rect

        gap = 4  # gap between row and preview

        # Vertical positioning: Prefer BELOW the row
        row_bottom = row_global_pos.y() + row_h
        row_top = row_global_pos.y()

        space_below = screen_rect.bottom() - (row_bottom + gap)
        space_above = (row_top - gap) - screen_rect.top()

        if space_below >= ph:
            target_y = row_bottom + gap
        elif space_above >= ph:
            target_y = row_top - gap - ph
        else:
            # If neither has enough space, place it where there is more space
            if space_below >= space_above:
                target_y = row_bottom + gap
            else:
                target_y = row_top - gap - ph

        # Horizontal positioning: Center around mouse_x
        target_x = mouse_x - (pw // 2)

        # Clamp to screen/window boundaries
        target_x = max(win_rect.left() + 4, min(target_x, win_rect.right() - pw - 4))
        target_y = max(screen_rect.top() + 4, min(target_y, screen_rect.bottom() - ph - 4))

        self.move(target_x, target_y)

        if not self._is_visible:
            self._opacity_effect.setOpacity(0.0)
            self.show()
            self.raise_()
            self._anim.stop()
            self._anim.setDuration(180)
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._anim.start()
            self._is_visible = True
        else:
            self._opacity_effect.setOpacity(1.0)
            self.show()
            self.raise_()

    def enterEvent(self, event):
        self._is_hovered = True
        try:
            self._hide_timer.stop()
        except RuntimeError:
            pass
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        try:
            self._hide_timer.start(120)
        except RuntimeError:
            pass
        super().leaveEvent(event)

    def hide_preview(self, immediate: bool = False):
        try:
            self._hide_timer.stop()
        except RuntimeError:
            pass
        if not self._is_visible:
            return
        if immediate:
            try:
                self._anim.stop()
            except RuntimeError:
                pass
            try:
                self._opacity_effect.setOpacity(0.0)
            except RuntimeError:
                pass
            try:
                self.hide()
            except RuntimeError:
                pass
            self._is_visible = False
            self._current_vehicle = None
            self._current_vehicle_id = None
            self._current_img_url = None
            self._is_hovered = False
            return

        try:
            self._anim.stop()
            self._anim.setDuration(100)
            self._anim.setStartValue(self._opacity_effect.opacity())
            self._anim.setEndValue(0.0)
            self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
            self._anim.start()
        except RuntimeError:
            try:
                self.hide()
            except RuntimeError:
                pass
            self._is_visible = False

    def _on_anim_finished(self):
        try:
            if self._opacity_effect.opacity() <= 0.05:
                self.hide()
                self._is_visible = False
                self._current_vehicle = None
                self._current_vehicle_id = None
                self._current_img_url = None
                self._is_hovered = False
        except RuntimeError:
            self._is_visible = False


def cleanup_hover_preview():
    """Destroy the singleton safely to prevent PyQt segfaults on exit."""
    global _hover_preview_instance
    if _hover_preview_instance is not None:
        try:
            _hover_preview_instance.deleteLater()
        except RuntimeError:
            pass
        _hover_preview_instance = None
