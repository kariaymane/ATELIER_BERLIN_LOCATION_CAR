# RELEASE MANIFEST — v1.1.2

| Field | Value |
|---|---|
| Release Tag | `v1.1.2` |
| Git Branch | `main` |
| Git Commit SHA | `14acb89b05fb12e301d3e8a2c748ab7cd196d259` |
| Build Timestamp (UTC) | 2026-09-04 16:32:47 UTC |
| Build Timestamp (Local) | 2026-09-04 17:32:47 +01:00 |
| Tree State | Clean (Built directly from HEAD 14acb89) |

---

## 📱 Android Artifact

| Field | Value |
|---|---|
| File | `ATELIER_BERLIN_LOCATION_CAR_v1.1.2.apk` |
| Type | Standalone Android APK |
| Size | 23,375,146 bytes |
| SHA256 | `9b90c078be2e7ed21eec88fa076468b01555ff855254439290a4b6ef71c8700c` |
| Signing Status | Signed with Android Debug Keystore (Scheme v2: Verified) |
| Package Name | `com.example` |
| Launchable Activity | `com.example.MainActivity` |
| Features | Server data authority, dynamic time-liveness fleet updates, midnight rollover support, maintenance-over-active-rental protection, 33-vector revenue parity, offline Room sync, strict reservation lifecycle separation |

---

## 🪟 Windows Desktop Artifact

| Field | Value |
|---|---|
| ZIP Archive | `ATELIER_BERLIN_LOCATION_CAR_WINDOWS_v1.1.2.zip` |
| ZIP Size | 61,982,146 bytes |
| ZIP SHA256 | `0bd6a09cea83d1c9f9de2592d137758726dcdf7adf3ca8ad3027e74137aca137` |
| Executable | `ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` |
| EXE Size | 9,169,244 bytes |
| EXE SHA256 | `84f9b477465858e429523f3fd044f825e0dbab82dee8f4e6c6daae6a2eef6515` |
| Signing Status | Unsigned (Developer / Ad-hoc Windows distribution) |
| Features | Full multi-domain SQLite bootstrap reconciliation, dual subtab reservations (`En cours & À venir` vs `Historique`), 300px action column (no clipping), canonical `Africa/Casablanca` date formatting, 100% dashboard KPI parity with fleet status, production DB deletion safety guard |

---

## 🏛️ Verification Gates Passed

- [x] Full Desktop Test Suite: 315 passed, 0 failed, exit code 0 (14m 34s)
- [x] Full Backend Test Suite: 229 passed, 0 failed, exit code 0 (11.89s)
- [x] Full Mobile Test Suite (`./gradlew testDebugUnitTest --rerun-tasks`): 33/33 passed, exit code 0 (1m 49s)
- [x] 3-Tier Data Reconciliation Tool (`scripts/reconcile_data.py`): 100% agreement across PostgreSQL, FastAPI, and Desktop SQLite (0 discrepancies)
- [x] Clean Build Verification: Android APK and Windows EXE built from HEAD `14acb89` with fresh timestamps

