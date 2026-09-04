# 🏛️ FINAL RELEASE BUILD REPORT — v1.1.2

**Project:** ATELIER BERLIN LOCATION CAR  
**Release Tag:** `v1.1.2`  
**Git HEAD SHA:** `14acb89b05fb12e301d3e8a2c748ab7cd196d259`  
**Commit Message:** `fix(forensics): remediate reservation, vehicle, and dashboard data integrity across architecture`  
**Build Date (UTC):** `2026-09-04 16:32:47 UTC`  
**Build Date (Local):** `2026-09-04 17:32:47 +01:00`  
**Audit Standard:** ZERO-ASSUMPTION • ZERO-SUPERFICIAL-FIX • ZERO-UNVERIFIED-RELEASE  

---

## 1. Provenance & Git Head Verification

- **Branch:** `main`
- **HEAD Commit SHA:** `14acb89b05fb12e301d3e8a2c748ab7cd196d259`
- **Commit Timestamp:** `2026-09-04 17:11:40 +01:00` (`16:11:40 UTC`)
- **Working Tree State:** Clean (no uncommitted changes in tracked or untracked operational code)

---

## 2. Test Gate Results (Pre-Build)

All 4 test gates were executed against HEAD `14acb89` and completed with 100% pass rates:

### Gate 1: Backend Test Suite
- **Command:** `/home/ayman/car-rental-system/backend/venv/bin/pytest backend/tests/`
- **Result:** `229 passed, 7 warnings in 11.89s`
- **Exit Code:** `0`

### Gate 2: 3-Tier Data Reconciliation
- **Command:** `python3 scripts/reconcile_data.py`
- **Result:** `🎉 PERFECT ZERO-DEFECT RECONCILIATION: 0 discrepancies across PostgreSQL, FastAPI, and Desktop SQLite!`
- **Audit:** 4 vehicles and 2 reservations audited across IDs, foreign keys, timestamps, statuses, and pricing.
- **Exit Code:** `0`

### Gate 3: Mobile Unit Tests
- **Command:** `./gradlew testDebugUnitTest --rerun-tasks` (in `mobile/`)
- **Result:** `BUILD SUCCESSFUL in 1m 49s (33 actionable tasks executed)`
- **Exit Code:** `0`

### Gate 4: Desktop Pytest Suite
- **Command:** `PYTHONPATH=desktop /home/ayman/car-rental-system/desktop/venv/bin/pytest desktop/tests/`
- **Result:** `315 passed in 874.20s (14m 34s)`
- **Exit Code:** `0`

---

## 3. Fresh Artifact Builds

### 📱 Android Standalone APK
- **Command:** `./gradlew assembleDebug --no-build-cache --rerun-tasks` (in `mobile/`)
- **File Output:** `/home/ayman/car-rental-system/ATELIER_BERLIN_LOCATION_CAR_v1.1.2.apk`
- **Build Timestamp (UTC):** `2026-09-04 16:30:12 UTC`
- **File Size:** `23,375,146 bytes` (~23.4 MB)
- **SHA256:** `9b90c078be2e7ed21eec88fa076468b01555ff855254439290a4b6ef71c8700c`
- **Signature Verification:** Verified via `apksigner` (APK Signature Scheme v2: `true`, 1 signer)
- **Package:** `com.example`
- **Launchable Activity:** `com.example.MainActivity`
- **Provenance Proof:** Build timestamp is +18m 32s newer than git commit `14acb89`.

### 🪟 Windows Desktop Executable & ZIP
- **Build Toolchain:** Wine 11.0 + Windows CPython 3.11.9 (AMD64) + PyInstaller 6.22.2
- **Command:** `rm -rf build dist && wine venv_wine/Scripts/pyinstaller.exe --noconfirm --clean ATELIER_BERLIN_LOCATION_CAR.spec` (in `packaging/windows/`)
- **ZIP Packaging:** `cd packaging/windows/dist && zip -r /home/ayman/car-rental-system/ATELIER_BERLIN_LOCATION_CAR_WINDOWS_v1.1.2.zip ATELIER_BERLIN_LOCATION_CAR/`
- **Main Executable:** `packaging/windows/dist/ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe`
- **EXE Size:** `9,169,244 bytes`
- **EXE SHA256:** `84f9b477465858e429523f3fd044f825e0dbab82dee8f4e6c6daae6a2eef6515`
- **EXE Timestamp (UTC):** `2026-09-04 16:32:14 UTC`
- **Startup Verification:** Successfully booted via Wine in offscreen mode. Connected to health check endpoint with HTTP 200 OK.
- **ZIP Archive:** `/home/ayman/car-rental-system/ATELIER_BERLIN_LOCATION_CAR_WINDOWS_v1.1.2.zip`
- **ZIP Size:** `61,982,146 bytes` (~62.0 MB)
- **ZIP SHA256:** `0bd6a09cea83d1c9f9de2592d137758726dcdf7adf3ca8ad3027e74137aca137`
- **ZIP Timestamp (UTC):** `2026-09-04 16:32:47 UTC`
- **Provenance Proof:** Build timestamp is +21m 07s newer than git commit `14acb89`.

---

## 4. Artifact Cryptographic Inventory Table

| Artifact | Path | Size (Bytes) | SHA256 Hash | Build Status |
|---|---|---|---|---|
| **Android APK** | `ATELIER_BERLIN_LOCATION_CAR_v1.1.2.apk` | `23,375,146` | `9b90c078be2e7ed21eec88fa076468b01555ff855254439290a4b6ef71c8700c` | ✅ FRESH BUILD (Scheme v2 verified) |
| **Windows EXE** | `packaging/windows/dist/ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` | `9,169,244` | `84f9b477465858e429523f3fd044f825e0dbab82dee8f4e6c6daae6a2eef6515` | ✅ FRESH BUILD (Wine boot verified) |
| **Windows ZIP** | `ATELIER_BERLIN_LOCATION_CAR_WINDOWS_v1.1.2.zip` | `61,982,146` | `0bd6a09cea83d1c9f9de2592d137758726dcdf7adf3ca8ad3027e74137aca137` | ✅ FRESH BUILD (Fresh payload packaged) |

---

## 5. Verification Limitations Disclosures

1. **Hardware Native Win32 Display:** The Windows executable was cross-compiled using Wine PyInstaller on Linux and verified for process creation, database creation, and network connectivity. Native bare-metal Windows 10/11 DirectX/GDI rendering requires a physical Windows machine.
2. **Hardware Android Display:** The Android APK was compiled with Android SDK 36 and verified with `apksigner` and unit test suites. Physical touch interaction requires a hardware Android phone attached via ADB.

---

## 6. Conclusion & Gate Sign-Off

All forensic fixes have been built from the source commit `14acb89` into completely fresh, verified release artifacts for version `v1.1.2`. No old artifacts or cached binaries were reused.

