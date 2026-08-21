from PySide6.QtGui import QColor

THEME_PALETTES = {
    "emerald": {
        "PRIMARY": "#1E4D38",
        "PRIMARY_HOVER": "#276147",
        "PRIMARY_DARK": "#143626",
        "SECONDARY": "#B88E56",
        "SECONDARY_LIGHT": "#D4AF37",
        "SECONDARY_DARK": "#8E6B3A",
        "BG_BASE": "#F7F8F4",
        "SURFACE": "#FFFFFF",
        "SURFACE_VARIANT": "#F0F3EC",
        "TEXT_PRIMARY": "#1A221A",
        "TEXT_SECONDARY": "#637060",
        "TEXT_TERTIARY": "#909C8E",
        "BORDER": "#E2E6DC",
        "BORDER_LIGHT": "#ECEFE7",
    },
    "midnight": {
        "PRIMARY": "#2563EB",
        "PRIMARY_HOVER": "#3B82F6",
        "PRIMARY_DARK": "#1D4ED8",
        "SECONDARY": "#F59E0B",
        "SECONDARY_LIGHT": "#FCD34D",
        "SECONDARY_DARK": "#D97706",
        "BG_BASE": "#0B0F19",
        "SURFACE": "#111827",
        "SURFACE_VARIANT": "#1F2937",
        "TEXT_PRIMARY": "#F9FAFB",
        "TEXT_SECONDARY": "#9CA3AF",
        "TEXT_TERTIARY": "#6B7280",
        "BORDER": "#374151",
        "BORDER_LIGHT": "#1F2937",
    },
    "graphite": {
        "PRIMARY": "#3F3F46",
        "PRIMARY_HOVER": "#52525B",
        "PRIMARY_DARK": "#27272A",
        "SECONDARY": "#A1A1AA",
        "SECONDARY_LIGHT": "#D4D4D8",
        "SECONDARY_DARK": "#71717A",
        "BG_BASE": "#18181B",
        "SURFACE": "#27272A",
        "SURFACE_VARIANT": "#3F3F46",
        "TEXT_PRIMARY": "#F4F4F5",
        "TEXT_SECONDARY": "#A1A1AA",
        "TEXT_TERTIARY": "#71717A",
        "BORDER": "#52525B",
        "BORDER_LIGHT": "#3F3F46",
    },
    "ocean": {
        "PRIMARY": "#0284C7",
        "PRIMARY_HOVER": "#0EA5E9",
        "PRIMARY_DARK": "#0369A1",
        "SECONDARY": "#38BDF8",
        "SECONDARY_LIGHT": "#7DD3FC",
        "SECONDARY_DARK": "#0284C7",
        "BG_BASE": "#0A192F",
        "SURFACE": "#112240",
        "SURFACE_VARIANT": "#233554",
        "TEXT_PRIMARY": "#CCD6F6",
        "TEXT_SECONDARY": "#8892B0",
        "TEXT_TERTIARY": "#64FFDA",
        "BORDER": "#233554",
        "BORDER_LIGHT": "#112240",
    },
    "royal": {
        "PRIMARY": "#831843",
        "PRIMARY_HOVER": "#9D174D",
        "PRIMARY_DARK": "#701A75",
        "SECONDARY": "#FBBF24",
        "SECONDARY_LIGHT": "#FDE047",
        "SECONDARY_DARK": "#F59E0B",
        "BG_BASE": "#1C1018",
        "SURFACE": "#2D1B2E",
        "SURFACE_VARIANT": "#4A2545",
        "TEXT_PRIMARY": "#FCE7F3",
        "TEXT_SECONDARY": "#FBCFE8",
        "TEXT_TERTIARY": "#F9A8D4",
        "BORDER": "#831843",
        "BORDER_LIGHT": "#4A2545",
    },
}

# Track the currently active theme name for palette lookups
_current_theme_name: str = "emerald"

def set_current_theme(name: str):
    global _current_theme_name
    _current_theme_name = name

def get_current_palette() -> dict:
    """Return the active THEME_PALETTES entry."""
    return THEME_PALETTES.get(_current_theme_name, THEME_PALETTES["emerald"])

class Theme:
    STATUS_GREEN_BG = "#EAF5EC"
    STATUS_GREEN_TEXT = "#1B5E20"
    STATUS_ORANGE_BG = "#FEF3E6"
    STATUS_ORANGE_TEXT = "#B76200"
    STATUS_GOLD_BG = "#FEF9E7"
    STATUS_GOLD_TEXT = "#8D6E1A"
    STATUS_RED_BG = "#FDEAEA"
    STATUS_RED_TEXT = "#B71C1C"
    STATUS_GRAY_BG = "#EAECEE"
    STATUS_GRAY_TEXT = "#37474F"

def get_app_stylesheet(theme_name: str = "emerald") -> str:
    """Returns the global stylesheet for the ATELIER BERLIN LOCATION CAR application based on the selected theme."""
    set_current_theme(theme_name)
    t = THEME_PALETTES.get(theme_name, THEME_PALETTES["emerald"])
    return f"""
    /* GLOBAL DEFAULTS */
    * {{
        font-family: "Hanken Grotesk", "Segoe UI", sans-serif;
        color: {t['TEXT_PRIMARY']};
    }}

    QMainWindow, QDialog, QWidget#main_container {{
        background-color: {t['BG_BASE']};
    }}

    /* SCROLLBARS */
    QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: {t['BORDER']};
        min-height: 20px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t['TEXT_TERTIARY']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    QScrollBar:horizontal {{
        border: none;
        background: transparent;
        height: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {t['BORDER']};
        min-width: 20px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {t['TEXT_TERTIARY']};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}

    /* SIDEBAR */
    QFrame#sidebar {{
        background-color: {t['SURFACE']};
        border-right: 1px solid {t['BORDER']};
    }}

    QPushButton.nav_btn {{
        text-align: left;
        padding-left: 16px;
        padding-right: 16px;
        border: none;
        border-radius: 8px;
        background-color: transparent;
        color: {t['TEXT_SECONDARY']};
    }}
    QPushButton.nav_btn:hover {{
        background-color: {t['SURFACE_VARIANT']};
        color: {t['TEXT_PRIMARY']};
    }}
    QPushButton.nav_btn[active="true"] {{
        background-color: {t['PRIMARY']};
        color: #FFFFFF;
        font-weight: bold;
    }}
    QPushButton.nav_btn[unread="true"] {{
        color: {t['SECONDARY_DARK']};
        font-weight: bold;
    }}

    /* TOP BAR */
    #topbar, QWidget#topbar, QFrame#topbar {{
        background-color: {t['SURFACE']};
        border-bottom: 1px solid {t['BORDER']};
        min-height: 56px;
    }}

    /* CARDS & SURFACES */
    QFrame#statCard, QFrame#fleetCard, QFrame#periodCard, QFrame[card="true"],
    #statCard, #fleetCard, #periodCard, .card, [card="true"] {{
        background-color: {t['SURFACE']};
        border: 1px solid {t['BORDER']};
        border-radius: 10px;
    }}

    QFrame#statCard:hover, QFrame#fleetCard:hover {{
        border-color: {t['PRIMARY']};
    }}

    QFrame.surface {{
        background-color: {t['SURFACE_VARIANT']};
        border: 1px solid {t['BORDER_LIGHT']};
        border-radius: 8px;
    }}

    /* PROGRESS BARS */
    QProgressBar {{
        border: none;
        background-color: {t['SURFACE_VARIANT']};
        border-radius: 3px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {t['PRIMARY']};
        border-radius: 3px;
    }}

    /* GROUP BOX */
    QGroupBox {{
        background-color: {t['SURFACE']};
        border: 1px solid {t['BORDER']};
        border-radius: 10px;
        margin-top: 14px;
        padding-top: 16px;
        font-weight: bold;
        color: {t['TEXT_PRIMARY']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 10px;
        color: {t['TEXT_PRIMARY']};
        font-size: 13px;
    }}

    /* BUTTONS */
    QPushButton {{
        background-color: {t['SURFACE']};
        border: 1px solid {t['BORDER']};
        border-radius: 6px;
        padding: 6px 12px;
        color: {t['TEXT_PRIMARY']};
    }}
    QPushButton:hover {{
        background-color: {t['SURFACE_VARIANT']};
        border-color: {t['TEXT_TERTIARY']};
    }}
    QPushButton:pressed {{
        background-color: {t['BORDER']};
    }}
    QPushButton:disabled {{
        background-color: {t['BG_BASE']};
        color: {t['TEXT_TERTIARY']};
        border-color: {t['BORDER_LIGHT']};
    }}

    QPushButton.primary {{
        background-color: {t['PRIMARY']};
        color: #FFFFFF;
        border: none;
    }}
    QPushButton.primary:hover {{
        background-color: {t['PRIMARY_HOVER']};
    }}
    QPushButton.primary:pressed {{
        background-color: {t['PRIMARY_DARK']};
    }}
    QPushButton.primary:disabled {{
        background-color: {t['TEXT_TERTIARY']};
        color: #FFFFFF;
    }}

    QPushButton.danger {{
        background-color: {Theme.STATUS_RED_TEXT};
        color: #FFFFFF;
        border: none;
    }}
    QPushButton.danger:hover {{
        background-color: #D32F2F;
    }}

    /* INPUTS */
    QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox, QTextEdit {{
        background-color: {t['SURFACE']};
        border: 1px solid {t['BORDER']};
        border-radius: 6px;
        padding: 6px 10px;
        color: {t['TEXT_PRIMARY']};
        selection-background-color: {t['PRIMARY']};
    }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTextEdit:focus {{
        border: 1px solid {t['PRIMARY']};
        background-color: {t['SURFACE']};
    }}
    QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QTextEdit:disabled {{
        background-color: {t['BG_BASE']};
        color: {t['TEXT_TERTIARY']};
    }}

    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 5px solid {t['TEXT_SECONDARY']};
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        border: 1px solid {t['BORDER']};
        background-color: {t['SURFACE']};
        selection-background-color: {t['PRIMARY']};
        selection-color: #FFFFFF;
        outline: none;
    }}

    /* TABLES */
    QTableWidget, QTableView {{
        background-color: {t['SURFACE']};
        alternate-background-color: {t['BG_BASE']};
        border: 1px solid {t['BORDER']};
        border-radius: 8px;
        gridline-color: {t['BORDER_LIGHT']};
        selection-background-color: {t['PRIMARY']};
        selection-color: #FFFFFF;
    }}
    QHeaderView::section {{
        background-color: {t['SURFACE_VARIANT']};
        color: {t['TEXT_SECONDARY']};
        padding: 8px;
        border: none;
        border-bottom: 1px solid {t['BORDER']};
        border-right: 1px solid {t['BORDER_LIGHT']};
        font-weight: bold;
    }}
    QTableWidget::item {{
        padding: 4px;
        border-bottom: 1px solid {t['BORDER_LIGHT']};
    }}

    /* TABS */
    QTabWidget::pane {{
        border: 1px solid {t['BORDER']};
        border-radius: 8px;
        background: {t['SURFACE']};
        top: -1px;
    }}
    QTabBar::tab {{
        background: {t['SURFACE_VARIANT']};
        border: 1px solid {t['BORDER']};
        padding: 8px 16px;
        margin-right: 4px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        color: {t['TEXT_SECONDARY']};
    }}
    QTabBar::tab:selected {{
        background: {t['SURFACE']};
        border-bottom-color: {t['SURFACE']};
        color: {t['PRIMARY']};
        font-weight: bold;
    }}
    QTabBar::tab:hover:!selected {{
        background: {t['BORDER_LIGHT']};
        color: {t['TEXT_PRIMARY']};
    }}

    /* DIALOGS */
    QDialog {{
        background-color: {t['BG_BASE']};
    }}
    """
