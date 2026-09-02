# FINAL RELEASE VERIFICATION REPORT

**Date:** 2026-09-02
**Branch:** `fix/dashboard-live-sync-forensic`
**Commit:** `7de8ece2f96797ec18c64f81496202c01a5f2f2c`
**Production:** `https://car-rental-system.fly.dev/` — **release v24** (deployed this run)

---

## RELEASE GATE

| # | Gate | Result |
|---|---|---|
| 1 | Backend tests = 0 failures | **PASS** — 145 passed |
| 2 | Desktop tests = 0 failures | **PASS** — 229 passed, 0 failed, 0 errors (6:32) |
| 3 | Mobile tests = 0 failures | **PASS** — 65 passed |
| 4 | Android build = SUCCESS | **PASS** — `:app:assembleDebug` BUILD SUCCESSFUL |
| 5 | Windows build = SUCCESS | **PASS** — `build_windows.sh` WIN_EXIT=0, "Build SUCCESS" |
| 6 | Windows ZIP freshly generated | **PASS** — from `7de8ece`, dist/build wiped first, old ZIP archived |
| 7 | Production backend deployed | **PASS** — `fly deploy` → release **v24**, release_command (`alembic upgrade head`) OK, smoke checks passed |
| 8 | Production `/health` = healthy | **PASS** — `{"status":"alive"}` 200; `/health/ready` `{"database":"connected"}` 200 |
| 9 | Production dashboard endpoints verified | **PASS** — see §3 |
| 10 | Revenue correct | **PASS** — canonical rule; `year_revenue = 48 500,00` live, periods correctly 0 |
| 11 | Top 5 correct | **PASS** — `/vehicle-performance` 200, 3 vehicles; naive/aware crash fixed |
| 12 | Vehicle rental count has NO denominator | **PASS** — desktop card is count-only; test asserts no `/` or ` sur ` label |
| 13 | Mobile clean cache works | **PASS** — Room v8→v9 + `fallbackToDestructiveMigration`; never issues a backend mutation |
| 14 | Desktop → Mobile live sync verified | **PASS** — live create / cancel / vehicle-status each delivered a WS event (§4) |
| 15 | PostgreSQL remains authoritative | **PASS** — no production data deleted; clients re-derive from the same canonical rule |
| 16 | No fake/static business data | **PASS** — forensic search clean (§9) |
| 17 | Git working tree clean | **PASS** |

---

## 1. THE TWO BLOCKERS — FIXED

### 1a. Desktop test failure — `test_forensic_state_changes_because_time_passed`

**Root cause:** the test seeded a reservation ending in **4 real seconds** and asserted the "before" state, then waited on the **real wall clock + a real QTimer**. Under any suite load, if >4 s elapsed between seeding and the assertion, the vehicle had already freed itself and `BoundaryClock.next_boundary` was `None` → line 275 failed.

**Fix (project's existing time abstraction, no skip/xfail/weakened assertion/sleep):**
the `DomainStore` and the `BoundaryClock` now run on an **injected clock** (`now_fn`) and an **injected scheduler** (`schedule_fn`) — a controlled clock the test advances explicitly, and a manual scheduler whose callback the test fires. The full stack (MainWindow → DomainStore → BoundaryClock → vehicle list → dashboard → subscriptions) is still exercised end to end; the transition is still driven **only by time passing**. Production behaviour unchanged.

Verification: **5/5** repeated runs pass; whole file **8 passed in ~2 s** (was ~15 s), **3/3** stable; **full suite 229 passed, 0 failed**.

### 1b. Backend not redeployed

Deployed with the project's existing `fly deploy` workflow (`docker/Dockerfile.backend`, `release_command = "alembic upgrade head"`). No new migrations (prod already at `h3c4d5e6f7g8`), so the release command was a no-op. Release **v24**, `DEPLOY_EXIT=0`. No secrets exposed, no production DB contents modified.

---

## 2. PRE-DEPLOY VERIFICATION

```
git status --porcelain            -> clean
git rev-parse HEAD                -> 7de8ece2f96797ec18c64f81496202c01a5f2f2c
git diff f1a0888(v23) HEAD -- backend/  -> only dashboard_service.py + one new test file
alembic heads                    -> h3c4d5e6f7g8 (== production head; no new migrations)
backend pytest                   -> 145 passed
```

---

## 3. PRODUCTION API — VERIFIED ON THE RUNNING SERVICE (release v24)

```
GET /health          -> 200  {"status":"alive","database":"not_checked"}
GET /health/ready     -> 200  {"status":"ready","database":"connected","pool":{"size":5,...}}

GET /api/v1/dashboard/stats -> 200
   total_vehicles 3 | available 2 | reserved 0 | rented 1 | maintenance 0
   today_revenue 0.0 | week_revenue 0.0 | month_revenue 0.0
   year_rentals 7 | year_revenue 48500.0            <-- NEW, canonical, LIVE

GET /api/v1/dashboard/vehicle-performance -> 200  (3 vehicles)
   ll kkkk            count 4  revenue 41850.0  utilization 3100.0
   ForensicBrand …    count 2  revenue  3500.0  utilization  280.0
   cici oo            count 1  revenue  3150.0  utilization  140.0
   (previously 500'd on a naive `last_rental` subtraction — fix is LIVE)

GET /api/v1/dashboard/{daily,weekly,monthly}  -> revenue 0.0   (canonical: nothing started this period)
GET /api/v1/dashboard/yearly                  -> revenue 48500.0, rentals 7
GET /api/v1/events/recent (auth)              -> 200
```

---

## 4. LIVE DESKTOP → MOBILE SYNC — VERIFIED ON PRODUCTION

WS `wss://…/api/v1/events/ws` (Bearer) opened as a stand-in for a connected Mobile:

```
POST /api/v1/rentals/  (Desktop-style, future 2027 dates)  -> HTTP 201
   -> WS frame: RESERVATION_CREATED  (+ NOTIFICATION_CREATED)   "…depuis Desktop."
POST /api/v1/rentals/{id}/cancel                            -> HTTP 200
   -> WS frame: RESERVATION_STATUS_CHANGED  (+ NOTIFICATION_CREATED)
PATCH /api/v1/vehicles/{id}/status  MAINTENANCE             -> HTTP 200
   -> WS frame: VEHICLE_STATUS_CHANGED  (+ NOTIFICATION_CREATED)
PATCH /api/v1/vehicles/{id}/status  AVAILABLE  (revert)     -> HTTP 200
   -> WS frame: VEHICLE_STATUS_CHANGED
```

Every mutation → PostgreSQL COMMIT → `EventBroadcaster.broadcast_event` → WS frame that a
connected Mobile's `RealtimeSyncManager` receives → `FleetRepository.handleRealtimeEvent`
re-fetches the **authoritative** record (never trusts the frame) → revision-guarded Room
upsert → Compose recomposition. **No app restart, reinstall, manual cache clear, or manual
refresh.** Reconnect: exponential backoff + post-reconnect catch-up + 20 s fallback poll.

Probe rentals (`50d32a08…`, `e8e83d67…`) are dated 2027 and `CANCELLED` → inert (excluded
from revenue / Top-5 / fleet counts). The test vehicle was reverted to `AVAILABLE`.
No production data deleted.

---

## 5. DASHBOARD CONSISTENCY

One canonical `/dashboard/stats` + one shared derivation spec
(`shared/fleet_status_reference.py` ↔ `desktop/app/utils/fleet_status.py` +
`desktop/app/sync/dashboard_cache.py` ↔ `mobile/.../FleetStatus.kt`).
`year_revenue` uses the identical `get_revenue_between` / `compute_overview_rows` /
`FleetStatus.dashboardOverview` window in all three. Cross-runtime parity suites green.

"Véhicules en location" — **count only** on both clients: desktop `ExecutiveFleetCard`
no longer built with `has_progress`, so no `N/5`, no `N sur 5`, no progress bar; mobile
already `FleetCountCard(count = metrics.rentedVehicles)`.

---

## 6. MOBILE CLEAN CACHE

`AppDatabase` version `8 → 9` (schema unchanged). `fallbackToDestructiveMigration` is
already configured → first launch of this build drops the local Room mirror (stale
vehicles / reservations / maintenance / notifications / sync-metadata), `META_CACHE_COMPLETE`
disappears, `refreshAll()` routes to `bootstrapAndReset()` → one clean INITIAL
`GET /sync/bootstrap` (read-only) → `applyAuthoritativeSnapshot` (Room writes only).

Audit: no mobile code path from a cache reset issues a backend mutation. The only `@DELETE`
in `ApiService` is the user-initiated "delete maintenance ticket" action. `clearAll()` DAOs
are `DELETE FROM <local table>` — Room only. **PostgreSQL is never touched.**

---

## 7. FULL REGRESSION

| Suite | Command | Result |
|---|---|---|
| Backend | `pytest` | **145 passed** |
| Desktop | `pytest` (full) | **229 passed, 0 failed, 0 errors** |
| Mobile | `./gradlew :app:testDebugUnitTest` | **65 passed** |
| Mobile build | `./gradlew :app:assembleDebug` | **BUILD SUCCESSFUL** |
| Windows | `packaging/windows/build_windows.sh` (`--clean`) | **Build SUCCESS**, WIN_EXIT=0 |

---

## 8. FINAL WINDOWS ZIP

`packaging/windows/{dist,build}` removed, prior ZIP archived to
`car-rental-system-backups/`, rebuilt with `build_windows.sh` (PyInstaller 6.22.2 / wine-11.0).

| check | result |
|---|---|
| exactly one EXE | ✅ 1 (`ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe`) |
| EXE type | ✅ `PE32+ executable for MS Windows 6.00 (GUI), x86-64` |
| EXE in ZIP == standalone EXE | ✅ same SHA-256 |
| Arabic resources (`i18n/ar.json`) | ✅ present — incl. `"period_year": "هذا العام"` |
| French resources (`i18n/fr.json`) | ✅ present — incl. `"period_year": "Cette année"` |
| branding (`logo_transparent_officiel`) | ✅ present |
| shared fleet-status data | ✅ `shared/fleet_status_reference.py` + `fleet_status_cases.json` |
| tzdata Africa/Casablanca | ✅ present |
| total files | 895 |

---

## 9. FINAL FORENSIC SEARCH

- hardcoded revenue / vehicle count / Top-5 literals — **none**
- Mock/Fake/Demo/Stub/Test repository·service·dashboard in production source — **none**
- duplicate revenue / fleet-status / rental-status formulas — **none**: 3 runtime mirrors
  of ONE canonical spec, cross-checked by parity suites (not independent formulas)
- stale-cache / non-canonical local dashboard source — **none**: desktop dashboard renders
  only from `DomainStore.snapshot` or `/dashboard/stats`; no raw SQL

---

## FINAL OUTPUT

```
COMMIT:                7de8ece2f96797ec18c64f81496202c01a5f2f2c   (branch fix/dashboard-live-sync-forensic)
PRODUCTION DEPLOYMENT: fly deploy -> release v24  (DEPLOY_EXIT=0, release_command OK, smoke checks passed)
PRODUCTION HEALTH:     /health 200 "alive"   /health/ready 200 "database:connected"

BACKEND TESTS:         145 passed, 0 failed
DESKTOP TESTS:         229 passed, 0 failed, 0 errors
MOBILE TESTS:          65 passed, 0 failed
ANDROID BUILD:         :app:assembleDebug  BUILD SUCCESSFUL
WINDOWS BUILD:         build_windows.sh  WIN_EXIT=0  "Build SUCCESS"

REVENUE:               canonical (recognition-at-start). LIVE: year_revenue 48 500,00 DH / year_rentals 7;
                       today/week/month 0,00 DH (nothing started this period). Desktop "Cette année"
                       period + Mobile "Cette année" card. Desktop==Mobile==backend.
TOP 5:                 LIVE 200, 3 vehicles (41850 / 3500 / 3150). Fixed the naive/aware datetime
                       TypeError that 500'd the endpoint; added canonical offline Top-5.
VEHICLES IN RENTAL:    count only — no "N/5", no "N sur 5", no progress bar (test-enforced).
MOBILE CACHE:          Room v8->v9 + fallbackToDestructiveMigration -> clean initial sync from
                       FastAPI/PostgreSQL. Cache only; PostgreSQL never touched.
LIVE SYNC:             VERIFIED on production — create / cancel / vehicle-status each delivered a
                       WebSocket event; no restart / reinstall / manual refresh.
POSTGRES AUTHORITY:    intact. No production data deleted. Clients converge to the backend.

FINAL APK PATH:        /home/ayman/car-rental-system/mobile/app/build/outputs/apk/debug/app-debug.apk
FINAL APK SHA256:      e7a18564e4384541e3394ea2b86ce5c83c0693eb76900c80f654b5ab58b8becf
                       (23 358 033 bytes; apksigner verify: VERIFIED; debug build — production
                        release signing keystore is a CI-only secret)

FINAL WINDOWS EXE PATH:  /home/ayman/car-rental-system/packaging/windows/dist/ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe
FINAL WINDOWS EXE SHA256: 32bc26d07ffa1b1084821caab40e39bd2c50a2bc40668661ea28a241107bacd5   (9 129 921 bytes)

FINAL WINDOWS ZIP PATH:  /home/ayman/car-rental-system/ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip
FINAL WINDOWS ZIP SHA256: b9b64003f8a748b791d61ec9efbc072a3b7035bd963d96b3e9e9af76eaa2389a   (61 905 299 bytes, 895 files)

GIT STATUS:            clean · branch fix/dashboard-live-sync-forensic @ 7de8ece · NOT pushed
```
