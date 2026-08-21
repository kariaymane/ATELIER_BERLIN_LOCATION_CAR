"""
Desktop i18n — translation manager with live language switching.
Loads JSON translation files and supports French + Arabic with RTL.
"""
import json
from pathlib import Path
from typing import Optional

_current_lang = "fr"
_translations: dict[str, dict] = {}
_i18n_dir = Path(__file__).parent


def load_translations():
    """Load all translation files."""
    global _translations
    _translations.clear()
    for lang_file in _i18n_dir.glob("*.json"):
        lang = lang_file.stem
        try:
            with open(lang_file, "r", encoding="utf-8") as f:
                _translations[lang] = json.load(f)
        except Exception as e:
            print(f"Error loading translation {lang_file}: {e}")


def set_language(lang: str):
    """Set the current language."""
    global _current_lang
    if not _translations:
        load_translations()
    if lang in _translations or lang in ("fr", "ar"):
        _current_lang = lang


def get_language() -> str:
    """Get the current language code."""
    return _current_lang


def is_rtl() -> bool:
    """Check if current language is RTL."""
    return _current_lang == "ar"


def t(key: str, **kwargs) -> str:
    """
    Get translated string by dot-notation key.
    Example: t("vehicles.title") -> "Véhicules" / "السيارات"
    """
    if not _translations:
        load_translations()

    parts = key.split(".")
    value = _translations.get(_current_lang, {})
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
            break

    if value is None:
        # Fallback to French
        value = _translations.get("fr", {})
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return key

    if isinstance(value, str) and kwargs:
        try:
            value = value.format(**kwargs)
        except (KeyError, ValueError):
            pass

    return value if isinstance(value, str) else key


# Load on import
load_translations()
