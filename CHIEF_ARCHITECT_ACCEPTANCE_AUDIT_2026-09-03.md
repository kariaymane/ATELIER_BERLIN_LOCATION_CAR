# 🏛️ CHIEF ARCHITECT — FULL PROJECT ACCEPTANCE AUDIT
## ATELIER BERLIN LOCATION CAR

**Date:** 2026-09-03
**Auditor role:** Chief Software Architect / Business-Logic Auditor / QA Lead / Release Manager
**Repo:** `/home/ayman/car-rental-system` — `main` @ `eacfa55` (1 commit ahead of `origin/main`, **unpushed**)
**Deployed backend:** Fly `car-rental-system` release **v27** ≈ commit `725fed5` (Sep 3 ~02:47 UTC)
**Shipped clients:** `ATELIER_BERLIN_LOCATION_CAR_725fed5.apk` (debug-signed) + `..._WINDOWS_725fed5.zip`

---

## EXECUTIVE VERDICT

**The project is ~90% complete and, in its *shipped* configuration, internally coherent.** The
core business engine — vehicle effective-status derivation and revenue (chiffre d'affaires)
recognition — is now expressed as a single normative Python spec per concern
(`shared/fleet_status_reference.py`, `shared/revenue_reference.py`), ported to all three
runtimes, and locked by cross-runtime golden-vector parity tests that are green. Double-booking
is prevented at the database level by a real PostgreSQL `EXCLUDE` constraint that is present in
the migration chain and deployed. Authentication and RBAC are solid.

**It is NOT "done" in the sense of "sign it and forget it".** There is one **P1 regression sitting
in `main` HEAD** (the unpushed `eacfa55`) that reverses time-liveness guarantees three prior
"100 % live" increments were built to provide. There is one **P1 business-logic hazard**
(scheduling maintenance silently cancels an in-progress rental and erases its already-earned
revenue). Release management is in a genuinely confusing state (HEAD unpushed, prod stale,
manifest hash does not match the artifact on disk, no git tag). And a documented timezone-contract
inconsistency between two modules in the same repo has been flagged in three previous forensics
and is still unresolved.

**Release decision: 🟡 RELEASE READY WITH CONDITIONS** (conditions in §RELEASE DECISION).

---

## 1. WHAT WAS VERIFIED, AND HOW

| Area | Method | Result |
|---|---|---|
| Backend test suite | `venv/bin/pytest` (in-memory SQLite path) | **217 passed, 0 failed** |
| Backend PostgreSQL path | `.github/workflows/backend.yml` `test-postgres` job (postgres:16 service, `TEST_DATABASE_URL`) | Configured & runs on every push/PR to `main` |
| Mobile unit tests | `./gradlew --offline testDebugUnitTest --rerun-tasks` (this machine) | **68 passed, 0 failed, 0 errors** |
| Desktop test suite | `PYTHONPATH=. ../venv/bin/pytest` | **300 passed, 0 failed** in 14 m 55 s. The suite is **slow** — the `test_refresh_reversion_forensic` / real-`QTimer` forensic proofs dominate; no `pytest-timeout` is installed, so a genuinely hung test would not self-abort (worth adding). |
| Live production API | anonymous probes of `/health`, `/health/ready`, `/openapi.json` | Alive; DB **connected** (pool size 5, 1 GB VM); `/dashboard/revenue` + `/dashboard/period/{name}` **present** |
| Fly deployment state | `fly status`, `fly releases`, `fly image show`, `fly secrets list` | v27 running in `cdg`; secrets deployed; **no `CORS_ORIGINS`** (native clients only) |

**Could NOT be verified from this environment** (physically impossible here — see
`car-rental-system-env-limits`): on-device Android runtime, Windows EXE runtime on real Windows,
two-desktop + one-phone cross-client live E2E, a signed *production* release APK (keystore is a
CI-only GitHub secret), and **authenticated** live production data probing (the admin password
read + login was blocked by the sandbox classifier — a correct block; the operator can run it
with `!curl …`).

---

## 2. BUSINESS LOGIC STATUS

### ✅ Correct and well-built

- **Vehicle effective status** — `shared/fleet_status_reference.py` is a single pure function.
  Precedence `SOLD/INACTIVE > MAINTENANCE > RENTED > RESERVED > AVAILABLE`, mutually exclusive,
  provably sums to `total_vehicles`. `RENTED` is **time-derived** (`start <= now < end` for a
  RESERVED-or-ACTIVE reservation), matching this business's "no separate pickup step" reality.
  Backend (`services/fleet_status.py`), desktop (`utils/fleet_status.py`) and mobile
  (`FleetStatus.kt`) are parity-tested against 14 golden vectors — **green in all three runtimes**.
- **Revenue / chiffre d'affaires** — `shared/revenue_reference.py`, PRO-RATA BY DAY: a rental's
  `total_price` is split evenly across `num_days`; a day counts once it has begun; period bounds
  are Africa/Casablanca local midnights, week starts Monday; `CANCELLED` never contributes;
  `total_price/num_days` keeps the all-time sum exactly equal to `total_price` (Decimal, no drift).
  Backend `revenue_service.py`, desktop `dashboard_cache.py`, mobile `RevenueEngine.kt` all
  delegate to the same rule and are parity-tested — **green**.
- **The 2026-09-03 "split-brain revenue" root cause is now closed on the shipped pair.** The
  deployed backend (v25–v27) exposes `/api/v1/dashboard/revenue` and `/api/v1/dashboard/period/{name}`
  and computes pro-rata via the same `shared/revenue_reference.py` that the shipped `725fed5`
  clients use. (Previously the pro-rata clients shipped against a recognition-at-start backend
  that lacked those routes.)
- **Double-booking** — `check_availability()` is the application-level pre-check (half-open
  `start < end` overlap, excludes `CANCELLED`/`COMPLETED`); the real guarantee is the PostgreSQL
  `excl_reservations_no_overlap` `EXCLUDE USING gist (vehicle_id WITH =, tstzrange(start,end,'[)') WITH &&) WHERE status NOT IN ('CANCELLED','COMPLETED')`.
  It **is** in `migrations/versions/001_foundation.py` and re-asserted in `5dfe7eb02006` — i.e.
  it exists in the deployed schema, not only in a SQLAlchemy `after_create` hook.
- **Reservation lifecycle** — `RESERVED → ACTIVE (Activer) → COMPLETED | CANCELLED`;
  `complete_rental` also allows `RESERVED → COMPLETED`; `update_rental` re-checks availability on
  date change; `cancel`/`complete` free the vehicle's raw status. CHECK constraint on valid
  statuses.
- **Maintenance** — future-dated tickets no longer flip the raw `vehicle.status` column (only a
  window-open-*now* ticket sets the transient `MAINTENANCE` hold); effective status is derived
  from the schedule. "Maintenance wins": creating a ticket atomically cancels overlapping
  `RESERVED`/`ACTIVE` reservations with `cancellation_reason='MAINTENANCE'` in the same
  transaction. (See P1-2 for the side effect.)
- **Client rental report** — eligible = `RESERVED|ACTIVE|COMPLETED`; `active_rentals` is
  time-derived (`start <= now < end`), consistent with the fleet "en location" rule; `CANCELLED`
  reported but excluded from totals.

### ⚠️ Wrong / needs a decision

- **P1-2 — Scheduling maintenance over a live rental erases realised revenue.**
  `RentalRepository.cancel_overlapping_reservations()` cancels *any* `RESERVED` **or `ACTIVE`**
  reservation overlapping the maintenance window, including one whose window contains `now` (the
  car is physically out on rent). There is no guard against it and no partial-revenue
  preservation: `shared/revenue_reference.is_revenue_eligible()` returns `False` for **every**
  `CANCELLED` reservation with no carve-out for days realised before cancellation, so the
  dashboard CA for that rental drops to **0** the instant maintenance is booked. A single
  operator mis-click can silently cancel a customer's in-progress rental and remove money the
  business already earned. *Fix required:* refuse (or require explicit confirmation for)
  maintenance overlapping a covering-now reservation; and/or recognise realised days on a rental
  that was `CANCELLED` after it started.

- **P1/P2-3 — Early completion recognises full revenue on future calendar dates.**
  `_realised_day_dates()` sets `realised = num_days` for any `COMPLETED` rental regardless of
  `now`. Completing a 10-day rental on day 3 immediately books all 10 day-slices — including the
  7 future calendar dates — into revenue. If an early return reduces the charge, this
  over-recognises; if the fee is non-refundable it is defensible, but placing "realised" revenue
  on dates that have not happened is still wrong for a realised-revenue metric. *Needs the
  business owner's rule* (does early return change the price?), then either clamp `end`/realised
  days to the completion instant, or keep full recognition but place it no later than
  `date(completion)`.

- **P3 — Client "total_amount" (full `SUM(total_price)`) vs dashboard CA (pro-rata realised)**
  answer different questions but a user will compare them and see a mismatch with no explanation.
  Add a note / tooltip.

---

## 3. ARCHITECTURE STATUS

**Intended model** (correct, and mostly enforced):

```
PostgreSQL (authoritative)
   → FastAPI (one revenue engine, one fleet-status engine, one time contract)
   → Desktop SQLite / Mobile Room  = MIRROR/CACHE, never a competing authority
   → DomainStore (desktop) / Flows (mobile)  = one observable snapshot
   → UI renders the snapshot
```

**Where it holds:** the three "one spec" modules (`fleet_status_reference`, `revenue_reference`,
`money_time`) plus golden-vector parity tests are a genuine, working single-source-of-truth for
the hard business math. The desktop `DomainStore` + `BoundaryClock` and the mobile
`BoundaryTicker` are a real single-observable design.

**Where it is inconsistent:**

- **P1-1 — the newest commit (`eacfa55`, unpushed) reverses the authority direction and, as a
  side effect, kills time-liveness.** See §SYNC STATUS. In short: once any server dashboard
  response arrives, `DomainStore._server_overview` is stored and **permanently** overrides the
  local overview (until logout); the midnight period-rollover term in `recompute_effective()` is
  explicitly gated behind `self._server_overview is None`; and mobile
  `performanceMetricsFlow` was flipped from `local ?: api` to `api ?: local`. The Vehicles list
  still recomputes at a boundary, but the Dashboard's fleet cards and revenue cards freeze to the
  last fetch — reintroducing the exact "two screens disagree" class that
  `car-rental-status-contradiction-forensic` fixed, and voiding the Increment 3/4/6 "cards roll
  at local midnight with no network" guarantee.

- **P2-4 — two opposite naive-datetime policies in the same repo.**
  `shared/money_time.to_business()` and `shared/revenue_reference._as_datetime()` read a naive
  datetime as **Africa/Casablanca-local**. `shared/fleet_status_reference._parse()`,
  `backend/app/services/fleet_status.py`, and `desktop/app/utils/datetime_utils.parse_datetime_utc()`
  read a naive datetime as **UTC**. Both are documented with confident docstrings. Currently
  dormant because the sync path serialises aware ISO strings off `TIMESTAMPTZ` columns and the
  desktop stores datetimes as `String(50)` ISO with offset — but the first naive string to reach
  either engine shifts revenue or fleet state by up to one hour (0 h during Ramadan). Flagged in
  `car-rental-status-contradiction-forensic`, `car-rental-prod-db-outage-and-readiness`, and
  `car-rental-dashboard-split-revenue-rule`; still open.

- **P2-5 — desktop `reservation_list.py` is internally inconsistent about the picker's timezone.**
  The create payload (l. 372–373) reads the `QDateTime` as Casablanca wall-clock (correct);
  the availability pre-check (l. 219–220, 584–585) uses `toPython().astimezone(timezone.utc)`
  on a naive value → assumes **OS-local**. Agree only when the operator's PC is set to
  Africa/Casablanca. The DB `EXCLUDE` constraint still prevents a real double-book; the risk is a
  misleading availability grid.

---

## 4. DATABASE STATUS — is PostgreSQL really authoritative?

**Yes, for data.** `TIMESTAMP(timezone=True)` columns, `NUMERIC` money, FK
`reservations.vehicle_id → vehicles.id ON DELETE RESTRICT`, comprehensive `CHECK` constraints
(status enums, non-negative money, `num_days >= 1`, `end > start`, `length(vin) = 17`,
`year BETWEEN 1990 AND 2035`), unique `registration` / `vin` / user email, and the `btree_gist`
range-exclusion constraint for overlap. Migration chain is linear
(`001_foundation … h3c4d5e6f7g8`), and per `car-rental-prod-db-outage-and-readiness` the prod DB
was recovered to 1 GB and `alembic upgrade head` applied through `h3c4d5e6f7g8`. `/health/ready`
confirms the pool is initialised and the DB answers `SELECT 1`.

**Gaps:**

- **P2-9 — CI's Postgres run builds the schema with `Base.metadata.create_all`, not
  `alembic upgrade head`.** Model/migration drift is therefore not caught by CI. (The Fly
  `release_command` *does* run `alembic upgrade head`, so prod uses migrations — but nothing
  proves the migration chain reproduces the models.)
- **P2-10 — `Reservation.customer_id` has no FK constraint** (it is a bare indexed UUID column).
  Clients are soft-deleted (`status='DELETED'`), which mitigates in practice, but the canonical
  link is unenforced.
- **P3 — `year <= 2035`** will start rejecting legitimate model years within a few years.
- **P3 — VIN is validated only by `length = 17`.** "AAAAAAAAAAAAAAAAA" passes. Acceptable for an
  internal tool; note it as a data-quality (not code) gap.

---

## 5. SYNC STATUS — can stale state overwrite newer state?

**Shipped build (`725fed5`) / deployed backend:** the incremental pull is `updated_at >= since`
with delete-tombstones derived from `AuditLog(action='DELETED', created_at >= since)`. `>=` (not
`>`) re-fetches the boundary row each cycle — idempotent, mildly wasteful, and it papers over the
"written in the same second as `since`" lost-update window. `/api/v1/sync/bootstrap` returns a
monotonic `revision` (max `updated_at` epoch-ms) and the mobile client applies it as one atomic
Room transaction with a `synced_through_revision` watermark (Increment 5) — mobile cannot go
sparse. **No global ordered revision on the desktop incremental path** — it is still
timestamp-cursor based.

**`eacfa55` (main HEAD) adds `SyncEngine.bootstrap()` on desktop, but:**

- **P2-6 — it only reconciles/purges VEHICLES.** The docstring says *"Guarantees that local
  SQLite cache is a 100 % faithful mirror of PostgreSQL, purging any local records that were
  deleted on the server"* — the code fetches `data["vehicles"]`, deletes local vehicles absent
  from the server set, and upserts vehicles. **Reservations, clients and maintenances are not
  touched at all.** A reservation cancelled/deleted server-side is not reconciled by bootstrap;
  desktop still depends on the timestamp-cursor incremental pull for 3 of 4 entity types — the
  same sparse-cache class the mobile Increment-5 work eliminated.
- `eacfa55` also adds a good defensive guard to the incremental pull: skip a pulled row whose
  incoming `version < local.version` (anti-regression) and propagate server `created_at`.

**P1-1 — the anti-reversion mechanism over-reaches (see §3).** `DomainStore._server_overview`
becomes a permanent override; `dashboard.py._is_live_revenue` rejects **every** subsequent
`source == "local"` revenue result; mobile `performanceMetricsFlow = api ?: local`. This
correctly stops a *stale local snapshot* from clobbering a *fresh server number*, but it also
stops the *legitimate local time-progression recompute*. The 8 new regression tests in `eacfa55`
(`test_refresh_reversion_forensic.py`, `test_dashboard_cache_reversion.py`,
`MobileLiveAuthorityTest.kt`, …) cover late responses, rapid refreshes, background sync, WS
events, startup, offline/reconnect, tab switch — **none cover a clock crossing a boundary while
online**, which is exactly the case that now regresses.

---

## 6. DESKTOP STATUS

- **Functional:** renders the Vehicles list and Dashboard fleet cards from the `DomainStore`
  snapshot (canonical effective status); `ReservationWidget` / `MaintenanceWidget` render from
  the snapshot; 8 mutation handlers go through `store.mutate()`. `BoundaryClock` is a single
  single-shot timer (no polling). WS realtime client. `QScrollArea` around the dashboard (fixes
  the earlier vertical clipping).
- **P1-1 (defect):** dashboard fleet cards + period revenue cards freeze to the last server
  fetch while online; at a reservation/maintenance/ midnight boundary the Vehicles list updates
  and the Dashboard does not → transient cross-screen contradiction until "Actualiser" or a WS
  push. **In `main` HEAD only — not in the shipped `725fed5` build.**
- **P2-5 (defect):** availability-probe vs create-payload timezone mismatch in
  `reservation_list.py` (see §3).
- **P2-6:** `bootstrap()` reconciles only vehicles.
- **Debt (from memory, still true):** `_create_reservation_record` is *not* migrated to
  `store.mutate()` (converges via `refresh_data() → store.reload()`, so not a 2nd authority, but
  the odd one out). `data_refreshed` pulse not fully retired.
- **UX:** `eacfa55` widens reservation/vehicle table columns + adds cell tooltips + button
  min-widths (addresses truncation reports). **Not visually verifiable here** (no display /
  xvfb); trust the diff + the operator's screenshot loop.
- **P3:** several `datetime.now().strftime('%H:%M')` for header timestamps (display only, naive
  local — harmless).

---

## 7. MOBILE STATUS

- **Functional:** Room mirror; `FleetStatus.kt` / `RevenueEngine.kt` Kotlin ports parity-tested
  against the shared golden vectors; `BoundaryTicker` (cold `channelFlow`, no polling);
  `/sync/bootstrap` atomic apply with revision watermark (cannot go sparse); server-readiness
  probe + `OfflineBanner` + DB-down empty states; session restore hardened (a transient 5xx/
  timeout no longer wipes the 7-day refresh token — `car-rental-mobile-session-fix`); plaintext
  login password never persisted / restorable / logged, with forensic tests
  (`car-rental-mobile-password-security`).
- **P1-1 (defect):** `performanceMetricsFlow` flipped to `api ?: local` in `eacfa55`. Once
  `_liveMetrics != null` (any successful `/dashboard/stats` since app start, reset only on a full
  cache wipe), the dashboard shows the server snapshot and ignores `localMetricsFlow` — the only
  flow wired to `boundaryTicks`. Midnight revenue rollover and time-derived KPI transitions
  freeze while online. **In `main` HEAD only — the shipped `725fed5` APK still has
  `local ?: api`.**
- **i18n / RTL:** FR + AR maps in `ui/i18n/Localization.kt` (~104 keys) + `LayoutDirection.Rtl`
  switch in `MainActivity` when `AppLanguage.AR`. Present and wired. (No `res/values-ar/` — the
  app uses an in-code table, which is fine.)
- **P2-7:** the shipped APK is **debug-signed** (`debugConfig`); a production signed APK cannot
  be produced in this environment (keystore is a CI-only secret). `apksigner verify` passes but
  it is a debug cert.
- **Not verified:** any on-device / emulator runtime (no AVD here). All mobile evidence is unit
  tests + static review.

---

## 8. SECURITY STATUS — no blockers

| Control | Finding |
|---|---|
| Password hashing | **Argon2id** (`time_cost=3, memory=64 MB, parallelism=4`), never logged; `needs_rehash` supported |
| JWT | `jose` HS256, **separate** access/refresh secrets, `type` claim checked, 15 min access / 7 day refresh, `jti`, refresh tokens stored hashed, account-lockout migration present |
| RBAC | Server-side matrix (`ADMIN`/`MANAGER`/`EMPLOYEE`/`MOBILE_USER`), `require_perm(...)` dependency on every mutating route; `test_rbac.py` green |
| Transport / headers | `SecurityHeadersMiddleware`, `RequestSizeLimitMiddleware` (10 MB), `slowapi` rate limit `100/minute`, `force_https` at Fly |
| Secrets | None hardcoded in `backend/app`, `shared`, `desktop/app/{services,sync}`; all via env / Fly secrets; global exception handler never returns stack traces / SQL |
| CORS | `CORS_ORIGINS` unset in prod → empty allow-list (native clients only, no browser origin) |
| Injection | SQLAlchemy Core/ORM throughout, parameterised; no string-built SQL in app code |
| Upload validation | size-limited; content-type / magic-byte validation is light (P3) |

**P3 notes:** `/docs`, `/redoc`, `/openapi.json` are publicly reachable in production (hardcoded
`docs_url`); low risk for an internal tool but consider gating behind auth or `DEBUG`. The prod
`ADMIN_PASSWORD` is a real Fly secret (good) but also present in the local `.env` (dev hygiene).

---

## 9. DATA QUALITY STATUS

No authenticated production data pull was possible from here (classifier blocked the admin login
— correct). Per `car-rental-prod-db-outage-and-readiness` the prod dataset as of 2026-09-02 was
**3 vehicles / 11 reservations / 1 maintenance / 11 clients / 2 users**, plus **2 inert forensic
probe rentals** left in prod (dated 2027, `CANCELLED`) by earlier sessions —
`scripts/purge_forensic_probes.sql` exists to remove them and **should be run before handover**.
VIN/registration are only length/uniqueness-validated, so garbage values are technically possible
(data-quality, not a code bug). No evidence of fabricated dashboard data — the notification scan
and all KPIs derive from real rows.

---

## 10. REQUIREMENTS TRACEABILITY MATRIX

| Requirement | Implementation | Evidence | Status |
|---|---|---|---|
| Vehicle management (CRUD, status, docs, photos) | `api/v1/vehicles.py`, `models/vehicle.py`, `vehicle_image.py` | `test_vehicles.py`, CHECK constraints | **PASS** |
| Vehicle effective status (one derivation) | `shared/fleet_status_reference.py` + 3 runtime ports | `test_fleet_status_crossruntime.py` ×3, 14 vectors | **PASS** |
| Reservations (overlap prevention) | `excl_reservations_no_overlap` (PG), `check_availability()` | `test_double_booking.py`, `test_constraints.py` | **PASS** |
| Reservation lifecycle (RESERVED/ACTIVE/COMPLETED/CANCELLED) | `rental_service.py` | `test_sync_lifecycle.py`, `test_activer_action.py` | **PASS** |
| Client management (canonical entity, CIN, history, KPIs) | `models/client.py`, `client_service.py` | `test_clients.py`, `test_client_rentals_report.py` | **PASS** |
| Client ↔ reservation link | `Reservation.customer_id` (no FK) + denormalised name | `test_reservation_client_linking.py` | **PARTIAL** (unenforced FK) |
| Maintenance (schedule-derived block, return to service, precedence) | `api/v1/maintenance.py`, `fleet_status.py` | `test_maintenance_wins_reservation.py`, `test_maintenance_frees_vehicle.py` | **PASS** (but see P1-2) |
| Dashboard fleet counts | `dashboard_service.get_overview` → `compute_fleet_counts` | `test_fleet_status_parity.py` | **PASS** |
| Revenue (pro-rata, all periods, custom range) | `shared/revenue_reference.py` + 3 ports; `/dashboard/revenue`, `/period/{name}` | `test_revenue_crossruntime.py`, `test_revenue_consistency.py`, `test_api_contract_release_gate.py` | **PASS** (code); **PARTIAL** (deploy-contract not CI-checked) |
| Vehicle utilization (overlap-safe) | `shared/utilization_reference.py` | `test_utilization_interval_union.py` | **PASS** |
| Sync — desktop offline | `desktop/app/sync/engine.py`, `DomainStore` | `test_domain_store*.py` | **PARTIAL** (bootstrap reconciles vehicles only; timestamp cursor) |
| Sync — mobile offline | `/sync/bootstrap` + revision watermark | `MobileSparseCacheForensicTest`, `CrossClientConvergenceTest` | **PASS** |
| Time-live transitions (no manual refresh) | `BoundaryClock` / `BoundaryTicker` | `test_boundary_clock.py`, `BoundaryTickerTest` | **REGRESSED in HEAD** (P1-1) — PASS in shipped `725fed5` |
| Live cross-client (desktop ↔ mobile) | `EventBroadcaster` + WS | prior live E2E in memory; not re-run here | **PARTIAL** (single-machine only; needs Redis if scaled >1) |
| Security (hashing, JWT, RBAC) | `auth/`, `security/` | `test_auth.py`, `test_rbac.py`, `test_realtime_auth.py` | **PASS** |
| Arabic / RTL | desktop `i18n/ar.json`; mobile `Localization.kt` + `LayoutDirection.Rtl` | present, wired | **PASS** (translation completeness not exhaustively reviewed) |
| Responsive desktop UI | `QScrollArea`, column/button widths (`eacfa55`) | diff review only (no display here) | **PARTIAL** (not visually verified) |
| Production release (signed, tagged, reproducible) | local debug APK + wine PyInstaller EXE; `RELEASE_MANIFEST.md` | manifest APK SHA ≠ on-disk file | **PARTIAL / FAIL** (see P2-7, P2-8) |

---

## 11. CRITICAL DEFECTS

### P0 — RELEASE BLOCKER
*None found in the shipped `725fed5` build / deployed v27 backend.* The money math, the
double-booking constraint, and auth are sound and enforced.

### P1 — CRITICAL

- **P1-1 — Time-liveness regression in `main` HEAD (`eacfa55`, unpushed).**
  *Files:* `desktop/app/state/domain_store.py` (`update_server_dashboard`, `recompute_effective`
  gated on `self._server_overview is None`), `desktop/app/ui/dashboard.py` (`_is_live_revenue`
  rejects all later `source=="local"`), `desktop/app/ui/main_window.py` (`_refresh_dashboard`
  prefers `_authoritative_server_overview`), `mobile/.../FleetRepository.kt`
  (`performanceMetricsFlow = combine(local, api){ local, api -> api ?: local }`).
  *Rule broken:* "the period revenue cards and fleet cards roll over at local midnight / at each
  reservation boundary with no API call and no user action" (Increments 3/4/6) and "all screens
  agree on a vehicle's state" (`car-rental-status-contradiction-forensic`).
  *Root cause:* the anti-reversion fix makes the server overview a permanent override instead of
  "authoritative for the current wall-clock period only"; the boundary tick is not wired to
  invalidate it or to trigger a refetch.
  *Impact:* while online, after any boundary, Dashboard fleet cards + revenue cards show stale
  values while the Vehicles list is fresh — transient contradiction until manual refresh / WS
  push; at local midnight the CA cards do not roll until the next fetch.
  *Fix:* invalidate `_server_overview` / `_is_live_revenue` / `_liveMetrics` when
  `now` crosses `snapshot.next_boundary` (and either recompute locally or auto-refetch); OR keep
  server-authoritative but have the `BoundaryClock`/`BoundaryTicker` call
  `_refresh_dashboard(fetch_server=True)` / `refreshDashboard()` on the tick. Add a regression
  test: "app online, advance injected clock past midnight, assert period cards rolled."

- **P1-2 — Maintenance scheduled over an in-progress rental silently cancels it and erases its
  realised revenue.** *Files:* `backend/app/repositories/rental_repository.py`
  (`cancel_overlapping_reservations` — no covering-now guard), `backend/app/api/v1/maintenance.py`
  (create/update call it unconditionally), `shared/revenue_reference.py`
  (`is_revenue_eligible` → `False` for all `CANCELLED`, no realised-days carve-out).
  *Impact:* an operator booking maintenance can cancel a rental the customer is currently on and
  wipe already-earned CA from the dashboard, with only a notification.
  *Fix:* block or explicitly confirm maintenance overlapping a covering-now reservation; and/or
  recognise realised days for a reservation that was `CANCELLED` after `start_datetime`.

### P2 — IMPORTANT

- **P2-3 — Early `COMPLETE` recognises full `num_days` revenue on future calendar dates** (needs
  business rule; §2).
- **P2-4 — Two opposite naive-datetime timezone policies** in the same repo (`shared/money_time`
  + `revenue_reference` = Casablanca-local vs `fleet_status_reference` +
  `desktop/utils/datetime_utils` = UTC). Dormant, but 1 h skew waiting on the first naive
  string. Unify to ONE policy.
- **P2-5 — desktop `reservation_list.py`** availability-probe (`astimezone(utc)` on naive =
  OS-local) vs create-payload (Casablanca) timezone mismatch.
- **P2-6 — `SyncEngine.bootstrap()` reconciles vehicles only** despite a "100 % faithful mirror"
  docstring; reservations/clients/maintenances still rely on the timestamp-cursor incremental
  pull.
- **P2-7 — Release provenance is broken.** `RELEASE_MANIFEST.md` APK SHA256 `e3391dc2…` ≠ actual
  `ATELIER_BERLIN_LOCATION_CAR_725fed5.apk` on disk (`508c0b64…`); unreferenced `_eacfa55`
  APK+ZIP also on disk; no git tag since `v1.0.6`; `main` unpushed; APK debug-signed.
- **P2-8 — No deploy-contract test.** `test_api_contract_release_gate.py` runs against the
  in-process test app, not the deployed backend — the precise lesson of the 2026-09-03
  split-brain forensic is still not encoded in CI.
- **P2-9 — CI Postgres job uses `create_all`, not `alembic upgrade head`** → migration/model
  drift not caught.
- **P2-10 — `Reservation.customer_id` has no FK constraint.**

### P3 — COSMETIC / MINOR

- `get_today_rentals`/`get_today_returns` use `23:59:59` inclusive (misses the final second) and
  bare `datetime.now(tz)` instead of `now_business()`.
- `year <= 2035` CHECK; VIN validated by length only.
- `/docs` + `/openapi.json` public in prod.
- Client `total_amount` (full price) vs dashboard CA (pro-rata) unexplained to the user.
- Repo hygiene: 18 untracked files in root, stale 516 MB `dist/…WIN.zip` (Aug 29), multiple
  superseded APKs/ZIPs.
- `test_no_naive_now` is a grep and is trivially bypassable.

---

## 12. MISSING FEATURES

Nothing in the stated scope is entirely absent. Items that are *partial*:

- Desktop full-snapshot reconciliation for reservations/clients/maintenances (only vehicles).
- A global monotonic revision on the desktop incremental sync path (mobile has it via bootstrap).
- CI gate that a build's clients and the deployed backend agree on a golden dataset.
- Migration-vs-model schema-drift test.
- Production-signed mobile APK (blocked by environment, exists only via the `v*`-tag CI workflow).
- Multi-machine `EventBroadcaster` (in-process singleton; needs Redis pub/sub if Fly ever runs
  >1 machine).

---

## 13. TEST GAPS

- **No test** for "online + clock crosses a boundary → dashboard cards update" (the P1-1 case).
  `eacfa55` added 8 reversion tests, all for network-ordering races.
- **No test** that the *deployed* backend matches `shared/revenue_reference.py` on a golden
  dataset (only in-process).
- **No test** that `alembic upgrade head` reproduces `Base.metadata`.
- **No test** for maintenance-over-a-covering-now-rental (P1-2).
- Overlap/exclusion constraint on SQLite is an emulation **trigger** in `conftest.py`, not the
  real `EXCLUDE`; the real constraint is only exercised in the CI Postgres job (which *is*
  configured — good).
- Desktop suite is slow (300 tests → ~15 min, several real-`QTimer` forensic proofs) and some
  temporal tests are documented as wall-clock-flaky under full-suite load (made deterministic
  with an injected clock in the guarded ones). All 300 pass.
- Mobile: **zero** instrumented/on-device tests (no emulator); all coverage is JVM unit tests +
  Robolectric.

---

## 14. REAL-WORLD FAILURE SCENARIOS

| Scenario | Expected | Actual | Verdict |
|---|---|---|---|
| Two operators reserve the same vehicle for overlapping dates simultaneously | Second write rejected | App pre-check races, but PG `EXCLUDE` rejects the loser (`IntegrityError → "double_booking"`) | **SAFE** |
| Network drops mid-reservation-create | No partial row | Single transaction + `flush`/`commit`; `IntegrityError` path rolls back | **SAFE** |
| Refresh while `SyncEngine` is running | No corruption / no revert to stale | `eacfa55` generation counters + version guards; `_run_sync` coalesces | **SAFE** (but see next) |
| Clock crosses local midnight while app is online | Period revenue + fleet cards roll automatically | **HEAD: they do NOT until next fetch; Vehicles list does → contradiction.** Shipped `725fed5`: they roll | **UNSAFE in HEAD**, SAFE in shipped |
| API returns a stale row (`updated_at` just below `since`) | Not lost | `>= since` re-fetch window covers most cases; a same-instant write after the query still races | **MOSTLY SAFE** |
| Desktop SQLite holds a reservation the server already cancelled | Reconciled on next sync | Incremental pull via `AuditLog` tombstone; `bootstrap()` does **not** cover reservations | **PARTIAL** |
| Vehicle enters maintenance during an active reservation | Sensible handling / warning | Reservation silently `CANCELLED`, realised revenue → 0 | **UNSAFE** (P1-2) |
| Reservation cancelled after the vehicle was shown available | Grid corrects | Effective-status derivation + fan-out; grid re-renders | **SAFE** |
| Client deleted while historical rental exists | History preserved | Client soft-delete (`status='DELETED'`); rows kept | **SAFE** |
| Vehicle deleted while rentals exist | Blocked | FK `ON DELETE RESTRICT` | **SAFE** (verify the API returns a clean 4xx, not 500) |
| Transient 5xx / cold-start on mobile refresh | Session kept, cached data shown | Fixed — `validateAndRestoreSession` only clears on explicit 401/403 or provably-expired token | **SAFE** |
| Production DB out of memory / down | Clients detect it, show offline banner, don't fabricate | `/health/ready` real `SELECT 1`; mobile `SERVER_DB_UNAVAILABLE` + banner; Room untouched | **SAFE** (post-recovery) |
| Fly scales to 2 machines | Live WS events still delivered | `EventBroadcaster` is in-process — second machine's clients miss events | **UNSAFE if scaled** (`min_machines_running=1` + suspend mitigates today) |

---

## 15. FINAL SCORECARD

| Dimension | Score | Why |
|---|---:|---|
| Business Logic | **82/100** | One-spec engines for status & revenue are excellent and parity-locked; −18 for the maintenance-cancels-active-rental revenue erasure (P1-2), early-complete future-date recognition (P2-3), and the naive-tz split (P2-4). |
| Architecture | **80/100** | Genuine single-source-of-truth for the math; DomainStore/BoundaryClock/Ticker are real. −20 for the HEAD authority-direction reversal killing time-liveness (P1-1) and desktop bootstrap covering one entity type (P2-6). |
| Data Integrity | **88/100** | Real PG constraints incl. range-exclusion, deployed. −12 for unenforced `customer_id` FK, no migration-drift test, VIN quality. |
| Synchronization | **72/100** | Mobile bootstrap+revision is solid; −28 for desktop timestamp-cursor + vehicles-only reconciliation + the P1-1 freeze. |
| Desktop | **74/100** | Snapshot-driven rendering, boundary clock, WS. −26 for P1-1, P2-5, P2-6, unverified responsive pass. |
| Android | **80/100** | Parity ports, bootstrap, session + password hardening. −20 for P1-1 flip, debug-signed only, no on-device tests. |
| Backend / API | **88/100** | Clean layering, 217 green, dual-DB CI, real readiness split, pro-rata endpoints deployed. −12 for deploy-contract gap + `create_all` CI schema. |
| Security | **90/100** | Argon2id, sane JWT, server-side RBAC, headers, rate limit, no hardcoded secrets. −10 for public docs, light upload validation. |
| Testing Quality | **72/100** | Golden-vector cross-runtime parity is real and valuable; −28 for the boundary-while-online gap, no deploy-contract test, no migration-drift test, grep-based guards, zero mobile instrumented tests. |
| UX / UI | **70/100** | i18n FR/AR + RTL, offline banners, scroll fixes, truncation fixes. −30 because none of it is visually verifiable here and the P1-1 contradiction is user-visible. |
| Production Readiness | **62/100** | Shipped pair is coherent and live; −38 for release-provenance mess (manifest hash mismatch, no tag, unpushed HEAD, prod stale), debug-signed APK, HEAD carrying an unreviewed P1. |

**Overall: ~77 / 100 — "solid engineering, not yet a clean release".**

---

## 16. RELEASE DECISION

# 🟡 RELEASE READY WITH CONDITIONS

The **shipped `725fed5` clients + deployed v27 backend** are a coherent, self-consistent,
reasonably tested pair with sound money math, database-enforced double-booking prevention, and
solid security — adequate for the single-site, few-operators business this targets. They may
continue in production.

**Conditions that must be met before the next release / before this is "signed off":**

1. **Do NOT push/build/deploy `eacfa55` (main HEAD) as-is.** Fix P1-1 first (wire the boundary
   tick to invalidate or refetch the server overview) and add the missing regression test, OR
   consciously accept "dashboard KPIs are only as fresh as the last fetch while online" as a
   documented product decision.
2. **Resolve P1-2** — decide and implement the rule for maintenance overlapping a covering-now
   rental (block / confirm) and whether realised revenue survives a post-start cancellation.
3. **Fix release provenance** — one git tag per release, `RELEASE_MANIFEST.md` hashes that match
   the artifacts on disk, push `main`, delete or archive superseded artifacts, and document
   which commit prod is running.
4. **Get the business owner's ruling on early-completion revenue** (P2-3) and align the spec.
5. **Unify the naive-datetime timezone policy** (P2-4) to a single documented rule and delete the
   contradicting one.

**Recommended (not strictly blocking):**

6. Add a CI deploy-contract test (golden dataset → deployed `/dashboard/*` vs
   `shared/revenue_reference.py`).
7. Make the CI Postgres job build the schema via `alembic upgrade head`.
8. Extend desktop `bootstrap()` to reconcile reservations, clients and maintenances.
9. Run `scripts/purge_forensic_probes.sql` on prod and confirm the 2027 probe rentals are gone.
10. Add the `customer_id` FK (or document the soft-delete invariant that substitutes for it).

---

## 17. WHAT IS CORRECT / BROKEN / PARTIAL / MISSING / RISKY  (one-glance)

**CORRECT:** fleet-status spec + 3-runtime parity · revenue spec + 3-runtime parity · PG
range-exclusion double-booking (deployed) · CHECK constraints · Argon2id + JWT + RBAC · readiness
/ liveness split · mobile bootstrap + revision watermark · mobile session & password hardening ·
maintenance schedule-derived status (6a fix) · i18n FR/AR + RTL wiring · **217 backend + 300
desktop + 68 mobile tests green (0 failures)**.

**BROKEN:** time-liveness of dashboard KPIs while online (P1-1, HEAD only) · maintenance silently
cancels in-progress rentals & erases their revenue (P1-2) · `RELEASE_MANIFEST.md` APK hash ≠
artifact (P2-7).

**PARTIAL:** desktop `bootstrap()` (vehicles only) · desktop incremental sync (timestamp cursor,
no global revision) · deploy-contract verification (in-process only) · responsive UI (not
visually verified) · live cross-client (single machine only).

**MISSING:** boundary-while-online test · migration-drift test · deploy-contract CI gate ·
production-signed APK (env-blocked) · multi-machine event fan-out.

**RISKY:** naive-datetime tz split (P2-4) · early-complete full recognition on future dates
(P2-3) · `customer_id` unenforced link (P2-10) · `EventBroadcaster` if Fly ever scales >1 ·
unpushed `main` carrying an unreviewed P1.

---

*Prepared as a read-only audit. No source files were modified. Test suites were executed
read-only. Live production was probed only via anonymous health/schema endpoints.*
