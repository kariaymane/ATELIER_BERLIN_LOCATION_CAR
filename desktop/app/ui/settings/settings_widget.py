"""
Settings & Customization Widget for ATELIER BERLIN LOCATION CAR Car Rental System.
Provides live Language (Français / العربية) and Theme selection with instant RTL switching.
No developer/technical API configuration is exposed.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QComboBox, QPushButton, QRadioButton, QButtonGroup,
    QScrollArea, QGridLayout
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from app.config import (
    THEMES, get_saved_theme, save_theme, get_saved_language, save_language
)
from app.i18n import t, is_rtl, get_language, set_language, load_translations


class SettingsWidget(QWidget):
    """Clean, user-facing Settings page for Language and Theme selection."""
    theme_changed = Signal(str)
    language_changed = Signal(str)

    def __init__(self, user_data: dict = None, parent=None):
        super().__init__(parent)
        self._user_data = user_data or {}
        self._current_theme = get_saved_theme()
        self._radios = {}
        self._setup_ui()

    def _setup_ui(self):
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Page Header
        self._header_lbl = QLabel(t("settings.title"))
        self._header_lbl.setFont(QFont("Libre Caslon Text", 20, QFont.Weight.Bold))
        self._header_lbl.setStyleSheet("color: #1E4D38;")
        main_layout.addWidget(self._header_lbl)

        self._subtitle_lbl = QLabel(t("settings.subtitle"))
        self._subtitle_lbl.setFont(QFont("Hanken Grotesk", 11))
        self._subtitle_lbl.setStyleSheet("color: #6B7264;")
        main_layout.addWidget(self._subtitle_lbl)

        # Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(24)

        # ──── 1. LANGUAGE SELECTOR CARD ────
        self._lang_card = QFrame()
        self._lang_card.setObjectName("statCard")
        self._lang_card.setProperty("class", "card")
        lang_card_layout = QVBoxLayout(self._lang_card)
        lang_card_layout.setContentsMargins(20, 20, 20, 20)
        lang_card_layout.setSpacing(14)

        self._lang_title = QLabel(t("settings.language_card_title"))
        self._lang_title.setFont(QFont("Libre Caslon Text", 14, QFont.Weight.Bold))
        lang_card_layout.addWidget(self._lang_title)

        lang_row = QHBoxLayout()
        self._lang_label = QLabel(t("settings.language_label"))
        self._lang_label.setFont(QFont("Hanken Grotesk", 11))

        self._lang_combo = QComboBox()
        self._lang_combo.addItem("🇫🇷 Français", "fr")
        self._lang_combo.addItem("🇲🇦 العربية", "ar")
        self._lang_combo.setFixedHeight(38)
        self._lang_combo.setFont(QFont("Hanken Grotesk", 11))

        cur_lang = get_language()
        idx = self._lang_combo.findData(cur_lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_combo_changed)

        lang_row.addWidget(self._lang_label)
        lang_row.addWidget(self._lang_combo)
        lang_row.addStretch()

        lang_card_layout.addLayout(lang_row)
        layout.addWidget(self._lang_card)

        # ──── 2. THEME SELECTOR CARD ────
        self._theme_card = QFrame()
        self._theme_card.setObjectName("statCard")
        self._theme_card.setProperty("class", "card")
        theme_card_layout = QVBoxLayout(self._theme_card)
        theme_card_layout.setContentsMargins(20, 20, 20, 20)
        theme_card_layout.setSpacing(14)

        self._theme_title = QLabel(t("settings.theme_card_title"))
        self._theme_title.setFont(QFont("Libre Caslon Text", 14, QFont.Weight.Bold))
        self._theme_subtitle = QLabel(t("settings.theme_subtitle"))
        self._theme_subtitle.setFont(QFont("Hanken Grotesk", 10))
        self._theme_subtitle.setStyleSheet("color: #6B7264;")

        theme_card_layout.addWidget(self._theme_title)
        theme_card_layout.addWidget(self._theme_subtitle)

        # Theme Grid
        self._theme_grid = QGridLayout()
        self._theme_grid.setSpacing(12)
        self._theme_group = QButtonGroup(self)

        self._theme_meta = [
            ("emerald", "#B5CDB0", "settings.theme_emerald", "settings.theme_emerald_desc"),
            ("midnight", "#2563EB", "settings.theme_midnight", "settings.theme_midnight_desc"),
            ("graphite", "#3F3F46", "settings.theme_graphite", "settings.theme_graphite_desc"),
            ("ocean", "#0284C7", "settings.theme_ocean", "settings.theme_ocean_desc"),
            ("royal", "#831843", "settings.theme_royal", "settings.theme_royal_desc"),
        ]

        row, col = 0, 0
        for key, color_hex, title_key, desc_key in self._theme_meta:
            box = QFrame()
            box.setProperty("class", "surface")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(12, 12, 12, 12)
            box_layout.setSpacing(6)

            radio = QRadioButton(t(title_key))
            radio.setFont(QFont("Hanken Grotesk", 11, QFont.Weight.Bold))
            if self._current_theme == key:
                radio.setChecked(True)
            self._theme_group.addButton(radio)
            self._radios[key] = (radio, title_key, desc_key)

            radio.toggled.connect(lambda checked, k=key: self._on_theme_selected(checked, k))

            desc_label = QLabel(t(desc_key))
            desc_label.setFont(QFont("Hanken Grotesk", 10))
            desc_label.setStyleSheet("color: #6B7264;")
            desc_label.setWordWrap(True)

            color_bar = QFrame()
            color_bar.setFixedHeight(6)
            color_bar.setStyleSheet(f"background-color: {color_hex}; border-radius: 3px;")

            box_layout.addWidget(radio)
            box_layout.addWidget(color_bar)
            box_layout.addWidget(desc_label)

            self._theme_grid.addWidget(box, row, col)
            col += 1
            if col > 1:
                col = 0
                row += 1

        theme_card_layout.addLayout(self._theme_grid)
        layout.addWidget(self._theme_card)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def _on_lang_combo_changed(self, index: int):
        new_lang = self._lang_combo.currentData() or "fr"
        self.language_changed.emit(new_lang)

    def _on_theme_selected(self, checked: bool, key: str):
        if checked:
            self._current_theme = key
            save_theme(key)
            self.theme_changed.emit(key)

    def retranslate_ui(self):
        """Update all text on the settings page when language changes."""
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)
        self._header_lbl.setText(t("settings.title"))
        self._subtitle_lbl.setText(t("settings.subtitle"))
        self._lang_title.setText(t("settings.language_card_title"))
        self._lang_label.setText(t("settings.language_label"))
        self._theme_title.setText(t("settings.theme_card_title"))
        self._theme_subtitle.setText(t("settings.theme_subtitle"))

        for key, (radio, title_key, desc_key) in self._radios.items():
            radio.setText(t(title_key))

        cur_lang = get_language()
        idx = self._lang_combo.findData(cur_lang)
        if idx >= 0 and self._lang_combo.currentIndex() != idx:
            self._lang_combo.blockSignals(True)
            self._lang_combo.setCurrentIndex(idx)
            self._lang_combo.blockSignals(False)
