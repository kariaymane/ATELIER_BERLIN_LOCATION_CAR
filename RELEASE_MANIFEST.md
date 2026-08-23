# RELEASE MANIFEST — ATELIER BERLIN LOCATION CAR

## Release Identification

- **Release date**: 2026-08-24
- **Application name**: ATELIER BERLIN LOCATION CAR
- **Release status**: CLIENT DELIVERY READY — EXTERNAL SIGNING/DEPLOYMENT REQUIRED

## Windows Package

| Item | Value |
|---|---|
| Package name | `ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip` |
| Size | 61,339,586 bytes |
| Build date | 2026-08-23 19:49 (UTC+1) |
| Contents | `ATELIER_BERLIN_LOCATION_CAR.exe` + `_internal/` (bundled Qt DLLs incl. `qwindows.dll`, assets, translations) |
| Validation | Built via PyInstaller; launch-tested under Wine (application start, local database initialization, GUI event loop, zero errors). Physical-Windows validation not performed. |
| SHA-256 | `3c7851edd4c3ee08924fa6b96471db8114d015d445ad7a1d52aa10361cd75412` |

## Android Package

| Item | Value |
|---|---|
| Package name | `app-debug.apk` (`com.example`) |
| Type | DEBUG build (unsigned release) |
| Version / Code | 1.0 / 1 |
| Build date | 2026-08-23 |
| API endpoint | Production server URL embedded (`car-rental-system.fly.dev`) |
| Validation | Unit tests passed; login/bootstrap/vehicles/reservations/maintenance/notifications verified in code and tests; Room read cache included; no Flutter components |
| SHA-256 | `3dba4431211613b37c60f06b67c509db8668f78b2d3e11438f6a1a940736eea5` |
| Signing | EXTERNAL SIGNING REQUIRED — release keystore passwords exist only in the project's CI secrets; a release APK must be produced through the configured CI pipeline or by the client's signing authority |

## Backend Status

- FastAPI backend: healthy (`/health` → ok), all domains present:
  authentication, clients, vehicles, reservations (`rentals`), maintenance,
  notifications, dashboard, synchronization, realtime events.
- Realtime endpoints require authenticated sessions; missing, invalid,
  expired, malformed, forged and refresh tokens are rejected.
- Verified against a locally rebuilt container from this exact source.

## Database / Migration Status

- PostgreSQL is the single authoritative store.
- Alembic: exactly one head (`c8e41a7b2d95`); production database is at head.
- Full migration chain applied cleanly to a fresh database (verification run).
- Double-booking exclusion constraint active; production data preserved and untouched.

## Test Status

| Suite | Result |
|---|---|
| Backend pytest | 60 passed, 1 skipped |
| Desktop pytest | 31 passed, 1 skipped |
| Realtime authentication tests | 19/19 PASS |
| Offline pending upload tests | 17/17 PASS |
| Double-booking protection | PASS |
| Client synchronization | PASS |
| Android unit tests | 11/11 PASS |
| Android debug build | PASS |
| Android release compilation (no signing) | PASS |
| Docker rebuild verification | PASS |
| Delivery package secret audit | CLEAN |

## Known External Requirements

1. **Production deployment** — deploy current verified source through the
   normal pipeline (Fly.io). Not performed here (no authorization).
   Until deployed, the running server image predates the realtime
   authentication enforcement.
2. **Android release signing** — EXTERNAL SIGNING REQUIRED (CI secrets).
3. **Windows physical validation** — recommended one interactive launch on a
   real Windows machine (Wine validation already performed).

## Final Status

CLIENT DELIVERY READY — EXTERNAL SIGNING/DEPLOYMENT REQUIRED
