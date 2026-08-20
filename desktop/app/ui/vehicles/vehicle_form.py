"""
Vehicle form dialog — add/edit vehicles with multi-photo gallery and full specifications.
Fully localized for French and Arabic with RTL layout support.
Supports uploading, previewing, and removing multiple vehicle photos.
"""
import os
import shutil
import uuid
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QDateEdit, QTextEdit, QPushButton, QLabel, QCheckBox,
    QFileDialog, QMessageBox, QFrame, QScrollArea, QWidget
)
from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtGui import QPixmap, QFont, QPainter, QPainterPath
from app.i18n import t, is_rtl
from app.config import API_BASE_URL
from app.services.api_client import ApiClient


class PhotoThumbnail(QFrame):
    """A single photo thumbnail in the gallery with remove button."""
    remove_requested = Signal(int)  # emits the index

    def __init__(self, index: int, pixmap: QPixmap = None, path_or_url: str = "", parent=None):
        super().__init__(parent)
        self.index = index
        self.path_or_url = path_or_url
        self.setFixedSize(100, 80)
        self.setStyleSheet("""
            QFrame {
                background: #FFFFFF;
                border: 1px solid #D5DDD3;
                border-radius: 8px;
            }
            QFrame:hover {
                border: 2px solid #1E4D38;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)

        self._img_lbl = QLabel()
        self._img_lbl.setFixedSize(96, 58)
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("border: none; border-radius: 6px; background: #F2F5F0;")
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(96, 58, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._img_lbl.setPixmap(scaled)
        else:
            self._img_lbl.setText("🚗")
            self._img_lbl.setFont(QFont("Hanken Grotesk", 16))
        layout.addWidget(self._img_lbl)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(96, 16)
        remove_btn.setFont(QFont("Hanken Grotesk", 8))
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setStyleSheet("""
            QPushButton {
                background: #FEF2F2; color: #DC2626; border: 1px solid #FECACA;
                border-radius: 3px; padding: 0px;
            }
            QPushButton:hover { background: #FEE2E2; }
        """)
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.index))
        layout.addWidget(remove_btn)


class VehicleFormDialog(QDialog):
    """Form dialog for creating/editing a vehicle with multi-photo gallery management."""
    saved = Signal(dict)

    def __init__(self, vehicle_data=None, api_client=None, parent=None):
        super().__init__(parent)
        self._data = vehicle_data or {}
        self._api = api_client or ApiClient(API_BASE_URL)
        self._is_edit = bool(vehicle_data and vehicle_data.get("id"))

        # Parse existing image_url into a list of URLs
        self._photo_urls = self._data.get("images", [])
        if not self._photo_urls:
            raw_url = self._data.get("image_url") or ""
            if raw_url:
                self._photo_urls = [u.strip() for u in raw_url.split(",") if u.strip()]

        # New photos selected from filesystem (not yet uploaded)
        self._new_photo_paths = []  # list of local file paths

        title = t("vehicles.form_edit_title") if self._is_edit else t("vehicles.form_add_title")
        self.setWindowTitle(title)
        self.setMinimumWidth(580)
        self._setup_ui()

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Scroll area to handle long forms
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(10)

        # 1. Registration
        self._reg = QLineEdit(self._data.get("registration", ""))
        self._reg.setPlaceholderText("ex: GB-123-EF")
        self._reg.setMinimumHeight(38)
        form.addRow(t("vehicles.form_reg"), self._reg)

        # 2. VIN
        self._vin = QLineEdit(self._data.get("vin", ""))
        self._vin.setMaxLength(17)
        self._vin.setPlaceholderText("17 caractères")
        self._vin.setMinimumHeight(38)
        if self._is_edit:
            self._vin.setReadOnly(True)
        form.addRow(t("vehicles.form_vin"), self._vin)

        # 3. Brand
        self._brand = QLineEdit(self._data.get("brand", ""))
        self._brand.setPlaceholderText("ex: Audi")
        self._brand.setMinimumHeight(38)
        form.addRow(t("vehicles.form_brand"), self._brand)

        # 4. Model
        self._model = QLineEdit(self._data.get("model", ""))
        self._model.setPlaceholderText("ex: A8 L")
        self._model.setMinimumHeight(38)
        form.addRow(t("vehicles.form_model"), self._model)

        # 5. Year
        self._year = QSpinBox()
        self._year.setRange(1990, 2035)
        self._year.setValue(self._data.get("year", 2024))
        self._year.setMinimumHeight(38)
        form.addRow(t("vehicles.form_year"), self._year)

        # 6. Color
        self._color = QLineEdit(self._data.get("color", "Noir" if not is_rtl() else "أسود"))
        self._color.setMinimumHeight(38)
        form.addRow(t("vehicles.form_color"), self._color)

        # 7. Motorisation / Fuel
        self._fuel = QComboBox()
        for ft in ["GASOLINE", "DIESEL", "HYBRID", "ELECTRIC", "LPG"]:
            self._fuel.addItem(t(f"fuel.{ft}"), ft)
        if "fuel_type" in self._data:
            idx = self._fuel.findData(self._data["fuel_type"])
            if idx >= 0:
                self._fuel.setCurrentIndex(idx)
        self._fuel.setMinimumHeight(38)
        form.addRow(t("vehicles.form_motorisation"), self._fuel)

        # 8. Transmission
        self._trans = QComboBox()
        self._trans.addItem(t("transmission.AUTOMATIC"), "AUTOMATIC")
        self._trans.addItem(t("transmission.MANUAL"), "MANUAL")
        if "transmission" in self._data:
            idx = self._trans.findData(self._data["transmission"])
            if idx >= 0:
                self._trans.setCurrentIndex(idx)
        self._trans.setMinimumHeight(38)
        form.addRow(t("vehicles.form_trans"), self._trans)

        # 9. Mileage
        self._mileage = QSpinBox()
        self._mileage.setRange(0, 9999999)
        self._mileage.setValue(self._data.get("current_mileage", 0))
        self._mileage.setMinimumHeight(38)
        form.addRow(t("vehicles.form_mileage"), self._mileage)

        # 10. Purchase Mileage
        self._purchase_mileage = QSpinBox()
        self._purchase_mileage.setRange(0, 9999999)
        self._purchase_mileage.setValue(self._data.get("purchase_mileage", 0))
        self._purchase_mileage.setMinimumHeight(38)
        form.addRow(t("vehicles.form_purchase_mileage"), self._purchase_mileage)

        # 11. Daily Rental Price (DH / jour)
        self._price = QDoubleSpinBox()
        self._price.setRange(0, 999999.99)
        self._price.setDecimals(2)
        self._price.setValue(self._data.get("daily_rental_price", 450.0))
        self._price.setMinimumHeight(38)
        form.addRow(t("vehicles.form_daily_price"), self._price)

        # 12. Purchase Price
        self._purchase_price = QDoubleSpinBox()
        self._purchase_price.setRange(0, 99999999.99)
        self._purchase_price.setDecimals(2)
        self._purchase_price.setValue(self._data.get("purchase_price", 0))
        self._purchase_price.setMinimumHeight(38)
        form.addRow(t("vehicles.form_purchase_price"), self._purchase_price)

        # 13. Status
        self._status = QComboBox()
        for st in ["AVAILABLE", "RENTED", "RESERVED", "MAINTENANCE"]:
            self._status.addItem(t(f"status.{st}"), st)
        if "status" in self._data:
            idx = self._status.findData(self._data["status"])
            if idx >= 0:
                self._status.setCurrentIndex(idx)
        self._status.setMinimumHeight(38)
        form.addRow(t("vehicles.form_status"), self._status)

        layout.addLayout(form)

        # ── MULTI-PHOTO GALLERY ──
        photo_box = QFrame()
        photo_box.setStyleSheet("background: #F4F6F3; border: 1px solid #D5DDD3; border-radius: 8px; padding: 10px;")
        photo_box_layout = QVBoxLayout(photo_box)
        photo_box_layout.setSpacing(10)

        lbl_photo_sec = QLabel(t("vehicles.form_photo_section"))
        lbl_photo_sec.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.Bold))
        lbl_photo_sec.setStyleSheet("color: #1E4D38; border: none;")
        photo_box_layout.addWidget(lbl_photo_sec)

        # Photo gallery grid
        self._gallery_widget = QWidget()
        self._gallery_widget.setStyleSheet("border: none;")
        self._gallery_layout = QGridLayout(self._gallery_widget)
        self._gallery_layout.setSpacing(8)
        self._gallery_layout.setContentsMargins(0, 0, 0, 0)
        photo_box_layout.addWidget(self._gallery_widget)

        # Add photos button
        add_photos_btn = QPushButton(f"📷 {t('vehicles.form_photo_upload')}")
        add_photos_btn.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
        add_photos_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_photos_btn.setFixedHeight(36)
        add_photos_btn.setStyleSheet("""
            QPushButton {
                background: #E8F3E6; color: #1E4D38; border: 1px solid #B5CDB0;
                border-radius: 6px; padding: 0 16px;
            }
            QPushButton:hover { background: #D4E8D0; }
        """)
        add_photos_btn.clicked.connect(self._choose_photos)
        photo_box_layout.addWidget(add_photos_btn)

        layout.addWidget(photo_box)

        # Populate gallery with existing photos
        self._rebuild_gallery()

        # ── DOCUMENT VALIDITY ──
        docs_box = QFrame()
        docs_box.setStyleSheet("background: #F4F6F3; border: 1px solid #D5DDD3; border-radius: 8px; padding: 10px;")
        docs_layout = QVBoxLayout(docs_box)

        lbl_docs_sec = QLabel(t("vehicles.form_docs_section"))
        lbl_docs_sec.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.Bold))
        lbl_docs_sec.setStyleSheet("color: #1E4D38; border: none;")
        docs_layout.addWidget(lbl_docs_sec)

        docs_form = QFormLayout()

        def make_date_edit(date_val):
            de = QDateEdit()
            de.setCalendarPopup(True)
            de.setMinimumHeight(32)
            if date_val:
                try:
                    d = QDate.fromString(str(date_val).split("T")[0], "yyyy-MM-dd")
                    if d.isValid():
                        de.setDate(d)
                    else:
                        de.setDate(QDate.currentDate().addYears(1))
                except Exception:
                    de.setDate(QDate.currentDate().addYears(1))
            else:
                de.setDate(QDate.currentDate().addYears(1))
            return de

        self._assurance_exp = make_date_edit(self._data.get("assurance_expiry"))
        docs_form.addRow(t("vehicles.doc_assurance"), self._assurance_exp)

        self._vignette_exp = make_date_edit(self._data.get("vignette_expiry"))
        docs_form.addRow(t("vehicles.doc_vignette"), self._vignette_exp)

        self._visite_exp = make_date_edit(self._data.get("visite_technique_expiry"))
        docs_form.addRow(t("vehicles.doc_visite"), self._visite_exp)

        self._carte_grise_exp = make_date_edit(self._data.get("carte_grise_expiry"))
        docs_form.addRow(t("vehicles.doc_carte_grise"), self._carte_grise_exp)

        self._autres_label = QLineEdit(self._data.get("autres_label", ""))
        self._autres_label.setPlaceholderText("ex: Extincteur")
        docs_form.addRow(t("vehicles.form_autres_label"), self._autres_label)

        self._autres_exp = make_date_edit(self._data.get("autres_expiry"))
        docs_form.addRow(t("vehicles.form_autres_expiry"), self._autres_exp)

        docs_layout.addLayout(docs_form)
        layout.addWidget(docs_box)

        # ── NOTES ──
        self._notes = QTextEdit(self._data.get("notes", ""))
        self._notes.setMaximumHeight(60)
        self._notes.setPlaceholderText(t("vehicles.form_notes"))
        layout.addWidget(self._notes)

        # Buttons
        btns = QHBoxLayout()
        cancel_btn = QPushButton(t("common.cancel"))
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)

        save_btn = QPushButton(t("vehicles.form_save"))
        save_btn.setProperty("class", "primary")
        save_btn.setFont(QFont("Hanken Grotesk", 10, QFont.Weight.Bold))
        save_btn.clicked.connect(self._save)
        btns.addWidget(save_btn)

        layout.addLayout(btns)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ─── MULTI-PHOTO GALLERY ───

    def _rebuild_gallery(self):
        """Rebuild the visual gallery grid from current photo data."""
        # Clear existing thumbnails
        while self._gallery_layout.count():
            item = self._gallery_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        all_photos = []

        # Existing remote/server photos
        for i, url in enumerate(self._photo_urls):
            pix = QPixmap()
            # Try loading from local cache
            from app.services.image_cache import get_image_cache
            cache = get_image_cache()
            full_url = cache._build_url(url)
            if full_url in cache._cache:
                pix = cache._cache[full_url]
            else:
                # Try disk
                clean_rel = url.replace("/static/uploads/vehicles/", "").replace("/static/uploads/", "").lstrip("/")
                for candidate in [
                    Path("/home/ayman/car-rental-system/backend/uploads/vehicles") / clean_rel,
                    Path("/home/ayman/car-rental-system/backend/uploads") / clean_rel,
                    Path(url),
                ]:
                    if candidate.is_file():
                        pix = QPixmap(str(candidate))
                        break
            all_photos.append(("url", i, pix, url))

        # Newly selected local photos
        for j, path in enumerate(self._new_photo_paths):
            pix = QPixmap(path)
            all_photos.append(("local", j, pix, path))

        cols = 5  # thumbnails per row
        for idx, (source, sub_idx, pix, path_or_url) in enumerate(all_photos):
            thumb = PhotoThumbnail(idx, pix, path_or_url)
            thumb.remove_requested.connect(self._on_remove_photo)
            row = idx // cols
            col = idx % cols
            self._gallery_layout.addWidget(thumb, row, col)

        # Store combined list for removal tracking
        self._all_gallery_items = all_photos

    def _choose_photos(self):
        """Open multi-file selector for photos."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            t("vehicles.form_photo_upload"),
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if file_paths:
            self._new_photo_paths.extend(file_paths)
            self._rebuild_gallery()

    def _on_remove_photo(self, gallery_index: int):
        """Remove a photo by its gallery index."""
        if gallery_index < 0 or gallery_index >= len(self._all_gallery_items):
            return

        source, sub_idx, _, _ = self._all_gallery_items[gallery_index]
        if source == "url":
            if sub_idx < len(self._photo_urls):
                self._photo_urls.pop(sub_idx)
        elif source == "local":
            if sub_idx < len(self._new_photo_paths):
                self._new_photo_paths.pop(sub_idx)

        self._rebuild_gallery()

    def _save(self):
        reg = self._reg.text().strip()
        brand = self._brand.text().strip()
        model = self._model.text().strip()

        if not reg:
            QMessageBox.warning(self, t("common.error"), t("vehicles.form_err_reg"))
            return

        if not brand or not model:
            QMessageBox.warning(self, t("common.error"), t("vehicles.form_err_brand"))
            return

        # Upload new photos and collect all URLs
        final_urls = list(self._photo_urls)  # existing URLs

        for local_path in self._new_photo_paths:
            uploaded_url = None
            try:
                # API returns a dict: {"status": "ok", "image_url": "/static/...", "filename": "..."}
                res = self._api.upload_vehicle_image(local_path)
                if res and isinstance(res, dict) and "image_url" in res:
                    uploaded_url = res["image_url"]
            except Exception:
                pass

            if uploaded_url:
                final_urls.append(uploaded_url)
            else:
                # Offline fallback: copy to local backend uploads
                try:
                    ext = Path(local_path).suffix
                    filename = f"{uuid.uuid4().hex}{ext}"
                    dest = Path("/home/ayman/car-rental-system/backend/uploads/vehicles") / filename
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(local_path, dest)
                    final_urls.append(f"/static/uploads/vehicles/{filename}")
                except Exception:
                    pass

        # Store as comma-separated string
        image_url = ", ".join(final_urls) if final_urls else ""

        data = {
            "registration": reg,
            "vin": self._vin.text().strip(),
            "brand": brand,
            "model": model,
            "year": self._year.value(),
            "color": self._color.text().strip(),
            "fuel_type": self._fuel.currentData(),
            "transmission": self._trans.currentData(),
            "current_mileage": self._mileage.value(),
            "purchase_mileage": self._purchase_mileage.value(),
            "daily_rental_price": self._price.value(),
            "purchase_price": self._purchase_price.value(),
            "status": self._status.currentData(),
            "image_url": image_url,
            "images": final_urls,
            "assurance_expiry": self._assurance_exp.date().toString("yyyy-MM-dd"),
            "vignette_expiry": self._vignette_exp.date().toString("yyyy-MM-dd"),
            "visite_technique_expiry": self._visite_exp.date().toString("yyyy-MM-dd"),
            "carte_grise_expiry": self._carte_grise_exp.date().toString("yyyy-MM-dd"),
            "autres_label": self._autres_label.text().strip(),
            "autres_expiry": self._autres_exp.date().toString("yyyy-MM-dd") if self._autres_label.text().strip() else None,
            "notes": self._notes.toPlainText().strip()
        }

        if self._is_edit:
            data["id"] = self._data["id"]

        self.saved.emit(data)
        self.accept()
