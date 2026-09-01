# FINAL TRUTH + RESPONSIVITY FORENSIC REPORT

**Project:** `/home/ayman/car-rental-system`
**HEAD:** `df9b96dfa56692845560d18995c5c83503f01140` (branch `main`, 12 commits ahead of `origin/main`)
**Worktree:** DIRTY — 89 changed paths (pre-existing in-progress work by the operator + this session's mobile session-fix)
**Audit date:** 2026-08-29
**Auditor scope note:** This environment has **no Windows runtime, no Android emulator, no production PostgreSQL credentials, and the Fly.io server may be scaled to zero.** Phases that require those (live 3-client E2E, production DB reconciliation, signed release-APK rebuild, physical Windows EXE validation) are reported as **NOT VERIFIED** with the reason, never faked.

---

## 0. Executive summary

| Area | State |
|---|---|
| Backend dashboard canonicalization | **GOOD** — `/dashboard/stats` and `/vehicles/stats` both derive fleet counts from the single shared module `backend/app/services/fleet_status.py`. Parity tests pass. |
| Desktop dashboard canonicalization | **GOOD** — `desktop/app/utils/fleet_status.py` mirrors the backend precedence; Vehicles list and Dashboard cache use the same function. Parity tests pass. |
| Mobile dashboard | **GOOD by construction** — mobile renders `/dashboard/stats` verbatim and vehicle state from the backend's `effective_status`. It performs **no independent fleet math**. |
| Mobile login / session persistence | **WAS BROKEN — FIXED THIS SESSION.** Root cause identified and repaired (see §7). |
| Desktop time-boundary live state | **PARTIAL GAP** (see §12) — Dashboard self-heals within ≤30 s; list views do **not** react to a pure time-boundary crossing with no accompanying data change. |
| Release artifacts | **STALE / NOT VERIFIED** — the committed `RELEASE_MANIFEST.md` SHA-256s no longer match the on-disk ZIP; APK in `build/outputs` predates current source; signed release APK cannot be produced here (keystore is CI-only). |

---

## 1. Dashboard metric forensic

Backend path: `GET /api/v1/dashboard/stats` → `DashboardService.get_overview()` (`backend/app/services/dashboard_service.py`).

| Metric | Canonical source | Derivation | Notes |
|---|---|---|---|
| Total vehicles | `fleet_status.compute_fleet_counts` | count of vehicles excluding `SOLD`/`INACTIVE` | ✔ shared module |
| Available / Reserved / Rented | `fleet_status.compute_fleet_counts` | disjoint buckets, precedence `MAINTENANCE > RENTED > RESERVED > AVAILABLE`, interval `[start,end)`, evaluated at `now` (UTC) | ✔ shared module; identical rule in `desktop/app/utils/fleet_status.py` |
| Maintenance (vehicles) | same | active maintenance ticket (`status NOT IN COMPLETED/CANCELLED`) whose `[start, COALESCE(actual_end, expected_end, +inf))` covers `now` | ✔ |
| Active / Reserved / Completed / Cancelled reservations | `rental_repository` status counts | grouped by `Reservation.status` | counts by **persisted** reservation status (correct — reservation status is authoritative, unlike vehicle status) |
| Revenue today / week / month | `rental_repository.get_revenue_between(start, end)` | sum over rentals in period | period bounds: desktop uses local-TZ midnight / ISO week Monday / 1st-of-month (`dashboard_cache._period_bounds`); **backend bound TZ must be confirmed equal — see Risk R2** |
| Top vehicles | `dashboard_service` per-vehicle utilization | days rented / days since first rental | not cross-checked against mobile (mobile has no "top vehicles" widget) |
| Client count | `client_repository` | row count | trivial |

**No duplicate fleet-count implementation was found** in backend or desktop after the recent consolidation. `grep -RInE "available|reserved|rented|maintenance"` across `backend/`, `desktop/`, `mobile/` shows the only arithmetic lives in the two `fleet_status` modules plus the mobile DTO passthrough.

---

## 2. Dashboard parity

Automated parity guards present and **passing**:

* `backend/tests/test_fleet_status_parity.py`
* `backend/tests/test_fleet_parity_desktop.py` *(cross-checks the two precedence tables)*
* `desktop/tests/test_dashboard_cache_parity.py`
* `desktop/tests/test_fleet_parity_desktop.py`
* `desktop/tests/test_forensic_matrix.py`

**Live numeric parity matrix (PostgreSQL ↔ FastAPI ↔ SQLite ↔ Dashboard ↔ Mobile Room):** **NOT VERIFIED** — requires a running backend + seeded controlled dataset + emulator, none available in this environment. The *code paths* are proven equivalent by the tests above; the *running values* were not observed.

---

## 3. Contradiction scan

| Concept | Implementations found | Verdict |
|---|---|---|
| `effective_status` (vehicle) | `backend/app/services/fleet_status.py`, `desktop/app/utils/fleet_status.py` | Two implementations by necessity (SQL vs. SQLAlchemy-ORM-over-SQLite); precedence tables are identical and cross-tested. **Equivalent.** |
| Vehicle availability | derived from the same modules | **Consistent.** |
| Reservation count | `rental_repository` (backend) / local query (desktop) | by persisted status — consistent. |
| Maintenance count | `fleet_status` modules | consistent. |
| Revenue | `rental_repository.get_revenue_between` (backend) / `dashboard_cache` in-period sum (desktop) | **Risk R2** — period-boundary timezone equality not re-proven this pass. |
| Mobile fleet math | none | mobile shows backend truth verbatim. |

---

## 4. Vehicle state canonicalization

Canonical precedence (verified present in both `fleet_status` modules):

```
SOLD / INACTIVE  (structural, from vehicle.status — never overridden)
  > MAINTENANCE  (active ticket covers now)
  > RENTED       (ACTIVE reservation covers now)
  > RESERVED     (RESERVED reservation covers now)
  > AVAILABLE
```

The persisted `vehicle.status` column is treated as **structural + a MAINTENANCE hint only**; the buckets are recomputed from live reservation/maintenance rows on every read. Migrations `f1a2b3c4d5e6_unstick_maintenance_vehicle_status` and `g2b3c4d5e6f7_maintenance_wins_cancellation_reason` exist to repair historically stuck rows. Mobile consumes the backend's `effective_status` field (`FleetRepository.kt:64` — `VehicleStatus.fromApi(dto.effectiveStatus ?: dto.status)`), so it cannot contradict the backend for a synced vehicle.

---

## 5. Reservation / maintenance contradiction

Backend tests present and passing:

* `backend/tests/test_maintenance_wins_reservation.py`
* `backend/tests/test_maintenance_frees_vehicle.py`
* `desktop/tests/test_maintenance_wins_reservation_desktop.py`

Rule confirmed in code: an active maintenance overlapping a reservation ⇒ reservation `CANCELLED` with `cancellation_reason = MAINTENANCE`; vehicle bucket = `MAINTENANCE`; on maintenance close the bucket recomputes and the (still-cancelled) reservation no longer blocks availability. **Live cross-layer replay NOT VERIFIED** (no running stack).

---

## 6. Live propagation

**Desktop:** local mutation → commit → `get_event_bus().data_refreshed.emit()` + `_run_sync()` (see `main_window.py` lines 737/857/894/1043). Global bus fan-out in `_on_global_data_refreshed` refreshes dashboard + all list views. Realtime server events → 250 ms-debounced `_run_sync` (`_on_realtime_event`). Background pull every `SYNC_INTERVAL_SECONDS = 30`.

**Mobile:** Room is the single UI source; repository writes to Room and Compose collects `Flow`s (`vehiclesFlow`, `reservationsFlow`, `maintenanceFlow`, `performanceMetricsFlow`) via `stateIn`. `RealtimeSyncManager` pushes server changes into Room.

**Gap:** see §12.

---

## 7. Mobile login / session — ROOT CAUSE & FIX (this session)

### Symptom
App repeatedly demands email + password on cold start even though the user never logged out; a brief flash of the login screen on every launch; offline launch impossible.

### Root causes (three, all in the startup path)

1. **`AuthRepository.validateAndRestoreSession()` destroyed the session on *any* non-200.**
   The old code path: if the `/auth/refresh` call returned `null` (network unreachable, DNS failure, timeout) **or** any non-success code (including `500`/`503` from a Fly.io cold-start, `429` rate-limit) it called `clearLocalSession()`, which called `tokenManager.clearAll()` — wiping the 7-day refresh token, the access token, the stored identity **and the operator-configured API base URL**. One transient blip at launch = permanent re-login. This is almost certainly the field symptom, because the backend is a scale-to-zero Fly deployment whose first request after idle frequently times out or 5xx's.

2. **`FleetViewModel` routed straight to the login screen before restore finished.**
   The `userSession` collector's initial emission is `null`; the old collector immediately set `navigationStack = [Auth]`. The `Splash` screen was effectively never shown; the login form rendered for every cold start and only flipped to Dashboard if/when restore later succeeded.

3. **`clearLocalSession()` used `clearAll()`** — nuking the configured base URL on every session drop, silently reverting the server the operator had set.

### Fix applied (files changed this session)

| File | Change |
|---|---|
| `mobile/.../data/api/JwtUtils.kt` *(new)* | Dependency-free JWT `exp` inspection: `isDefinitelyExpired` (readable exp in the past), `isProbablyValid`, `expiresAtEpochSeconds`. Unreadable/opaque tokens ⇒ "unknown", never "expired" — server stays authority. |
| `mobile/.../data/api/TokenManager.kt` | New `clearSession()` — removes tokens + identity keys **but keeps `api_base_url`**. `clearAll()` retained for factory-reset semantics. |
| `mobile/.../data/repository/AuthRepository.kt` | `validateAndRestoreSession()` rewritten: session is cleared **only** on an explicit server rejection (`401`/`403` from refresh or probe) or logout. On network failure / timeout / `5xx`: if a stored session exists and its token is not already provably expired, the app **enters with the cached session** and re-validates on the next reachable call. `clearLocalSession()` now calls `clearSession()`. `login()` no longer persists an empty-string refresh token. |
| `mobile/.../ui/viewmodel/FleetViewModel.kt` | Added `_bootstrapped` flag; navigation `combine(userSession, _bootstrapped)` holds on `Splash` until the first restore attempt completes, then routes Dashboard (session) or Auth (no session). Dashboard re-entry guarded so `refreshAll()` doesn't re-fire on every session re-emit. |
| `mobile/.../MainActivity.kt` | Renders a real `SplashScaffold()` while `currentScreen is Screen.Splash` instead of falling through to `AuthScreen`. |

### Resulting behavior (matches Requirement 5)

```
first login (email+password) → tokens + identity persisted (SharedPreferences "car_rental_auth_prefs", MODE_PRIVATE)
cold start, server reachable   → /auth/refresh rotates tokens → Dashboard, no login screen
cold start, server unreachable → cached non-expired session → Dashboard (background re-validates)
server returns 401/403         → session cleared → login required
logout                         → clearSession() → next start requires login
refresh token provably expired → not eligible for offline entry → login required
```

### Security posture (explicit, per operator decision this session)
Chosen option: **"enter app offline with cached session."** Trade-off accepted: a lost/stolen *unlocked* phone holding a stored-but-server-revoked token can view **cached Room data** until the next online call rejects it. Mitigations in place: tokens in `MODE_PRIVATE` SharedPreferences; refresh token rotates on every use; access-token `exp` is 15 min, refresh `exp` is 7 days; any authenticated call that returns 401 triggers `TokenAuthenticator` → refresh → on rejection `clearTokens()`. **Not** using `EncryptedSharedPreferences` — noted as Risk R4.

### Tests added — `mobile/.../test/java/com/example/SessionPersistenceTest.kt` (5 tests, passing)
* future token → `isProbablyValid` / not expired
* past token → `isDefinitelyExpired`
* opaque/`null` token → treated as unknown, not expired
* `clearSession()` keeps base URL, drops credentials
* `clearAll()` resets base URL

**NOT covered by automated test in this environment:** the full `validateAndRestoreSession` flow (offline-enters / 401-clears / success-rotates) needs MockWebServer or an instrumentation test — MockWebServer is not in the dependency set and cannot be added offline. Logic was verified by reading; behavior should be confirmed on a device before release.

---

## 8. Room / Flow audit (mobile)

`FleetViewModel` exposes `StateFlow`s built from `fleetRepository.*Flow` via `stateIn(WhileSubscribed(5000))`; screens use `collectAsState()`. Room DAOs return `Flow` for list queries. **No one-shot `DAO` query feeding a screen that displays mutable data was found** in the main screens. `AuthScreen` local `remember { mutableStateOf("") }` is correct (transient form input). **Full per-screen Room-observation sweep NOT exhaustively completed** — spot-checked Dashboard, Vehicles, Reservations, Maintenance; detail screens not individually traced.

---

## 9. EventBus audit (desktop)

Single global bus (`desktop/app/services/event_bus.py`), signal `data_refreshed`. Fan-out consumer `_on_global_data_refreshed` (`main_window.py:1061`) refreshes dashboard + lists. Regression tests: `desktop/tests/test_global_dispatch_isolation.py`, `test_reactivity_regression.py`, `test_full_reactivity_lifecycle.py`, `test_mutation_failure_no_false_event.py` (mutation failure must NOT emit a success event) — **all passing**.

---

## 10. Cache audit

Desktop `dashboard_cache.compute_local_overview` recomputes from the local SQLite session on each call using `now` — it is a *computation*, not a stored cache, so it cannot go stale on its own. `_refresh_dashboard(fetch_server=True)` additionally pulls server stats each sync. No TTL-based stale-value cache was found in the dashboard path.

---

## 11. Sync audit

Local → outbox → server → Postgres → pull → local merge → `data_refreshed` (only when rows actually changed — see §12 gap). Conflict path surfaces reservation rejections visibly (`_on_sync_finished`: `reservations.rejected_by_server` status message; never silent). Offline flag handled (`_is_online`). Tests: `desktop/tests/test_desktop_sync_offline.py`, `test_false_conflict_regression.py`, `test_pending_uploads.py` — passing.

---

## 12. Time-based live state — PARTIAL GAP (Phase 12 / 13)

**Finding.** There is **no exact time-boundary scheduler.** Time-driven state changes surface via the 30 s background sync:

* **Dashboard** — `_on_sync_finished` calls `_refresh_dashboard(fetch_server=True)` on **every** online sync cycle, so a vehicle that becomes `AVAILABLE` at 18:00 (reservation end, no DB write) is corrected on the dashboard within **≤ 30 s**. Acceptable, not a storm (1 recompute / 30 s).
* **List views (Vehicles / Reservations / Maintenance)** — refresh **only** on `data_refreshed`, which `_on_sync_finished` emits **only when the sync actually pushed/pulled rows**. A pure time-boundary crossing produces no rows, no event ⇒ **the Vehicles list keeps showing `RENTED` until the next real data change or a manual refresh, while the Dashboard already shows `AVAILABLE`.** This is a genuine Dashboard-vs-list contradiction across a time boundary.

**Recommended fix (not applied — design decision for the operator):** a single centralized boundary scheduler that, per open reservation/maintenance, arms one `QTimer.singleShot` for the next `start`/`end` instant; on fire → recompute effective sets → one `data_refreshed.emit()`. Fallback: have `_on_sync_finished` emit `data_refreshed` unconditionally when online (cheap; still 30 s granularity). Mobile has the analogous gap — `RealtimeSyncManager` is event-driven; no local boundary timer.

**Heartbeat decision:** a brute-force heartbeat is **not** warranted. Event-driven refresh + 30 s pull + realtime already bound staleness to 30 s. The only missing piece is the boundary scheduler above; adding a 1-per-30 s unconditional emit closes the visible contradiction with negligible cost (measured: `compute_local_overview` is a single-pass over local rows).

---

## 13. Error semantics (Phase 14)

**Backend:** distinct HTTP codes preserved (401/403/404/409/422/500). Login maps 401/404→"Identifiants incorrects", 403→"Accès refusé", 429→"Trop de tentatives", else→"Erreur de connexion (code)".
**Mobile:** `AuthRepository.login` distinguishes 401/404 vs 403 vs 429 vs other, and network exceptions ("Unable to resolve host" / "Failed to connect" / timeout) → "Impossible de contacter le serveur" — **kept separate** from HTTP errors. **Not** collapsed to a single "Serveur injoignable".
**Gap:** `FleetViewModel.refreshAll()` collapses any repository failure to `"Erreur de synchronisation avec le serveur API."` — the underlying category (offline vs 409 vs 500) is lost at the ViewModel boundary. Minor; noted as Risk R3.

---

## 14. Button forensic (Phase 15)

Desktop mutation buttons traced (`main_window.py`): reservation create/activate/complete/cancel, maintenance create/advance/complete, vehicle form save — each path commits then emits `data_refreshed` + `_run_sync`. `test_mutation_failure_no_false_event.py` guards the failure case. **Full mobile button sweep NOT completed** (detail-screen action buttons not individually traced). Spot check: mobile has no write buttons on most screens (read-mirror app); maintenance advance/complete exist in `ApiService` and route through the repository → Room.

---

## 15. Responsive UI (Phases 10–11)

**NOT VERIFIED.** Requires rendering on multiple form factors / an emulator / screenshot tests across phone-portrait, phone-landscape, small/large width, Arabic RTL, French LTR. `AuthScreen` was read: uses `verticalScroll`, `fillMaxWidth`, `imePadding`, `statusBarsPadding`, `navigationBarsPadding`, `wrapContentHeight` on the logo — no hardcoded offsets that would clip. The broader Compose screen set and the client-document (CIN recto/verso, permis recto/verso) image layout were **not** audited this pass.

---

## 16. Test matrix (actually executed this session)

| Suite | Command | Result |
|---|---|---|
| Backend | `backend/venv/bin/pytest -q` | **101 passed**, 5 warnings, 15.4 s |
| Desktop | `PYTHONPATH=. venv/bin/pytest -q` | **147 passed**, 478 s |
| Mobile unit | `./gradlew --offline testDebugUnitTest --rerun-tasks` | **17 passed** (12 pre-existing + 5 new `SessionPersistenceTest`), 0 failures |
| Mobile debug APK | `./gradlew --offline assembleDebug` | **BUILD SUCCESSFUL** |
| Mobile release APK | `./gradlew --offline assembleRelease` | **FAILED — keystore `my-upload-key.jks` absent (CI-only), documented** |
| Mobile instrumentation (`androidTest`) | — | **NOT RUN — no emulator/device** |
| Live cross-layer E2E (Phase 18) | — | **NOT RUN — no running backend/Postgres/emulator** |
| Login E2E on device (Phase 19) | — | **NOT RUN — no device** |
| Responsiveness (Phase 20) | — | **NOT RUN** |

---

## 17. E2E cross-layer proof (Phase 18)

**NOT VERIFIED.** The deterministic lifecycle (AVAILABLE → RESERVED → RENTED → maintenance-wins/CANCELLED → maintenance-finished → AVAILABLE → new RESERVED) is covered *per layer* by unit/integration tests (`test_maintenance_wins_reservation*.py`, `test_full_reactivity_lifecycle.py`, `test_cross_window_convergence.py` — all passing) but was **not** replayed against a single live running stack observed from all of Postgres + API + desktop + dashboard + mobile simultaneously.

---

## 18. EXE provenance (Phase 21)

| Item | Value |
|---|---|
| On-disk | `ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip` (61,862,733 bytes, mtime 2026-08-29 19:17), extracted `ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` present |
| SHA-256 (zip, now) | `99fec1835413597c2dcdb6119d4c58395b5dba4a4220d05b0ac27c9f4636e549` |
| `RELEASE_MANIFEST.md` claims | `e49efd62ddb6bdbe6914c2a3d84cdbb94abb009f91484b3ef891329d5f16e8b3` (build 2026-08-23) |
| Verdict | **MISMATCH / STALE** — the committed manifest does not describe the current ZIP. No desktop/backend source was changed *this session* (only `mobile/`), but the pre-existing dirty worktree (89 files) means the ZIP cannot be attributed to a clean revision. Rebuild + re-manifest required before release. Physical-Windows validation: never performed (Wine-only, per manifest). |

---

## 19. APK provenance (Phase 21)

| Item | Value |
|---|---|
| `mobile/app/build/outputs/apk/release/app-release.apk` | SHA-256 `e4f553af76e99f5ec7afca0b26090d8316152220d4ffec21e8cf04cfd4620766` — **built before this session's source changes; now stale.** |
| `app-release.apk.sha256` (repo root) | matches the stale artifact above |
| Debug APK rebuilt this session | `mobile/app/build/outputs/apk/debug/app-debug.apk`, SHA-256 `b2e74d94334ccaf6bcfab451bcf2359b2243210d40068dd55c3d62f03096a106`, 23,509,950 bytes, 2026-08-29 21:42 — includes the session fix, compiles & unit-tests clean |
| Signed release APK | **BLOCKED** — release keystore is CI-secret-only; cannot be produced in this environment |

---

## 20. Remaining risks

* **R1 — Offline-session security trade-off** (accepted): a stored session unlocks cached data offline; server revocation only takes effect on the next online call. Consider a max-offline-age cap (e.g. refuse offline entry if the access token `exp` is > N days old even when the refresh token is still valid).
* **R2 — Revenue period-boundary timezone**: backend vs desktop period bounds (`today`/`week`/`month`) not re-proven equal this pass. If the backend uses UTC midnight and the desktop uses local midnight, "revenue today" can differ near midnight.
* **R3 — ViewModel error flattening**: `FleetViewModel.refreshAll()` collapses all repository failures to one French string, losing the offline/409/500 distinction that the layers below preserve.
* **R4 — Token storage**: plain `MODE_PRIVATE` SharedPreferences, not `EncryptedSharedPreferences`/Keystore. Acceptable on non-rooted devices; upgrade recommended.
* **R5 — Desktop list views vs. time boundary** (§12): lists don't self-heal on a pure time transition; Dashboard does. Visible contradiction until next data change/manual refresh.
* **R6 — Release artifacts** out of sync with source and with their own manifest.
* **R7 — Mobile test coverage is thin** (17 tests); no ViewModel/repository/Compose/responsiveness/instrumentation coverage for most of the app.

---

## 21. NOT VERIFIED (explicit)

1. Live numeric parity Postgres ↔ API ↔ SQLite ↔ Dashboard ↔ Mobile on a controlled dataset (Phase 2).
2. Live cross-layer E2E lifecycle replay (Phase 18).
3. On-device login E2E: clean install → login → kill → relaunch authenticated → logout → relaunch requires login → expired-token → offline-with-valid-session (Phase 19). *Logic fixed & reasoned; not device-confirmed.*
4. Mobile responsive UI across form factors + RTL/LTR (Phases 10–11, 20).
5. Client-document image layout (CIN/permis recto-verso) on device (Phase 11).
6. `validateAndRestoreSession` flow behavior via automated test (MockWebServer unavailable offline).
7. Production PostgreSQL reconciliation (no credentials; read-only rule respected — nothing touched).
8. Signed release APK / rebuilt Windows EXE with fresh SHA-256 provenance (Phase 21).
9. Full per-screen Room-observation and per-button mobile sweep (Phases 7, 8, 15).
10. Backend/desktop revenue period-boundary TZ equality (R2).

---

## 22. Final verdict

```
============================================================
🚨 FINAL TRUTH + RESPONSIVITY FORENSIC VERDICT
============================================================

PROJECT:   /home/ayman/car-rental-system
HEAD:      df9b96dfa56692845560d18995c5c83503f01140  (main, +12 ahead of origin)
WORKTREE:  DIRTY — 89 changed paths (pre-existing WIP + this session's mobile session fix)

============================================================
DASHBOARD
============================================================

TOTAL:        NOT VERIFIED (no live stack) — code path canonical (fleet_status shared module)
AVAILABLE:    NOT VERIFIED — code path canonical
RESERVED:     NOT VERIFIED — code path canonical
RENTED:       NOT VERIFIED — code path canonical
MAINTENANCE:  NOT VERIFIED — code path canonical
REVENUE:      NOT VERIFIED — see Risk R2 (period-boundary TZ)

DASHBOARD = BACKEND:   PASS  (single shared module; parity tests pass)
DASHBOARD = DESKTOP:   PASS  (mirror module; parity tests pass)
DASHBOARD = MOBILE:    PASS  (mobile renders backend stats verbatim; no independent math)
                       — subject to sync latency; live values NOT VERIFIED

============================================================
BUSINESS TRUTH
============================================================

VEHICLE STATE:      PASS  (derived, precedence MAINTENANCE>RENTED>RESERVED>AVAILABLE; persisted status not authoritative)
RESERVATION STATE: PASS  (persisted status authoritative; counts consistent)
MAINTENANCE STATE: PASS  (active-ticket interval rule shared)
AVAILABILITY:      PASS  (same modules)
DOUBLE BOOKING:    PASS  (backend + desktop guards + tests: test_maintenance_wins_reservation, false-conflict regression)
DATE/TIME:         PARTIAL  (half-open [start,end) UTC consistent; revenue period-boundary TZ NOT re-proven — R2)

============================================================
DESKTOP
============================================================

BUTTONS:        PASS  (mutation→commit→event→sync traced; failure-no-false-event tested)
EVENTBUS:       PASS  (single global bus; isolation + lifecycle tests pass)
CACHE:          PASS  (dashboard overview is recomputation, not stored cache)
TRANSACTIONS:   PASS  (local commit before emit)
ASYNC:          PASS  (sync on QThread; 250ms realtime debounce)
CROSS-WINDOW:   PASS  (test_cross_window_convergence passes)
TIME-BOUNDARY:  FAIL  (§12 — list views do not self-heal on a pure time transition; dashboard does)

============================================================
MOBILE
============================================================

API:                  PASS  (Retrofit; effective_status consumed)
DTO:                   PASS  (spot-checked; effectiveStatus / back-image fields present)
ROOM:                  PASS  (Flow-backed list queries; no one-shot feeding live screens found)
FLOW/STATE:            PASS  (StateFlow + collectAsState)
VIEWMODEL:             PASS  (session gating fixed this session)
COMPOSE:               PASS (spot check) / responsiveness NOT VERIFIED
RESPONSIVENESS:        NOT VERIFIED (no emulator; Phases 10–11/20 not run)
IMAGES:                NOT VERIFIED (CIN/permis recto-verso layout not device-checked)
LOGIN:                 PASS  (root cause fixed; unit tests added; device E2E NOT VERIFIED)
SESSION PERSISTENCE:   PASS  (offline/transient-failure no longer wipes tokens; enters with cached session)
LOGOUT:                PASS  (clearSession → next start requires login; base URL retained)
TOKEN EXPIRATION:      PASS  (explicit 401/403 or provably-expired refresh ⇒ login; TokenAuthenticator rotates on 401)

============================================================
LIVE
============================================================

LOCAL MUTATION:   PASS  (immediate event + sync)
REMOTE MUTATION:  PASS  (realtime → 250ms sync → event)
SYNC:             PASS  (outbox/pull/merge; conflicts surfaced visibly)
REALTIME:         PASS  (desktop RealtimeEventsClient; mobile RealtimeSyncManager)
TIME TRANSITION:  FAIL  (§12 — no boundary scheduler; list-view staleness until next data change)
HEARTBEAT DECISION: NOT NEEDED as brute force — staleness already bounded to 30s; add a boundary scheduler
                   OR an unconditional online-sync data_refreshed emit (cheap) to close the §12 contradiction

============================================================
TESTS
============================================================

BACKEND:         PASS  (101/101)
DESKTOP:         PASS  (147/147)
MOBILE:          PASS  (17/17 unit; +5 new session-persistence tests)
REACTIVITY:      PASS  (desktop reactivity/lifecycle/dispatch-isolation suites)
DASHBOARD:       PASS  (backend + desktop parity suites)
E2E:             NOT RUN (no live stack)
LOGIN:           PARTIAL  (unit PASS; device E2E NOT RUN)
RESPONSIVENESS:  NOT RUN (no emulator)
FULL:            PASS for everything runnable here; NOT RUN items listed in §21

============================================================
RELEASE
============================================================

EXE:     STALE / NOT REBUILT
PATH:    ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip → .../ATELIER_BERLIN_LOCATION_CAR.exe
SHA256:  zip 99fec1835413597c2dcdb6119d4c58395b5dba4a4220d05b0ac27c9f4636e549
         (RELEASE_MANIFEST.md claims e49efd62… — MISMATCH; manifest is stale)

ZIP:     STALE
PATH:    /home/ayman/car-rental-system/ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip
SHA256:  99fec1835413597c2dcdb6119d4c58395b5dba4a4220d05b0ac27c9f4636e549

APK:     RELEASE = BLOCKED (keystore CI-only) ; DEBUG rebuilt this session
PATH:    debug: mobile/app/build/outputs/apk/debug/app-debug.apk
SHA256:  debug  b2e74d94334ccaf6bcfab451bcf2359b2243210d40068dd55c3d62f03096a106
         stale release  e4f553af76e99f5ec7afca0b26090d8316152220d4ffec21e8cf04cfd4620766

============================================================
FINAL
============================================================

ALL INFORMATION REAL:            PASS (code paths) / NOT VERIFIED (live values)
DASHBOARD CONSISTENT:            PASS (backend=desktop=mobile by shared/verbatim derivation; live NOT VERIFIED)
DESKTOP LIVE:                    PARTIAL (event + 30s pull PASS; time-boundary FAIL — §12)
MOBILE LIVE:                     PARTIAL (Room/Flow PASS; responsiveness + device live NOT VERIFIED)
MOBILE RESPONSIVE:               NOT VERIFIED
LOGIN ONCE UNTIL LOGOUT:         PASS (fixed) — device E2E NOT VERIFIED
NO STALE STATE:                  FAIL (desktop list views across a time boundary — §12)
NO CONTRADICTIONS:               PARTIAL (dashboard/business-truth PASS; dashboard-vs-list time-boundary contradiction remains)
NO DOUBLE BOOKING:               PASS
NO FALSE SERVER ERROR:           PASS (backend + mobile classify distinctly; R3 minor at ViewModel boundary)
TIME-BOUNDARY LIVE:              FAIL (§12)

TRUE LIVE SHOWROOM:              FAIL — one architectural gap (§12) + verification gaps

FINAL:                           NOT READY
                                 (mobile login fix is production-grade pending device E2E;
                                  blockers below prevent a full PASS)

BLOCKERS:
  B1  Desktop time-boundary staleness: list views do not react to a pure
      time transition (§12). Fix: boundary scheduler OR unconditional
      data_refreshed emit on each online sync.
  B2  Release artifacts stale and un-attributable to a clean revision;
      RELEASE_MANIFEST.md SHA-256s do not match on-disk ZIP. Rebuild EXE +
      signed release APK from a clean tree and regenerate the manifest.
  B3  Device verification outstanding for the login fix (login → kill →
      relaunch authenticated → logout → relaunch requires login →
      expired-token → offline-with-valid-session).

REMAINING RISKS:  R1 offline-session trade-off · R2 revenue TZ · R3 VM error
                  flattening · R4 unencrypted token storage · R5 desktop list
                  time-boundary · R6 stale artifacts · R7 thin mobile tests

NOT VERIFIED:     Live parity matrix · live E2E · device login E2E · mobile
                  responsiveness · CIN/permis image layout on device ·
                  validateAndRestoreSession automated flow test · production
                  PostgreSQL reconciliation · rebuilt signed artifacts ·
                  full per-screen Room + per-button mobile sweep · revenue
                  period-boundary TZ equality

============================================================
```

---

## What was actually changed this session

Only `mobile/` source (login/session fix). No backend, desktop, database, migration, git-history, or release-artifact changes. No destructive git operations. Production PostgreSQL not touched.

```
mobile/app/src/main/java/com/example/data/api/JwtUtils.kt                 (new)
mobile/app/src/main/java/com/example/data/api/TokenManager.kt             (+clearSession)
mobile/app/src/main/java/com/example/data/repository/AuthRepository.kt    (validateAndRestoreSession rewrite)
mobile/app/src/main/java/com/example/ui/viewmodel/FleetViewModel.kt       (splash gating)
mobile/app/src/main/java/com/example/MainActivity.kt                      (SplashScaffold)
mobile/app/src/test/java/com/example/SessionPersistenceTest.kt            (new, 5 tests)
```

Backend 101/101 · Desktop 147/147 · Mobile 17/17 — all green.
