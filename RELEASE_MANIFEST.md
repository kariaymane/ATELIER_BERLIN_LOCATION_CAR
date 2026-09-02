# RELEASE MANIFEST

| Field | Value |
|---|---|
| Git branch | `main` |
| Git SHA | `7a59534` (fix(sync): unified refresh pipeline, eliminate dashboard corruption and harden mobile cold-start timeouts) |
| Build date (UTC) | 2026-09-02 ~21:40 |
| Tree state | clean (committed) |

## Android

| Field | Value |
|---|---|
| File | `ATELIER_BERLIN_LOCATION_CAR_7a59534.apk` |
| Type | debug-signed (`debugConfig`) |
| Size | 23,374,417 bytes |
| SHA256 | `a16cac75cd924cb5d8addd38413b6ee25514028c3d7ec62fba27b5d4d313ed39` |
| Contains | Cold-start resilient connection timeouts (20s connect, 30s read, 20s WS), `RevenueEngine.kt` (pro-rata), `BoundaryTicker.kt` |

## Windows

| Field | Value |
|---|---|
| ZIP | `ATELIER_BERLIN_LOCATION_CAR_WINDOWS_7a59534.zip` |
| ZIP size | 61,945,053 bytes |
| ZIP SHA256 | `08050b3ce5549aca469f6c973d0d850d9090715df62cf12be3f4e72affd71596` |
| EXE | `ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` |
| EXE size | 9,143,963 bytes |
| EXE SHA256 | `652e87d7054e5af18ebba8d51df28ebe1f2e7bf3a342bf57de74dd937122e5d9` |
| Contains | Single canonical refresh pipeline (auto-sync + manual sync convergence), debounce protection, eliminated dashboard zero-flicker, dedicated revenue request guard |

## Supersedes

Prior artifacts: `ATELIER_BERLIN_LOCATION_CAR_7aec46e.apk`, `ATELIER_BERLIN_LOCATION_CAR_WINDOWS_7aec46e.zip`, and older builds.

