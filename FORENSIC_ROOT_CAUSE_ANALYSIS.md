# FORENSIC ROOT-CAUSE ANALYSIS — ATELIER BERLIN LOCATION CAR

**Date:** 2026-09-02
**Analyst:** Claude (Sonnet 5) forensic session
**Repo:** `/home/ayman/car-rental-system`
**HEAD at audit time:** `177d1fa` on branch `fix/dashboard-live-sync-forensic` (working tree clean, **NOT pushed**, no upstream configured)
**Production backend:** `https://car-rental-system.fly.dev` — **UP** at audit time (`/health/ready` → `database: connected`, pool initialized)

> This document is the **read-only forensic phase**. No source code was modified to produce it.
> Fixes are tracked separately (see §"Implementation Plan" at the end) and in `FINAL_DEEP_FORENSIC_REPORT.md`.

---

## 0. METHOD

Audited: git state; `.env`; `fly.toml`; CI workflows; backend auth (`api/v1/auth.py`, `services/auth_service.py`, `auth/jwt_handler.py`, `schemas/auth.py`); backend revenue (`services/dashboard_service.py`, `repositories/rental_repository.py`, `api/v1/dashboard.py`); the reservation model + migrations; desktop auth (`ui/login_window.py`, `services/api_client.py`, `main.py`, `ui/main_window.py`); desktop config (`config.py`); desktop dashboard (`ui/dashboard.py`, `sync/dashboard_cache.py`); mobile auth (`data/api/ApiClient.kt`, `data/api/TokenManager.kt`, `data/repository/AuthRepository.kt`, `build.gradle`); shared spec (`shared/`). Live probes run against production.

---

## 1. WHY DO THE SAME BUGS KEEP COMING BACK? (the meta root cause)

Five structural reasons, each independently sufficient to cause a "fixed" bug to reappear:

### 1.1 — The fix is applied in one of several parallel implementations

The same business rule is implemented **three times** (backend Python/SQL, desktop Python, mobile Kotlin) and the same *mechanism* (auth, refresh, date bounds) is often implemented **twice within one client**. When a bug is fixed, it is fixed in whichever copy the developer was looking at. The other copies keep the bug.

| Concern | Copy 1 | Copy 2 | Copy 3 |
|---|---|---|---|
| **Login / token acquisition (desktop)** | `ui/login_window.py::LoginWorker._authenticate_online` — **the live path**, raw `httpx`, 4 s timeout, **no retry** | `services/api_client.py::ApiClient.login` — robust, retries, cold-start aware — **effectively dead code** (MainWindow only calls `set_tokens()` with tokens LoginWorker already fetched) | — |
| **Revenue engine** | `repositories/rental_repository.py::get_revenue_between` (SQL) | `desktop/app/sync/dashboard_cache.py::compute_overview_rows` (Python re-impl) | `mobile .../data/fleet/FleetStatus.kt::dashboardOverview` (Kotlin re-impl) |
| **Effective vehicle status** | `backend/app/services/fleet_status.py` | `desktop/app/sync/fleet_status.py` | `mobile .../data/fleet/FleetStatus.kt` |
| **Period date bounds (today/week/month/year)** | `dashboard_service.py` | `dashboard_cache.py::_period_bounds` | `FleetStatus.kt` |
| **Token refresh** | desktop `ApiClient._do_refresh` | desktop `SyncEngine` (own refresh) | mobile `TokenAuthenticator` |

There **is** a normative spec (`shared/fleet_status_reference.py` + `shared/fleet_status_cases.json`) and cross-runtime parity tests for *fleet status*. There is **no** equivalent normative spec for **revenue**, **auth/token lifecycle**, or **date-period bounds** — those three drift freely.

### 1.2 — Tests run on SQLite; production is PostgreSQL

`.github/workflows/backend.yml` runs the backend test-suite with `DATABASE_URL=sqlite+aiosqlite:///:memory:`. Production is Postgres. Differences that a green CI cannot catch:

- `TIMESTAMP(timezone=True)` round-trips **aware** datetimes on Postgres, **naive** on SQLite → the recurring "can't subtract offset-naive and offset-aware datetime" 500s (last seen in `get_vehicle_performance`) are **invisible to CI**.
- Postgres `tstzrange` GIST exclusion constraints and the `EXCLUDE USING gist` overlap guards (migrations 001, 003) **do not exist** on SQLite — availability/overlap behaviour is only ever exercised in prod.
- `func.sum`/`func.coalesce` numeric typing, enum handling, and `NULLS` ordering differ.

So "all tests pass" has never meant "the Postgres code path is correct".

### 1.3 — No release-artifact ↔ commit binding

The repo root contains **10** copies of `ATELIER_BERLIN_LOCATION_CAR_WINDOWS*` plus loose `app-release.apk.sha256`, `atelier-...-e447da7.zip`, `dist/`, `build/`. Nothing records *which git SHA produced which binary*. `git status` is clean now, but the memory trail shows long periods with a 94-file dirty tree while EXE/APK were being handed to the client. **A bug "coming back" is often an older binary being run**, and there is no way to prove otherwise after the fact.

### 1.4 — Branch never merged; work stacked on unmerged work

`main` is behind. Real fixes live on `fix/dashboard-live-sync-forensic`, itself stacked conceptually on `fix/db-pool-health-readiness-mobile-cache` and `security/mobile-password-lifecycle`, **none pushed**. Every new session re-discovers the same issues because the fixes are not on `main`, not deployed as a set, and not visible to `git log main`.

### 1.5 — Client caches can become authoritative silently

Desktop offline auth (`_authenticate_offline`) and mobile cached-session restore both, by design, let a **stale** local credential/session in when the server is unreachable. That is correct for availability — but there is **no "this data is N minutes old / re-verifying" signal to the user**, so a stale cache is indistinguishable from live data, and a wrong number "comes back" every time the app starts offline.

---

## 2. LOGIN / CONNECTION — ROOT CAUSE

### Live evidence
```
POST https://car-rental-system.fly.dev/api/v1/auth/login
  {"email":"<PROD_ADMIN_EMAIL>","password":"<REDACTED>"}      → 200, tokens issued
  {"email":"BERLINECAR@GMAIL.COM", ...}  (uppercase)                → 200 (server lower-cases)
  {"email":"<PROD_ADMIN_EMAIL>","password":"wrong"}               → 422 (password min_length=8), NOT 401
```
Backend auth is **correct and canonical**: `AuthService.login` lower-cases + strips the email, verifies Argon2, rotates refresh tokens, locks after 5 failures, returns `{access_token, refresh_token, token_type, expires_in, user_id, role, full_name}`. Access TTL 15 min, refresh TTL 7 days.

### SYMPTOM
Operator opens the desktop app (or the phone) and login fails — "Erreur de connexion" / "Identifiants incorrects" — repeatedly, especially after the app has been closed for a while. Sometimes it "works on the 3rd try".

### ROOT CAUSE (desktop) — cold-start timeout in the wrong client
`fly.toml`: `min_machines_running = 0`, `auto_stop_machines = 'stop'`. The single backend machine **scales to zero** when idle. The next request pays a **cold start of 3–15 s**.

The **live** desktop login path is `LoginWorker._authenticate_online`:
```python
with httpx.Client(timeout=4.0) as client:        # 4 second hard timeout
    response = client.post(f"{API_BASE_URL}/api/v1/auth/login", json={...})
    ...
# on ANY exception (incl. ReadTimeout):
except Exception as e:
    self._server_rejected = False                 # NOT a rejection
return None                                        # → offline fallback
```
- On a cold machine the POST exceeds 4 s → `ReadTimeout` → `return None`.
- `run()` then calls `_authenticate_offline()`. On a **fresh install / new PC / wiped `%APPDATA%`** there is no `LocalUser` row → `rejected.emit(t("common.error_connection"))`.
- On a machine that logged in **once before**, offline auth succeeds against the **cached Argon2 hash** — but that cached hash is only as fresh as the last successful online login. If the password was changed server-side, or the cached `user_data` is stale, the user "logs in" and then **every** subsequent authenticated API call 401s, because `access_token` from `_authenticate_offline` is `""`.

Meanwhile `ApiClient.login()` — which retries with a 2.5× widened timeout precisely for "fly.dev machine cold-starting" — **is never called for login**. The cold-start fix exists; the login screen just doesn't use it.

### ROOT CAUSE (mobile) — historically the 15-minute access token; now mostly fixed, one contract gap left
`AuthRepository` / `TokenAuthenticator` are well built: refresh-on-401, "session dead **only** on explicit 401/403", cached-session restore, base-URL self-heal from `10.0.2.2`/`192.168.*`/`http://` back to prod. The old "re-login every 15 min" bug (access TTL expiry with no silent refresh) is addressed here.
Remaining gap: `AuthRepository.login` reads `body.user?.email` and `NetworkModels` declares a `user` object, but the backend `LoginResponse` has **no `user` object** (flat fields). It currently falls through to `email.trim()`, so it works — but it is **contract drift**: the mobile DTO models a response shape the backend does not send.

### ROOT CAUSE (error taxonomy) — every failure shows as "bad credentials"
Desktop `LoginWindow` has exactly one error string path (`t("login.error")` / `t("common.error_connection")`). It cannot distinguish:
INVALID CREDENTIALS · NETWORK UNREACHABLE · SERVER 5xx / cold-start timeout · RATE-LIMITED (login is `10/minute` per IP — a retry storm locks the operator out for a minute) · TOKEN/CONFIG failure.
Mobile is better (`401/404` vs `403` vs `429` vs `5xx` vs network) but still collapses `401` and `404` into "Identifiants incorrects".

### WHY PREVIOUS FIXES DID NOT HOLD
The retry/cold-start logic was added to `ApiClient` (§1.1 Copy 2) while the screen keeps using `LoginWorker` (Copy 1). Nobody deleted Copy 1, nobody rewired the screen. Each "login fix" session touched a different copy.

### PERMANENT FIX
1. **One auth client.** Delete `LoginWorker._authenticate_online`'s raw `httpx` block; route desktop login through a single `AuthClient.login()` (promote `ApiClient.login`) with: connect-timeout 5 s, **read**-timeout 30 s, 2 retries with backoff, explicit typed outcomes.
2. **Kill the cold start for auth**: set `fly.toml` `min_machines_running = 1` (the app is a paid single-tenant business tool; a warm machine costs a few $/mo and removes the entire failure class), **and** add a lightweight `/health` ping on app launch that starts the machine while the user is still typing.
3. **Typed login outcomes** → distinct messages on both clients: `INVALID_CREDENTIALS`, `ACCOUNT_LOCKED`, `NETWORK_UNREACHABLE`, `SERVER_ERROR`, `RATE_LIMITED`, `CONFIG_ERROR`.
4. **Offline login only with a visible badge** ("Mode hors-ligne — données locales") and never returns an empty `access_token` masquerading as a session; offline mode is explicitly read-only.
5. Align the mobile `LoginResponse` DTO to the real backend contract (remove the phantom `user` object) — see §3.

### REGRESSION TESTS
- backend: `test_auth.py` — login 200 shape is exactly the canonical contract; uppercase email → 200; unknown email → 401; wrong password (≥8 chars) → 401; 5 failures → lock → 423/401 `account_locked`; refresh rotation; expired refresh → 401.
- desktop: `test_login_outcomes.py` — mock transport returning connect-refused → `NETWORK_UNREACHABLE` (not "identifiants"); 503 → `SERVER_ERROR`; slow 6 s then 200 → success (retry proves cold-start tolerance); 429 → `RATE_LIMITED`; 401 → `INVALID_CREDENTIALS`; offline with cached hash → session flagged `offline=True`, `access_token==""` never used for API calls.
- mobile: `AuthRepositoryTest` — 401→"identifiants", timeout→"impossible de contacter", 429→"trop de tentatives", refresh-on-401 happy path, refresh 401 → session cleared, refresh network-error → session retained.

### PREVENTION
`AuthClient` is the **only** symbol allowed to call `/auth/*` — enforced by a test that greps the client codebases for `auth/login` / `auth/refresh` string literals and asserts a single occurrence per platform.

---

## 3. CANONICAL AUTHENTICATION CONTRACT (as it actually is — adopt verbatim)

```
POST /api/v1/auth/login
  Request : { "email": string, "password": string(8..128), "device_id"?: string }
  200     : { "access_token": string, "refresh_token": string,
              "token_type": "bearer", "expires_in": 900,
              "user_id": string(uuid), "role": string, "full_name": string }
  401     : { "detail": "<localised message>" }         # invalid creds / locked / disabled
  422     : { "detail": [ ...pydantic... ] }             # malformed body only
  429     : rate limit (10/min per IP)

POST /api/v1/auth/refresh
  Request : { "refresh_token": string, "device_id"?: string }
  200     : { "access_token", "refresh_token", "token_type", "expires_in" }   # rotation: old refresh is revoked
  401     : refresh invalid / revoked / expired

POST /api/v1/auth/logout   Authorization: Bearer <access>
  Request : { "refresh_token": string }   → { "message": string }
```
**Both clients consume exactly this.** The mobile `LoginResponseDto` must drop its `user: {...}` field. No `user` object is added to the backend (would be a 4th place to drift); `user_id` + `role` + `full_name` are sufficient and already canonical.

---

## 4. CHIFFRE D'AFFAIRES — BUSINESS DEFINITION + ENGINE

### Canonical definition (from `get_revenue_between` docstring + `test_revenue_consistency.py`, confirmed against prod)
> **Revenue of period [start, end) = Σ `reservation.total_price`** over every reservation where
> `status != 'CANCELLED'` **AND** `start_datetime >= start` **AND** `start_datetime < end` **AND** `start_datetime <= now`.
>
> Revenue is **recognised in full at rental start** ("recognition-at-start"). A 185-day rental that starts today books its entire `total_price` into *today / this week / this month / this year*. It is **not** pro-rated across days. A future booking (`start_datetime > now`) contributes **nothing** yet. `RESERVED`, `ACTIVE` and `COMPLETED` all count; only `CANCELLED` is excluded. There is no separate deposit/VAT/extras line — `total_price` is the whole contract value.

This is a **defensible** rule but it must be stated to the operator, because it is *why* `today_revenue` and `month_revenue` are legitimately `0` while `year_revenue` is large (every current prod reservation started in a prior month).

### Live prod proof of internal consistency (audit time)
```
/dashboard/stats : today_revenue 0.0 | week_revenue 46250.0 | month_revenue 0.0 | year_revenue 94750.0
/dashboard/daily   revenue 0.0
/dashboard/weekly  revenue 46250.0   (start 2026-08-31T00:00:00+01:00, end 2026-09-07T00:00:00+01:00)
/dashboard/monthly revenue 0.0
/dashboard/yearly  revenue 94750.0
```
`stats.*_revenue` == the matching `/dashboard/<period>` endpoint for every period. **The backend is self-consistent.** (Note: prod data is polluted with cross-session forensic probes — `ForensicBrand ProofModel`, `SYNC_7613`, a 185-day rental, `total 14` rentals / `8` this year. This pollution is itself a finding — see §17.)

### SYMPTOM
"Chiffre d'affaires ne marche pas." Operator selects a period and the number looks wrong / stuck at 0 / doesn't match another screen.

### ROOT CAUSES
1. **Desktop never queries the backend per selection.** `dashboard.py::_on_period_changed` just picks a **pre-computed key** (`today_revenue` / `week_revenue` / `month_revenue` / `year_revenue`) out of the single `/dashboard/stats` payload it fetched once. So:
   - There is **no way to get a period the payload didn't precompute** (yesterday, previous month, arbitrary range).
   - If `/dashboard/stats` failed (cold start, the very outage documented in memory), `_overview_data` is `{}` and every period shows `0.00 DH` — indistinguishable from "genuinely zero".
2. **No custom range exists anywhere.** `api/v1/dashboard.py` exposes only `daily|weekly|monthly|yearly`. There is **no** `GET /dashboard/revenue?from=&to=`. The requested "Personnalisé / Du–Au" is unimplemented server-side.
3. **Duplicate engine (§1.1).** When online, desktop shows the backend number; when offline it shows `dashboard_cache.compute_overview_rows`' Python number. These are kept equal only by discipline + `test_dashboard_cache_parity` — there is no shared spec, and they *have* diverged historically (naive-datetime handling).
4. **Contradiction bug — wrong dict key.** `dashboard.py::refresh_data` does `self._overview_data.get("active_maintenances", 0)` but the backend returns `active_maintenance_tickets` (and `maintenance`). The operational **"Maintenances actives"** card therefore **always shows 0**, while the fleet card right below it shows the real count (2 in prod). Two numbers for one fact, on one screen.

### PERMANENT FIX
- **One revenue endpoint, range-native:** `GET /api/v1/dashboard/revenue?from=YYYY-MM-DD&to=YYYY-MM-DD` (dates in **business timezone**, `to` **exclusive** end-of-day handled server-side). The fixed periods become thin wrappers that compute `from`/`to` and call the same service function. `/dashboard/stats` keeps returning today/week/month/year as a convenience **but the desktop revenue widget stops reading those keys and always calls `/dashboard/revenue` for the selected range.**
- **One engine:** extract `revenue_between(session, start, end, now)` as the single SQL implementation. `dashboard_cache` (offline) must be generated from / verified against a new `shared/revenue_cases.json` normative vector set — same pattern as fleet status. Mobile reads the same vectors.
- **Empty vs zero:** the widget distinguishes `HTTP error / no data` (show "—" + "données indisponibles") from `HTTP 200, revenue == 0` (show "0,00 DH").
- Fix the `active_maintenances` → `active_maintenance_tickets` key mismatch and add a test asserting the operational card == the fleet maintenance card == `/dashboard/stats.maintenance`.

### REGRESSION TEST
`test_revenue_consistency.py` (extend): seed rental A (`01/09→01/09`, 1000) and rental B (`02/09→02/09`, 2000) + one CANCELLED (5000) + one future (`01/10`, 9000). Assert `revenue(02/09..03/09)==2000`, `revenue(01/09..03/09)==3000`, `revenue(01/09..02/09)==1000`, `revenue(month)==3000`, cancelled & future never counted. Then assert **desktop `compute_overview_rows` == backend == mobile `dashboardOverview`** on the same fixture (one parametrised test importing all three, or driven by `shared/revenue_cases.json`).

---

## 5. REVENUE DATE FILTER — CURRENT STATE

| Requested | Exists today? |
|---|---|
| Aujourd'hui | ✅ (client picks `today_revenue`) |
| Hier | ❌ |
| Cette semaine | ✅ |
| Ce mois | ✅ |
| Mois précédent | ❌ |
| Cette année | ✅ (added recently) |
| Personnalisé (Du / Au) | ❌ — no UI, no endpoint |
| Dates sent to backend | ❌ — nothing is sent; client indexes a precomputed dict |
| "Du: … Au: … / Dernière mise à jour / Actualiser" panel | ❌ |

**Fix:** implement `GET /api/v1/dashboard/revenue?from=&to=`; rebuild the desktop widget as a compact panel: `[ Période ▾ ]` (7 presets incl. Personnalisé) → when Personnalisé, reveal two `QDateEdit` (`displayFormat = "dd/MM/yyyy"`) → on any change, send `from`/`to` as **ISO `YYYY-MM-DD`** to the endpoint → show `CA  <value> DH`, `Du: dd/MM/yyyy`, `Au: dd/MM/yyyy`, `Dernière mise à jour: HH:MM:SS`, `[ Actualiser ]`. No oversized button. Mobile mirrors with the same endpoint + a bottom-sheet range picker.

---

## 6. DATE FORMAT

**Findings:**
- Desktop display is **inconsistent**: reservation list & maintenance list render `%Y-%m-%d` (ISO, unambiguous but not the requested style); vehicle form writes `yyyy-MM-dd` (correct for API); dashboard "last refresh" is `%H:%M`.
- No `%m/%d/%Y` (US) or bare ambiguous `%d/%m/%y` found — so no *actively wrong* format, but no single **display** contract either.
- API payloads use ISO 8601 with offset (`2026-09-02T00:00:00+01:00`) — correct.

**Contract to adopt:**
| Layer | Format | Example |
|---|---|---|
| UI display (all dates shown to operator) | `DD/MM/YYYY` (+ `HH:MM` where a time is shown) | `02/09/2026` |
| UI → API | ISO 8601 date or datetime | `2026-09-02` / `2026-09-02T14:30:00+01:00` |
| DB | `TIMESTAMP(timezone=True)` (already) | — |
| Never | UI display string used as a business/query value | — |

One helper per client: `fmt_date(dt) -> "dd/MM/yyyy"`, `parse_user_date(s) -> date`. A lint test forbids `strftime("%Y-%m-%d"` / `strftime("%m/%d` in `desktop/app/ui/**`.

---

## 7. TIMEZONE / DATETIME

**BUSINESS_TIMEZONE = `Africa/Casablanca`** — already used consistently in `dashboard_service.py`, `rental_repository.py`, `dashboard_cache.py` (`TZ = ZoneInfo("Africa/Casablanca")`). Reservation columns are `TIMESTAMP(timezone=True)`. Backend comparisons are aware-vs-aware and correct.

**Residual risks:**
- **The rule lives in ~6 files as a copy-pasted literal `ZoneInfo('Africa/Casablanca')`** (not a shared constant). Someone will eventually write `datetime.now()` (naive) in a 7th place. → Put it in `shared/constants.py` as `BUSINESS_TZ` / `now_business()` and import everywhere; lint-forbid bare `datetime.now()` / `datetime.utcnow()` in `backend/app` and `desktop/app`.
- **SQLite CI (§1.2)** means the naive/aware boundary is only enforced in prod. `get_vehicle_performance` already 500'd once from exactly this (`datetime.now(tz) - datetime.fromisoformat(naive)`), was patched locally, and CI never saw it. → add a Postgres service to `backend.yml`.
- **`.replace(month=now.month+1)` month arithmetic** in `dashboard_service` / `dashboard_cache` is correct for the 12→1 wrap they special-case, but "mois précédent" must use the same careful arithmetic (Jan → Dec of prev year).
- **DST:** Morocco's offset shifts around Ramadan. `week_start = now - timedelta(days=weekday)` then `.replace(hour=0…)` on an aware datetime can land on a wall-clock time that doesn't exist / exists twice on a transition day. Low frequency, but boundary tests must include a DST-transition date.

**Boundary behaviour to pin:** `[start, end)` half-open everywhere (already the convention). `today` = `[local 00:00, tomorrow local 00:00)`. A rental starting exactly at `00:00` belongs to the new day. `now`-cutoff is `<= now` (a rental starting this exact second counts).

---

## 8–9. ONE SOURCE OF TRUTH

**Target (already the intended architecture; partially enforced):**
```
        PostgreSQL  ── authoritative state
            │
         FastAPI    ── authoritative business logic (revenue, availability, effective status)
            │  canonical DTOs + WS events
      ┌─────┴─────┐
   Desktop      Mobile
   SQLite        Room     ── mirrors / offline cache ONLY, never the business answer
```
**Where it holds:** effective vehicle status (normative spec + parity tests, Increments 1–6), versioned sync (`/sync/bootstrap` `revision`, Increment 5), desktop `DomainStore` snapshot rendering.
**Where it leaks:** revenue (3 engines, no spec), date-period bounds (3 impls), auth/refresh (multiple impls), and the *absence of a freshness signal* so a mirror silently substitutes for truth.

---

## 10. DESKTOP vs MOBILE CONTRADICTIONS — proven mechanisms

| # | Contradiction | Mechanism (proven) | Fix |
|---|---|---|---|
| C1 | Dashboard "Maintenances actives" = 0 but "Parc en maintenance" = 2 | `dashboard.py::refresh_data` reads key `active_maintenances`; backend sends `active_maintenance_tickets` | rename key + one-fact test |
| C2 | Desktop revenue ≠ mobile revenue for the same period | offline path uses re-implemented `compute_overview_rows` / `dashboardOverview`; only kept equal by hand | shared `revenue_cases.json` + parity test |
| C3 | Desktop shows old revenue after backend outage; "0.00 DH" everywhere | `/dashboard/stats` failed → `_overview_data == {}` → all-zero render, no error state | empty≠zero rendering + retry |
| C4 | Vehicle "AVAILABLE" on one screen, "RENTED"/"en location" on another | raw `vehicle.status` vs time-derived `effective_status` (`start<=now<end`). Backend already sends both (`status:AVAILABLE, effective_status:RENTED` seen live). Screens that still read raw `status` disagree with screens reading `effective_status` | every read-path uses `effective_status`; forbid raw `status` in UI/list code |
| C5 | Mobile shows a reservation desktop doesn't (or vice versa) after a while | historical: mobile incremental sync fetched only page 1 (cap 100) → sparse Room cache → frozen status. Fixed in Increment 5 (`applyAuthoritativeSnapshot`, `cache_snapshot_complete`) — **verify still holds** | keep; add a completeness assertion to E2E |
| C6 | A number updates on desktop but not on mobile until app reopen | WS event delivered but client cache-invalidation/refetch not wired for that entity; or WS not connected and poll interval long | audit every WS event type → cache-invalidation handler on both clients |

`EventBroadcaster` is an **in-process singleton** — correct for the single Fly machine, but if `min_machines_running` is raised >1 (or the app is scaled), cross-client events silently stop for clients pinned to the other machine. → if scaling, move to Redis pub/sub; if not, assert `min_machines_running <= 1` in a config test **or** set exactly 1 and document it.

---

## 11–12. LIVE-DATA STRATEGY + POLICY BY ENTITY

**Strategy (keep, formalise):** write → FastAPI → Postgres commit → `EventBroadcaster` domain event → WS frame → client invalidates that entity's cache → refetch authoritative → reactive UI. **Fallback:** smart poll (30 s) + manual `Actualiser`. One refresh path per client — not the "three independent refresh systems" the codebase has accreted.

| Entity | Source of truth | Cache | TTL (poll) | Realtime | Invalidation trigger | Manual refresh | Offline |
|---|---|---|---|---|---|---|---|
| Vehicle | PG | SQLite/Room | 30 s | `VEHICLE_*` WS | on WS + on mutation ack | yes | show cached + badge |
| Client | PG | SQLite/Room | 60 s | `CLIENT_*` WS | on WS + mutation ack | yes | cached + badge |
| Reservation | PG | SQLite/Room | 30 s | `RESERVATION_*` WS | on WS + mutation ack | yes | cached + badge |
| Maintenance | PG | SQLite/Room | 30 s | `MAINTENANCE_*` WS | on WS + mutation ack | yes | cached + badge |
| Notification | PG | SQLite/Room | 30 s | `NOTIFICATION_*` WS | on WS | yes | cached |
| **Dashboard / Revenue** | **PG (never client-computed when online)** | last good response + timestamp | **on focus + 60 s + every WS mutation** | via any domain WS | refetch `/dashboard/*` | yes, prominent | show last good **+ "au HH:MM" + stale badge if >10 min**; offline-computed value clearly marked provisional |
| Effective status (time-derived) | pure fn of reservation set + `now` | in-memory | single-shot boundary timer | `BoundaryClock` / `BoundaryTicker` | next boundary | n/a | works offline (local recompute) |

**Financial data must never be indefinitely stale:** hard rule — if the dashboard's last successful fetch is >10 min old **and** the app believes it is online, show the stale badge and auto-retry; never display an old revenue as if current.

---

## 13. DUPLICATED BUSINESS LOGIC — inventory

| Logic | Canonical home to keep | Duplicates to delete / generate-from-spec |
|---|---|---|
| Effective vehicle/fleet status | `shared/fleet_status_reference.py` (spec) + backend `fleet_status.py` | desktop & mobile re-impls **kept** but must stay spec-bound (parity tests exist ✅) |
| Revenue | **new** `revenue_service.revenue_between` + `shared/revenue_cases.json` | `dashboard_cache.compute_overview_rows`, mobile `dashboardOverview` → must be vector-verified |
| Date-period bounds | **new** `shared` `period_bounds(name, now)` | `dashboard_service` inline, `dashboard_cache._period_bounds`, `FleetStatus.kt` |
| Rental duration / `num_days` / `total_price` | backend `rental_service` (compute server-side on create) | any client-side recompute for display must equal the stored value; never re-derive for business use |
| Reservation overlap / availability | backend `check_availability` + PG `tstzrange` | desktop "availability probe" must call the endpoint (it does) and treat network error ≠ "conflict" (it does now) |
| Auth token lifecycle | **new** `AuthClient` per platform | `LoginWorker._authenticate_online`, `SyncEngine` refresh, dead `ApiClient.login` |
| Client totals / history KPIs | backend `/clients/{id}/rentals` | desktop must not sum locally |

---

## 14. MOBILE RESPONSIVENESS — audit status

**Not completed in this read-only phase** (requires the Android toolchain + emulator matrix, which this environment cannot run — see §"Environment limits"). What the code review flagged for the implementation phase:
- `build.gradle`: `minSdk 24`, `targetSdk 36` — wide range, no `WindowSizeClass` usage found.
- Need a screen-by-screen pass (Dashboard, Vehicles, Vehicle detail, Reservations + detail, Maintenance, Notifications, all forms/dialogs, date pickers, KPI cards, top bars, bottom nav) for: fixed `.dp` widths/heights, hardcoded offsets, `Row` without `weight`/`horizontalScroll`, dialogs exceeding viewport, keyboard (IME) overlap, font-scale ≥ 1.3, landscape, RTL (Arabic).
- Rule for the fix: **adaptive layout + `LazyColumn`/`LazyRow`/`FlowRow` + `fillMaxWidth` + `weight` + `WindowSizeClass` breakpoints + `Modifier.imePadding()` + `Modifier.safeDrawingPadding()`**; typography/spacing from a scale, **not** shrink-to-fit.

## 16. DESKTOP RESPONSIVENESS — audit status

- Login: `QFrame` with `setFixedWidth(440)` centred, `setMinimumSize(480,620)` — OK but the fixed 440 card + fixed logo `scaledToWidth(440)` won't adapt to a very small window; acceptable for desktop.
- Dashboard: uses a custom `FlowLayout` for the stat/fleet cards (good — wraps), `QScrollArea` present, cards `setMinimumWidth(200–250)`. Main risk: `QGridLayout`/`QHBoxLayout` sections elsewhere, long Arabic strings, long client/vehicle names, large revenue values overflowing fixed-width cards, and RTL mirroring. Needs a res* pass at 1024×720, 1280×800, 1920×1080, and narrow.

---

## 15. ANDROID UI STATE / REACTIVITY

Architecture is already `Repository → Flow/StateFlow → ViewModel → Compose`. `TokenManager` exposes `tokenFlow`; `FleetRepository` exposes `vehiclesFlow` / `cacheCompleteFlow`. `BoundaryTicker` is a cold `channelFlow` (no polling). No `Thread.sleep`/fixed timers found in the data layer. **Verify in the implementation phase** that every screen collects with `collectAsStateWithLifecycle` and that WS events feed the Room write that the Flow observes (so UI updates with no manual reopen).

---

## 17. DATABASE / TRANSACTION INTEGRITY

- Migrations `001_foundation`, `003_maintenance` create `tstzrange` GIST exclusion constraints — **Postgres-only**, untested by SQLite CI.
- `AuthService.login` on a wrong password does `session.add(user); await session.commit()` to bump `failed_login_attempts` — a **write inside the login read path**. If that commit fails (pool exhaustion — memory records a 256 MB OOM outage), the login 500s instead of returning 401. Wrap the counter bump so its failure cannot mask a valid/invalid credential verdict.
- **Failed-transaction poisoning:** confirm every `get_db` dependency does `rollback()` in a `finally` / on exception so a poisoned `AsyncSession` can't make the *next* request's reads silently fail. (Memory notes a "failed transaction poisoning" concern — needs an explicit test: force an `IntegrityError`, then assert the next request on a fresh session succeeds.)
- **Prod data hygiene:** production DB is polluted with forensic/probe rows from prior sessions (`ForensicBrand`, `SYNC_*` registrations, 2027/CANCELLED probe rentals, a 185-day rental). This corrupts every "does the number look right?" sanity check and the vehicle-performance ranking. → write a `scripts/purge_forensic_probes.sql` (guarded, dry-run first) and stop creating probe data in prod (use a disposable Postgres for E2E).
- Connection pool: `f1a0888` sized the pool; `/health/ready` shows `AsyncAdaptedQueuePool size=5, overflow=-4` — **verify `pool_pre_ping=True`** and that `size + max_overflow` fits the Fly machine's Postgres connection limit at 1 GB.

---

## 18. API CONTRACT CONSISTENCY

- **Login response**: mobile DTO models a phantom `user` object (§2, §3) — remove.
- **`expires_in`**: present (900). Clients should schedule a proactive refresh at ~`expires_in * 0.8` rather than waiting for a 401.
- **Vehicle DTO** (live): both `status` **and** `effective_status` are sent, plus `image_url` (empty string) / `image_urls` (`[]`) / `images` (`[]`) — **three image fields**, a drift magnet. Pick one (`image_urls: string[]`), deprecate the others.
- **Datetimes**: mixed `+01:00` offset (dashboard) and `Z` (`created_at: ...Z`) in the same API surface — both valid ISO, but clients must parse both. Standardise on offset-aware, document it.
- **Decimals**: `total_price`, `daily_rental_price` come back as JSON numbers (`250.0`) — fine, but pin 2-dp rounding server-side to avoid `46250.0` vs `46249.999999`.
- **Pagination**: `/vehicles/` returns `{vehicles, total, page, page_size}`; `/rentals/` returns `{..., total, page, page_size}` with a different item key — normalise the envelope.

---

## 19. END-TO-END CONSISTENCY TEST — to run in the implementation phase

Full 20-step create→verify(PG/API/desktop/mobile)→modify→cancel→revenue→date-filter→disconnect→reconnect→no-stale script, against a **disposable Postgres** (not prod), recording exact values at each step. Blocked items in this environment: the mobile leg (no emulator) and a true 2-desktop leg — those steps get a documented manual runbook.

---

## 20. RELEASE ARTIFACT INTEGRITY

Current state: **cannot bind any existing binary to a commit.** Fix going forward:
- Build only from a clean tree at a tagged commit; embed `git rev-parse HEAD` into the app (`--version` shows it; desktop "About"; mobile settings).
- Emit `RELEASE_MANIFEST.md` per build: git SHA, UTC build time, APK path+size+SHA256, EXE path+size+SHA256, ZIP SHA256.
- Delete the 10 stray `ATELIER_..._WINDOWS*` dirs from the repo root; artifacts go to `dist/<sha>/` and are git-ignored.
- CI (`android-release.yml`) already builds the signed APK/AAB from a tag — make that the **only** sanctioned APK source.

---

## ENVIRONMENT LIMITS (what this session cannot verify — carried from prior forensic memory, re-confirmed)

- **No Android emulator / device** here → mobile responsiveness, mobile E2E leg, on-device login, APK signing/runtime are **code-reviewed only**; verification needs the Android toolchain.
- **No Windows** → EXE runtime is build-script-only (`build_windows.sh` exit code), not executed.
- **No 2-desktop rig** → cross-desktop convergence is proven per-runtime + on shared fixtures, not on 2 live processes.
- **Prod Postgres** migrations can be observed via API but not directly inspected.
- Therefore a literal "TRUE 100% LIVE — PASS across all 4 processes" **cannot be signed off from this environment**; every mechanism is proven per-runtime and on shared vectors, and a manual runbook covers the rest.

---

## IMPLEMENTATION PLAN (priority order — tracked in FINAL_DEEP_FORENSIC_REPORT.md)

**P0**
1. `AuthClient` — one per platform; delete `LoginWorker` raw-httpx + dead `ApiClient.login`; 30 s read timeout + retry; typed outcomes + distinct messages. `fly.toml min_machines_running = 1` + launch-time warmup ping.
2. `shared/` normative specs: `revenue_cases.json` + `period_bounds()`; `BUSINESS_TZ` / `now_business()` constant; lint-forbid bare `datetime.now()` / `strftime("%Y-%m-%d")` in UI.
3. `GET /api/v1/dashboard/revenue?from=&to=` — range-native; fixed periods become wrappers.
4. Desktop revenue widget rebuild — compact, 7 presets + Personnalisé Du/Au (`dd/MM/yyyy` display, ISO to API), always queries backend, empty≠zero, `Dernière mise à jour HH:MM:SS`, `Actualiser`.
5. Fix C1 (`active_maintenance_tickets` key) + one-fact tests; sweep UI for raw `vehicle.status` reads → `effective_status`.
6. Postgres service in `backend.yml`; port the 3 known naive/aware + boundary regressions.

**P1**
7. Cache-policy table §12 enforced: one refresh path per client; dashboard stale badge (>10 min); WS-event → invalidation handler audit (C6).
8. Verify Increment-5 sparse-cache fix still holds; add completeness assertion.
9. Mobile responsiveness rebuild (screen-by-screen, `WindowSizeClass`, adaptive) + desktop resize pass + Arabic RTL.
10. API envelope + image-field + datetime-format normalisation (§18).

**P2**
11. Prod probe-data purge; release-manifest automation; delete stray artifact dirs; merge the stacked branches to `main` behind one green gate and deploy as a set.

**Release gate:** every box in §24 of the brief, with the environment-limited items explicitly marked "verified by code review + manual runbook" rather than silently checked.
