# Windows Build Script for ATELIER BERLIN LOCATION CAR
$ErrorActionPreference = "Stop"

Write-Host "Creating clean Python virtual environment..."
python -m venv venv
.\venv\Scripts\Activate.ps1

Write-Host "Installing dependencies..."
pip install --upgrade pip
pip install -r ..\..\desktop\requirements.txt
pip install pyinstaller Pillow

Write-Host "Building ATELIER BERLIN LOCATION CAR executable..."
# Include PySide6 and standard dependencies
pyinstaller --noconsole --name "ATELIER_BERLIN_LOCATION_CAR" `
    --icon="..\..\desktop\app\assets\images\logo_transparent_officiel.png" `
    --add-data="..\..\desktop\app\assets;app\assets" `
    --add-data="..\..\desktop\app\i18n;app\i18n" `
    --add-data="..\..\shared;shared" `
    --hidden-import="PySide6.QtWebSockets" `
    --hidden-import="PySide6.QtNetwork" `
    --hidden-import="PySide6.QtCore" `
    --hidden-import="PySide6.QtGui" `
    --hidden-import="PySide6.QtWidgets" `
    --clean `
    ..\..\desktop\app\main.py

Write-Host "Verifying executable..."
if (Test-Path "dist\ATELIER_BERLIN_LOCATION_CAR\ATELIER_BERLIN_LOCATION_CAR.exe") {
    Write-Host "Build SUCCESS: Executable created at dist\ATELIER_BERLIN_LOCATION_CAR\ATELIER_BERLIN_LOCATION_CAR.exe"
} else {
    Write-Host "Build FAILED: Executable not found!"
    exit 1
}
