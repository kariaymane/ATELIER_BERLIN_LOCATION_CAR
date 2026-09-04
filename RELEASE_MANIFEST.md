# RELEASE MANIFEST — v1.1.2

| Field | Value |
|---|---|
| Release Tag | `v1.1.2` |
| Git Branch | `main` |
| Git Commit SHA | `e0a3b931106a4918dd4b19f84984fc3b9b6be832` |
| Build Timestamp (UTC) | 2026-09-04 17:16:18 UTC |
| Build Timestamp (Local) | 2026-09-04 18:16:18 +01:00 |
| Tree State | Clean (Built directly from HEAD e0a3b93) |

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
| ZIP Size | 62,074,324 bytes |
| ZIP SHA256 | `d2c4b2c7180cb9f7f36f1e282ad3f6a1c225551115765444e9040c854b26ad33` |
| Executable | `ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` |
| EXE Size | 9,142,670 bytes |
| EXE SHA256 | `a89dbec83971d59405f5d92b48e130e94fd4e9539aa3f44e3f9818e50b8725a1` |
| Signing Status | Unsigned (Developer / Ad-hoc Windows distribution) |
| Features | Zero horizontal table overflow, lifecycle-correct action buttons (`RESERVED`: Activer+Annuler; `ACTIVE`: Terminer+Annuler), no mnemonic accelerator stripping (`En cours et à venir`), unclipped dashboard refresh time, unclipped fleet cards (`En maintenance`), unclipped vehicle add button, canonical Africa/Casablanca date formatting, 100% dashboard KPI parity with fleet status |

---

## 🏛️ Verification Gates Passed

- [x] Full Desktop Test Suite: 315 passed, 0 failed, exit code 0 (13m 10s)
- [x] Full Backend Test Suite: 229 passed, 0 failed, exit code 0 (14.34s)
- [x] Full Mobile Test Suite (`./gradlew testDebugUnitTest --rerun-tasks`): 33/33 passed, exit code 0 (2m 34s)
- [x] 3-Tier Data Reconciliation Tool (`scripts/reconcile_data.py`): 100% agreement across PostgreSQL, FastAPI, and Desktop SQLite (0 discrepancies)
- [x] Clean Build Verification: Android APK and Windows EXE built from CURRENT HEAD `e0a3b93` with fresh timestamps

