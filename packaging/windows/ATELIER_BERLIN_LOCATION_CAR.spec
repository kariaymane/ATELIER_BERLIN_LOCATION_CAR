# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['../../desktop/app/main.py'],
    pathex=[],
    binaries=[],
    datas=[('../../desktop/app/assets', 'app/assets'), ('../../desktop/app/i18n', 'app/i18n'), ('../../shared', 'shared')],
    hiddenimports=['PySide6.QtWebSockets', 'PySide6.QtNetwork', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'tzdata'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ATELIER_BERLIN_LOCATION_CAR',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['../../desktop/app/assets/images/logo_transparent_officiel.png'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ATELIER_BERLIN_LOCATION_CAR',
)
