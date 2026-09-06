# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]
DESKTOP = ROOT / "desktop"
APP = DESKTOP / "app"

app_analysis = Analysis(
    [str(APP / "main.py")],
    pathex=[str(DESKTOP), str(ROOT)],
    binaries=[],
    datas=[
        (str(APP / "assets/images/logo_transparent_officiel.png"), "app/assets/images"),
        (str(APP / "i18n/*.json"), "app/i18n"),
        (str(ROOT / "shared/*.py"), "shared"),
    ],
    hiddenimports=[
        "PySide6.QtWebSockets", "PySide6.QtNetwork", "PySide6.QtCore",
        "PySide6.QtGui", "PySide6.QtWidgets", "sqlalchemy.dialects.sqlite", "tzdata",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(app_analysis.pure)
exe = EXE(
    pyz,
    app_analysis.scripts,
    [],
    exclude_binaries=True,
    name="ATELIER_BERLIN_LOCATION_CAR",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=[str(APP / "assets/images/logo_transparent_officiel.png")],
)
coll = COLLECT(
    exe,
    app_analysis.binaries,
    app_analysis.datas,
    strip=False,
    upx=False,
    name="ATELIER_BERLIN_LOCATION_CAR",
)
