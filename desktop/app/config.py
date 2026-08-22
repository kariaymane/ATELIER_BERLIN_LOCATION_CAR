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
    """Get writable application data directory, prioritizing OS standards."""
    app_name = "CarRentalSystem"
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", "~")).expanduser()
        data_dir = base / app_name / "data"
    elif sys.platform == "darwin":
        data_dir = Path.home() / "Library" / "Application Support" / app_name / "data"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
        data_dir = base / app_name / "data"

    data_dir.mkdir(parents=True, exist_ok=True)
    
    # Migration logic for old database paths
    new_db_path = data_dir / "car_rental_local.db"
    
    if not new_db_path.exists():
        legacy_paths = [
            Path(__file__).parent / "data" / "car_rental_local.db",
            Path.home() / ".car-rental-desktop" / "data" / "car_rental_local.db"
        ]
        
        for old_path in legacy_paths:
            if old_path.exists():
                try:
                    import shutil
                    shutil.copy2(old_path, new_db_path)
                    print(f"Migrated old database from {old_path} to {new_db_path}")
                    break
                except Exception as e:
                    print(f"Failed to migrate database: {e}")
                    
    # Also migrate settings if they exist
    new_settings = data_dir / "settings.json"
    if not new_settings.exists():
        legacy_settings = [
            Path(__file__).parent / "data" / "settings.json",
            Path.home() / ".car-rental-desktop" / "data" / "settings.json"
        ]
        for old_path in legacy_settings:
            if old_path.exists():
                try:
                    import shutil
                    shutil.copy2(old_path, new_settings)
                    break
                except Exception:
                    pass
                    
    return data_dir

APP_DIR = Path(__file__).parent
DATA_DIR = get_data_dir()
DB_PATH = DATA_DIR / "car_rental_local.db"
SQLITE_URL = f"sqlite:///{DB_PATH}"

# API
_raw_api_url = os.environ.get("API_BASE_URL", "https://car-rental-system.fly.dev").rstrip("/")
if _raw_api_url.endswith("/api/v1"):
    _raw_api_url = _raw_api_url[:-7]
API_BASE_URL = _raw_api_url
WS_URL = os.environ.get("WS_URL", f"{API_BASE_URL.replace('http://', 'ws://').replace('https://', 'wss://')}/api/v1/events/ws")
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
