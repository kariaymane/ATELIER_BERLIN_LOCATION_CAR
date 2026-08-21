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
import traceback
import threading

global_request_id = 0

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
    Singleton robust preview controller.
    Fixes the crash during rapid transitions and deleted QObjects.
    """
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.BypassWindowManagerHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # ── SINGLE PREVIEW CONTROLLER STATE ──
        self._hover_generation = 0  # Request generation token
        self._active_generation = 0  # Currently displayed generation
        
        self._current_vehicle = None
        self._current_vehicle_id = None
        self._current_img_url = None
        
        self._pending_hover_row = None
        self._pending_hover_vehicle_id = None
        self._pending_vehicle_data = None
        
        self._is_visible = False
        self._is_hovered = False
        
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._on_show_timeout)
        
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._check_and_hide)

        # Hook up image cache safely
        self._img_connected = False

        self._setup_ui()
        self.hide()

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)
        
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(12, 12, 12, 12)

        self._container = QFrame(self)
        self._container.setObjectName("HoverContainer")
        self._container.setStyleSheet("""
            QFrame#HoverContainer {
                background-color: #FFFFFF;
                border: 1px solid #E2E5DE;
                border-radius: 12px;
            }
        """)
        
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.0)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 8)
        self._container.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Image setup
        self._photo = QLabel()
        self._photo.setFixedSize(320, 200)
        self._photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._photo.setStyleSheet("background-color: #F2F5F0; border-radius: 8px;")
        layout.addWidget(self._photo)

        # Header (Brand, Model, Year)
        header_layout = QHBoxLayout()
        self._title = QLabel()
        self._title.setFont(QFont("Libre Caslon Text", 16, QFont.Weight.Bold))
        self._title.setStyleSheet("color: #1E4D38;")
        self._year = QLabel()
        self._year.setFont(QFont("Hanken Grotesk", 12))
        self._year.setStyleSheet("color: #6B7264;")
        
        header_layout.addWidget(self._title)
        header_layout.addStretch()
        header_layout.addWidget(self._year)
        layout.addLayout(header_layout)

        # Attributes
        attr_layout = QHBoxLayout()
        self._fuel = QLabel()
        self._fuel.setStyleSheet("color: #4A5568;")
        self._trans = QLabel()
        self._trans.setStyleSheet("color: #4A5568;")
        self._plate = QLabel()
        self._plate.setStyleSheet("color: #4A5568;")
        
        attr_layout.addWidget(self._fuel)
        attr_layout.addWidget(self._trans)
        attr_layout.addWidget(self._plate)
        attr_layout.addStretch()
        layout.addLayout(attr_layout)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("background-color: #E2E5DE;")
        layout.addWidget(div)

        # Pricing
        price_layout = QHBoxLayout()
        self._price = QLabel()
        self._price.setFont(QFont("Hanken Grotesk", 14, QFont.Weight.Bold))
        self._price.setStyleSheet("color: #1E4D38;")
        self._status = QLabel()
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setContentsMargins(8, 4, 8, 4)
        
        price_layout.addWidget(self._price)
        price_layout.addStretch()
        price_layout.addWidget(self._status)
        layout.addLayout(price_layout)

        self._main_layout.addWidget(self._container)

        self._anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._anim.finished.connect(self._on_anim_finished)

    def on_row_enter(self, row, vehicle_data: dict):
        """Called when mouse enters a new row. Registers request generation."""
        if not vehicle_data:
            return
            
        vehicle_id = vehicle_data.get("id")
        
        self._hover_generation += 1  # Increment token for robust state tracking
        
        # Stop hide timer if returning
        if shiboken6.isValid(self._hide_timer):
            self._hide_timer.stop()

        self._pending_hover_row = row
        self._pending_hover_vehicle_id = vehicle_id
        self._pending_vehicle_data = vehicle_data

        if self._is_visible and self._current_vehicle_id == vehicle_id:
            return
        elif self._is_visible and self._current_vehicle_id != vehicle_id:
            # Immediate transition case
            if shiboken6.isValid(self._show_timer):
                self._show_timer.stop()
            self.show_for_row(row, vehicle_data, self._hover_generation)
        else:
            # Normal delay
            if shiboken6.isValid(self._show_timer):
                self._show_timer.start(200)

    def _on_show_timeout(self):
        """Fired when hover timer executes. Verifies token and safely shows."""
        if not self._pending_hover_row or not self._pending_vehicle_data:
            return
            
        if not shiboken6.isValid(self._pending_hover_row):
            return

        if not self._pending_hover_row.isVisible():
            return

        self.show_for_row(self._pending_hover_row, self._pending_vehicle_data, self._hover_generation)

    def show_for_row(self, row, vehicle_data: dict, generation: int):
        """Verify lifetime, compute position, populate UI."""
        if generation != self._hover_generation:
            # Stale callback - user has already moved on
            return
            
        if not shiboken6.isValid(row):
            return

        if shiboken6.isValid(self._hide_timer):
            self._hide_timer.stop()
            
        self._active_generation = generation
        self.set_vehicle(vehicle_data)

        self.adjustSize()
        pw = self.width()
        ph = self.height()

        try:
            row_global_pos = row.mapToGlobal(QPoint(0, 0))
            win = row.window()
            win_global_pos = win.mapToGlobal(QPoint(0, 0))
            win_rect = QRect(win_global_pos, win.size())
            screen = QApplication.screenAt(row_global_pos) or QApplication.primaryScreen()
            screen_rect = screen.availableGeometry() if screen else win_rect
        except RuntimeError:
            return

        mouse_pos = QCursor.pos()
        target_x = mouse_pos.x() - (pw // 2)
        
        row_h = row.height()
        gap = 4
        row_bottom = row_global_pos.y() + row_h
        row_top = row_global_pos.y()

        space_below = screen_rect.bottom() - (row_bottom + gap)
        space_above = (row_top - gap) - screen_rect.top()

        if space_below >= ph:
            target_y = row_bottom + gap
        elif space_above >= ph:
            target_y = row_top - gap - ph
        else:
            target_y = row_bottom + gap if space_below >= space_above else row_top - gap - ph

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

    def set_vehicle(self, vehicle: dict):
        if not vehicle:
            return

        self._current_vehicle = vehicle
        self._current_vehicle_id = vehicle.get("id")

        self._title.setText(f"{vehicle.get('brand', '')} {vehicle.get('model', '')}".strip())
        self._year.setText(str(vehicle.get('year', '')))
        
        fuel = vehicle.get('fuel_type', '')
        if fuel:
            self._fuel.setText(t(f"fuel.{fuel}"))
        else:
            self._fuel.setText("")
            
        trans = vehicle.get('transmission', '')
        if trans:
            self._trans.setText(t(f"transmission.{trans}"))
        else:
            self._trans.setText("")
            
        self._plate.setText(vehicle.get('registration', ''))

        val = vehicle.get('daily_rental_price', 0)
        curr = "DH" if not is_rtl() else "د.م"
        self._price.setText(f"{val} {curr} {t('vehicles.per_day')}")

        status = vehicle.get("status")
        if status:
            self._status.setText(t(f"status.{status}"))
            if status == "AVAILABLE":
                self._status.setStyleSheet("background-color: #E6F4EA; color: #1E4D38; border-radius: 4px; padding: 2px;")
            elif status == "RENTED":
                self._status.setStyleSheet("background-color: #FEF08A; color: #975A16; border-radius: 4px; padding: 2px;")
            elif status == "MAINTENANCE":
                self._status.setStyleSheet("background-color: #FED7D7; color: #9B2C2C; border-radius: 4px; padding: 2px;")
            else:
                self._status.setStyleSheet("background-color: #E2E8F0; color: #4A5568; border-radius: 4px; padding: 2px;")
        else:
            self._status.setText("")

        # IMAGE HANDLING
        cache = get_image_cache()
        if not self._img_connected:
            cache.image_loaded.connect(self._on_image_loaded)
            self._img_connected = True

        raw_url = vehicle.get("image_url")
        if not raw_url:
            self._current_img_url = None
            self._photo.setPixmap(QPixmap())
            self._photo.setText("🚗")
            self._photo.setFont(QFont("Hanken Grotesk", 48))
            return

        urls = [u.strip() for u in raw_url.split(",") if u.strip()]
        if not urls:
            self._current_img_url = None
            self._photo.setPixmap(QPixmap())
            self._photo.setText("🚗")
            self._photo.setFont(QFont("Hanken Grotesk", 48))
            return

        img_url = urls[0]
        self._current_img_url = f"{self._current_vehicle_id}_{cache._build_url(img_url)}"
        
        self._photo.setPixmap(QPixmap())
        self._photo.setText("⏳")
        self._photo.setFont(QFont("Hanken Grotesk", 32))

        cache.get_image(img_url, str(self._current_vehicle_id))

    def _on_image_loaded(self, url: str, pixmap: QPixmap):
        """Safely apply image if it matches the current request token & vehicle."""
        if not shiboken6.isValid(self):
            return
            
        if self._current_img_url != url:
            return
            
        if pixmap.isNull():
            self._photo.setPixmap(QPixmap())
            self._photo.setText("🚗")
            self._photo.setFont(QFont("Hanken Grotesk", 48))
            return
            
        target_size = self._photo.size()
        if target_size.isEmpty():
            return
            
        scaled = pixmap.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )
        if scaled.isNull():
            return

        rounded = QPixmap(target_size)
        rounded.fill(Qt.GlobalColor.transparent)

        painter = QPainter(rounded)
        if painter.isActive():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(0, 0, target_size.width(), target_size.height(), 8, 8)
            painter.setClipPath(path)

            x = (target_size.width() - scaled.width()) // 2
            y = (target_size.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()

            self._photo.setText("")
            self._photo.setPixmap(rounded)

    def on_row_leave(self, row, vehicle_data: dict):
        if not vehicle_data:
            return
            
        vehicle_id = vehicle_data.get("id")
        
        # If we left the pending row before timer fired, cancel timer
        if vehicle_id == self._pending_hover_vehicle_id:
            if shiboken6.isValid(self._show_timer):
                self._show_timer.stop()
            self._pending_hover_vehicle_id = None
            self._pending_hover_row = None
            self._pending_vehicle_data = None

        if self._current_vehicle_id == vehicle_id or not vehicle_id:
            if shiboken6.isValid(self._hide_timer):
                self._hide_timer.start(120)

    def _check_and_hide(self):
        if not self.underMouse():
            self.hide_preview(immediate=False)

    def cancel_and_hide(self):
        self._hover_generation += 1  # Invalidate any pending callbacks
        
        if shiboken6.isValid(self._show_timer):
            self._show_timer.stop()
            
        self._pending_hover_vehicle_id = None
        self._pending_hover_row = None
        self._pending_vehicle_data = None
        
        if shiboken6.isValid(self):
            self.hide_preview(immediate=True)

    def hide_preview(self, immediate: bool = False):
        if shiboken6.isValid(self._hide_timer):
            self._hide_timer.stop()
            
        if not self._is_visible:
            return
            
        if immediate:
            if shiboken6.isValid(self._anim):
                self._anim.stop()
            if shiboken6.isValid(self._opacity_effect):
                self._opacity_effect.setOpacity(0.0)
            if shiboken6.isValid(self):
                self.hide()
            self._is_visible = False
            self._current_vehicle = None
            self._current_vehicle_id = None
            self._current_img_url = None
            self._is_hovered = False
            return

        if shiboken6.isValid(self._anim):
            self._anim.stop()
            self._anim.setDuration(100)
            self._anim.setStartValue(self._opacity_effect.opacity())
            self._anim.setEndValue(0.0)
            self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
            self._anim.start()

    def _on_anim_finished(self):
        if shiboken6.isValid(self) and shiboken6.isValid(self._opacity_effect):
            if self._opacity_effect.opacity() <= 0.05:
                self.hide()
                self._is_visible = False
                self._current_vehicle = None
                self._current_vehicle_id = None
                self._current_img_url = None
                self._is_hovered = False

    def enterEvent(self, event):
        self._is_hovered = True
        if shiboken6.isValid(self._hide_timer):
            self._hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        if shiboken6.isValid(self._hide_timer):
            self._hide_timer.start(120)
        super().leaveEvent(event)


def cleanup_hover_preview():
    """Destroy the singleton safely to prevent PyQt segfaults on exit."""
    global _hover_preview_instance
    if _hover_preview_instance is not None:
        try:
            _hover_preview_instance.deleteLater()
        except RuntimeError:
            pass
        _hover_preview_instance = None
