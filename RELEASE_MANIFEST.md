# RELEASE MANIFEST

| Field | Value |
|---|---|
| Git branch | `main` |
| Git SHA | `7aec46e` (merge: one auth system · one pro-rata revenue engine · one date/time contract · Postgres CI) |
| Build date (UTC) | 2026-09-02 ~20:33 |
| Tree state | clean (committed) |

## Android

| Field | Value |
|---|---|
| File | `ATELIER_BERLIN_LOCATION_CAR_7aec46e.apk` |
| Type | debug-signed (`debugConfig`) — release-signed APK/AAB must come from `.github/workflows/android-release.yml` on a `v*` tag |
| Size | 23,548,352 bytes |
| SHA256 | `50eb12b1d391e8590ce14d42d54d0d852ae8dccd6e5d007ac144eff73d28434d` |
| Contains | `RevenueEngine.kt` (pro-rata), `LoginResponseDto` without phantom `user`, split login error taxonomy |

## Windows

| Field | Value |
|---|---|
| ZIP | `ATELIER_BERLIN_LOCATION_CAR_WINDOWS_7aec46e.zip` |
| ZIP size | 61,944,236 bytes (902 files) |
| ZIP SHA256 | `71ee4af2d27cca4800a1dd69a3100ca81a19b3ff197f5138717a84787713a96e` |
| EXE | `ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` |
| EXE size | 9,143,963 bytes |
| EXE SHA256 | `f01578fb89fb11fdf399595053fd281d2e2eaa843ffdeb30fdcdc11e0941f961` |
| Contains | `auth_client.py` (one auth client), rebuilt revenue widget, `shared/money_time.py` + `shared/revenue_reference.py` bundled |

## Backend

Not yet deployed — `git push origin main && fly deploy` required (both blocked for the automated session). Prod is still at fly release v24 (pre-pro-rata).

## Supersedes

Prior artifacts built from `7de8ece` (pre-forensic): `ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip` @ 03:47, `app-debug.apk` @ 03:41, `atelier-berlin-location-car-mobile-security-e447da7.zip`. Do not distribute those.
