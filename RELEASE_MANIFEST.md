# RELEASE MANIFEST — ATELIER BERLIN LOCATION CAR

## Release Identification

- **Release date**: 2026-08-24
- **Application name**: ATELIER BERLIN LOCATION CAR
- **Release status**: CLIENT DELIVERY READY — EXTERNAL SIGNING/DEPLOYMENT REQUIRED

## Windows Package

| Item | Value |
|---|---|
| Package name | `ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip` |
| Size | 61,426,741 bytes |
| Build date | 2026-08-23 19:49 (UTC+1) |
| Contents | `ATELIER_BERLIN_LOCATION_CAR.exe` + `_internal/` (bundled Qt DLLs incl. `qwindows.dll`, assets, translations) |
| Validation | Built via PyInstaller; launch-tested under Wine (application start, local database initialization, GUI event loop, zero errors). Physical-Windows validation not performed. |
| SHA-256 | `a6165c8b08bffcb03885b7ec9bc4bc4ca19a9a1b59b2ed29e5092531c4e81905` |

## Android Package

| Item | Value |
|---|---|
| Package name | `app-debug.apk` (`com.example`) |
| Type | DEBUG build (unsigned release) |
| Version / Code | 1.0 / 1 |
| Build date | 2026-08-23 |
| API endpoint | Production server URL embedded (`car-rental-system.fly.dev`) |
| Validation | Unit tests passed; login/bootstrap/vehicles/reservations/maintenance/notifications verified in code and tests; Room read cache included; no Flutter components |
| SHA-256 | `dc9fb7ad76bbe4c956234935640e1827494ce8ac9228e9de790386ac2f5fbf9b` |
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
| Backend pytest | 73 passed, 1 skipped |
| Desktop pytest | 41 passed, 1 skipped |
| Realtime authentication tests | 19/19 PASS |
| Offline pending upload tests | 17/17 PASS |
| Double-booking protection | PASS |
| Client synchronization | PASS |
| Android unit tests | 11/11 PASS |
| Clients canonical report tests | 6/6 PASS + live container probe PASS |
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
