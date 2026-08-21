"""
Desktop application configuration.
Supports development mode, production packaging, user AppData paths, and .env configuration.
"""
import sys
import os
from pathlib import Path

# Load .env configuration if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def get_data_dir() -> Path:
    """Get writable application data directory."""
    if getattr(sys, 'frozen', False):
        # Running in a packaged PyInstaller executable
        if sys.platform == "win32" and "APPDATA" in os.environ:
            data_dir = Path(os.environ["APPDATA"]) / "CarRentalSystem" / "data"
        else:
            data_dir = Path.home() / ".car-rental-desktop" / "data"
    else:
        # Development mode
        data_dir = Path(__file__).parent / "data"

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

APP_DIR = Path(__file__).parent
DATA_DIR = get_data_dir()
DB_PATH = DATA_DIR / "car_rental_local.db"
SQLITE_URL = f"sqlite:///{DB_PATH}"

# API
API_BASE_URL = os.environ.get("API_BASE_URL", "https://car-rental-system.fly.dev/api/v1")
WS_URL = os.environ.get("WS_URL", "wss://car-rental-system.fly.dev/api/v1/ws")
API_VERSION = "v1"

# Sync
SYNC_INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL", "30"))

# UI
DEFAULT_LANGUAGE = os.environ.get("DEFAULT_LANGUAGE", "fr")
DEFAULT_THEME = os.environ.get("DEFAULT_THEME", "emerald")

THEMES = [
    ("emerald", "Pistache (Doux & Naturel)"),
    ("midnight", "Midnight (Obsidian & Cobalt)"),
    ("graphite", "Graphite (Slate & Zinc)"),
    ("ocean", "Ocean (Marine & Cyan)"),
    ("royal", "Royal (Burgundy & Gold)"),
]

def get_saved_theme() -> str:
    settings_file = DATA_DIR / "settings.json"
    if settings_file.exists():
        try:
            import json
            with open(settings_file, "r") as f:
                data = json.load(f)
                theme = data.get("theme", DEFAULT_THEME)
                if theme in [t[0] for t in THEMES]:
                    return theme
        except Exception:
            pass
    return DEFAULT_THEME

def save_theme(theme_name: str):
    settings_file = DATA_DIR / "settings.json"
    try:
        import json
        data = {}
        if settings_file.exists():
            with open(settings_file, "r") as f:
                data = json.load(f)
        data["theme"] = theme_name
        with open(settings_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def get_saved_language() -> str:
    settings_file = DATA_DIR / "settings.json"
    if settings_file.exists():
        try:
            import json
            with open(settings_file, "r") as f:
                data = json.load(f)
                lang = data.get("language", DEFAULT_LANGUAGE)
                if lang in ("fr", "ar"):
                    return lang
        except Exception:
            pass
    return DEFAULT_LANGUAGE

def save_language(lang_code: str):
    settings_file = DATA_DIR / "settings.json"
    try:
        import json
        data = {}
        if settings_file.exists():
            with open(settings_file, "r") as f:
                data = json.load(f)
        data["language"] = lang_code
        with open(settings_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
