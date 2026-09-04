# RELEASE MANIFEST — v1.1.1

| Field | Value |
|---|---|
| Release Tag | `v1.1.1` |
| Git Branch | `main` |
| Git Commit SHA | `13db86bde72a2ace7b24f6e7d87000be400c4843` |
| Build Date (UTC) | 2026-09-04 03:05:00 |
| Tree State | Clean |

---

## 📱 Android Artifact

| Field | Value |
|---|---|
| File | `ATELIER_BERLIN_LOCATION_CAR_v1.1.1.apk` |
| Type | Standalone Android APK |
| Size | 23,567,287 bytes |
| SHA256 | `09fc5ac15f47e943cf536fc4c1e2a1cc1f6baff0216b8e42d25cf6122448bc9b` |
| Signing Status | Signed with Android Debug Keystore (Scheme v2: Verified) |
| Package Name | `com.example` |
| Launchable Activity | `com.example.MainActivity` |
| Features | Server data authority, dynamic time-liveness fleet updates, midnight rollover support, maintenance-over-active-rental protection, 33-vector revenue parity, offline Room sync |

---

## 🪟 Windows Desktop Artifact

| Field | Value |
|---|---|
| ZIP Archive | `ATELIER_BERLIN_LOCATION_CAR_WINDOWS_v1.1.1.zip` |
| ZIP Size | 61,975,775 bytes |
| ZIP SHA256 | `312c84a83235e5d69059f8776c3bc62bac6b8b62c9fb5c6da0588f3d9b2cdb87` |
| Executable | `ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` |
| EXE Size | 9,163,280 bytes |
| EXE SHA256 | `dd531e37138b0d13972eec0926dbc60d545bf4bc68d350df7109c02aac84cd38` |
| Signing Status | Unsigned (Developer / Ad-hoc Windows distribution) |
| Features | Full multi-domain SQLite bootstrap reconciliation, 15s cursor rewind safety margin, Africa/Casablanca timezone conversion, temporal boundary clock evolution, anti-downgrade revenue guards |

---

## 🏛️ Verification Gates Passed

- [x] Full Desktop Test Suite: 309 passed, 0 failed, exit code 0
- [x] Full Backend SQLite Suite: 229 passed, 0 failed, exit code 0
- [x] Full Backend PostgreSQL 16 Suite (`alembic upgrade head`): 229 passed, 0 failed, exit code 0
- [x] Full Mobile Test Suite (`./gradlew testDebugUnitTest --rerun-tasks`): 33/33 passed, exit code 0
- [x] Dedicated Regressions: 109/109 passed (sync cursor, maintenance active rental, revenue preservation, etc.)
- [x] GitHub Actions CI: 100% Green on release commit `13db86b` (Backend CI, Android Release, Windows Desktop Release)
- [x] Live Production Contract Tests: 100% Green on deployed PostgreSQL 16 backend container



