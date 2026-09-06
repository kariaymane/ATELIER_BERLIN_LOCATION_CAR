# Build on Windows using one authoritative PyInstaller specification.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Venv = Join-Path $PSScriptRoot ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

function Invoke-Checked {
    param([string]$Command, [string[]]$CommandArgs)
    & $Command @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Build command failed with exit code $LASTEXITCODE."
    }
}

Invoke-Checked -Command "python" -CommandArgs @("-m", "venv", $Venv)
Invoke-Checked -Command $Python -CommandArgs @(
    "-m", "pip", "install", "-r", (Join-Path $Root "desktop\requirements.txt"),
    "pyinstaller>=6,<7", "Pillow>=11,<13"
)
Invoke-Checked -Command $Python -CommandArgs @(
    "-m", "PyInstaller", "--noconfirm", "--clean",
    "--distpath", (Join-Path $PSScriptRoot "dist"),
    "--workpath", (Join-Path $PSScriptRoot "build"),
    (Join-Path $PSScriptRoot "ATELIER_BERLIN_LOCATION_CAR.spec")
)
$Executable = Join-Path $PSScriptRoot "dist\ATELIER_BERLIN_LOCATION_CAR\ATELIER_BERLIN_LOCATION_CAR.exe"
if (-not (Test-Path -LiteralPath $Executable)) {
    throw "The expected Windows executable was not produced."
}
Write-Host "Windows desktop build completed: $Executable"
