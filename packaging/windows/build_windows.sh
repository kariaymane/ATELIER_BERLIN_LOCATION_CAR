#!/bin/bash
set -e

echo "Building ATELIER BERLIN LOCATION CAR executable..."
wine cmd /c "venv_wine\\Scripts\\pyinstaller.exe --noconfirm --noconsole --name ATELIER_BERLIN_LOCATION_CAR \
    --icon=..\\..\\desktop\\app\\assets\\images\\logo_transparent_officiel.png \
    --add-data=..\\..\\desktop\\app\\assets;app\\assets \
    --add-data=..\\..\\desktop\\app\\i18n;app\\i18n \
    --add-data=..\\..\\shared;shared \
    --hidden-import=PySide6.QtWebSockets \
    --hidden-import=PySide6.QtNetwork \
    --hidden-import=PySide6.QtCore \
    --hidden-import=PySide6.QtGui \
    --hidden-import=PySide6.QtWidgets \
    --hidden-import=tzdata \
    --clean \
    ..\\..\\desktop\\app\\main.py"

echo "Verifying executable..."
if [ -f "dist/ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe" ]; then
    echo "Build SUCCESS: Executable created at dist/ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe"
    echo "Creating ZIP..."
    cd dist && zip -r ../../../ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip ATELIER_BERLIN_LOCATION_CAR/
else
    echo "Build FAILED: Executable not found!"
    exit 1
fi
