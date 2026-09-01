# MASTER — 100% LIVE ARCHITECTURE REPORT

**Project:** `/home/ayman/car-rental-system`
**Date:** 2026-08-30
**HEAD:** `df9b96dfa56692845560d18995c5c83503f01140` (branch `main`, 12 commits ahead of `origin/main`, unpushed)
**Working tree:** DIRTY — 94 changed paths of prior in-progress work + this increment.
**Scope of this document:** the fundamental architectural analysis, the target
architecture, and a sequenced, test-gated implementation plan. **Increment 1 is
implemented and green in this pass** (see §17). Increments 2–6 are specified but
not yet built — they restructure the desktop UI and the sync contract and must
land one at a time behind test gates.

---

## 0. HONEST FRAMING (read first)

"100% live" **is achievable** with a correct design — it is not blocked by
anything physical. But it is a **multi-increment program across three
codebases** (FastAPI/PostgreSQL, PySide6/SQLite, Android/Compose/Room), not a
single edit. Dropping a from-scratch state engine on top of 94 uncommitted
files, with no device / no production / no Android emulator available for
end-to-end verification (documented environment limit), would produce something
**unshippable and unbisectable**. The responsible path, and the one taken here:

1. Prove the root cause with a running test (Increment 1 — **done**).
2. Land the architecture in 6 revertible increments, each with its own tests.
3. Delete the old path only after the replacement is proven (Phase 18 rule).

`TRUE 100% LIVE SHOWROOM — PASS` **cannot** be declared from this environment:
the final proof requires a real Android device + the deployed backend + two
desktop instances against one server. What *can* be delivered here is the
architecture, the safety nets, and increments whose unit/integration tests
pass. Current status: **NOT READY — architecture defined, Increment 1 landed.**

---

## 1. FUNDAMENTAL ARCHITECTURAL PROBLEM

There is not one bug. There are **four structural facts**, and exactly one is
the root:

> **ROOT CAUSE — there is no single, ordered, observable stream of *committed
> domain state* that every screen derives from.** State is *copied*
> (SQLite → page-dict → widget on desktop; server → Room → domain on mobile)
> and re-synchronised by **coarse invalidation pulses that carry no version**.
> Therefore:
>
> 1. any missed or failed pulse permanently strands a copy until an unrelated
>    mutation happens to refresh it;
> 2. the same fact is computed by **three separate code paths** (backend SQL,
>    desktop Python, mobile Kotlin) with nothing forcing them equal;
> 3. **wall-clock time changes business truth but emits no pulse**, so a
>    reservation that ends at 18:00 is not reflected anywhere until the next
>    user action or a server-side change.

### The state graph, as it exists today

```
                         PostgreSQL  (authoritative)
                              │
        ┌─────────────────────┼───────────────────────┐
        │  /sync/pull?since=<timestamp>   (updated_at >= since)
        ▼                                              ▼
  Desktop SQLite  (LocalVehicle/…)              Mobile Room  (VehicleEntity/…)
        │  one-shot session.query(...)                 │  @Query ... Flow<List<>>
        ▼                                              ▼
  _load_vehicles_from_local()  builds dicts       repository.map { }  → StateFlow
        │  vehicle_list.load_vehicles(dicts)           │  ViewModel.stateIn
        ▼                                              ▼
   QWidget owns the copy                          Compose reads StateFlow
        ▲                                              ▲
        │  EventBus.data_refreshed.emit()  (no args)   │  RealtimeSyncManager →
        │  → _on_global_data_refreshed()  re-runs      │  fleetRepository.refreshAll()
        │     ALL 5 page refreshes + dashboard         │  (full re-pull, clearAll+insert)
        │                                              │
   RealtimeEventsClient (WS + 5s poll)           RealtimeSyncManager (WS + 20s poll)
        │  event = {type, vehicle_id}  (no state)      │  event = {type, entityId}
        └──────────── FastAPI event_broadcaster ───────┘
```

### Evidence for each structural fact

| # | Fact | Evidence |
|---|---|---|
| A | **≥3 effective-status implementations.** | `backend/app/services/fleet_status.py` (async SQL), `desktop/app/utils/fleet_status.py` (sync SQL, hand-ported), mobile `FleetRepository.mapVehicleDtoToDomain` (`dto.effectiveStatus ?: VehicleStatus.fromApi(dto.status)` — depends on the server field, no local interval math). Three code paths, **zero tests asserting equality** until Increment 1. |
| B | **`data_refreshed` is a level-less pulse.** | `desktop/app/services/event_bus.py`: two signals; `entity_changed(str,str)` is **declared but never emitted anywhere** (`grep -rn entity_changed desktop/app` → only the definition). Everything uses `data_refreshed` (no args). No consumer records "which revision am I showing". |
| C | **Widgets are state owners.** | `main_window._on_global_data_refreshed` loops over 5 callbacks (`_load_vehicles_from_local`, `_refresh_dashboard`, `_reservations.refresh_data`, …), each wrapped in `try/except` that only logs. A throw or a not-yet-constructed page = that widget silently keeps stale data; nothing retries. |
| D | **Time is invisible.** | `compute_fleet_sets(session)` uses `datetime.now(...)` correctly, but the only things that re-invoke it are: a mutation, a realtime event, or the 30 s sync timer — and `_on_sync_finished` **only** emits `data_refreshed` when `push/pull/upload` actually changed rows (`main_window.py` ~line 613). Quiet server + time passes ⇒ desktop never re-derives. No component's job is "advance state at the next interval boundary." |
| E | **Timestamp-based pull, not revision-based.** | `backend/app/services/sync_service.py` pull = `WHERE updated_at >= since` for each table. Hazards: clock skew between client and server, same-second writes, the boundary row re-pulled every cycle, and a backdated `updated_at` is missed entirely. Per-row `version` exists (optimistic lock) but there is **no global monotonic revision**. |
| F | **Mobile full-wipe refresh.** | `FleetRepository.refreshVehicles()` = `vehicleDao().clearAll()` then `insertVehicles(...)` inside a transaction; Room emits an empty list then the full list — a visible flicker, and any `combine{}` sees a transient zero. A concurrent pull can also clobber an un-pushed local optimistic write (last-write-wins, no version check on apply). |

---

## 2. PREVIOUS ARCHITECTURE (what each layer does today)

### Backend — the healthiest layer
- `fleet_status.py` **is** a genuine single source of truth for effective
  status: SQL, precedence-ordered, half-open intervals, open-ended maintenance
  handled. `/vehicles` list, `/vehicles/stats`, and `DashboardService` all call
  it (`dashboard_service.py:32` → `from app.services.fleet_status import compute_fleet_counts`).
- Realtime: `event_broadcaster` → WS `/events/ws` + `/events/recent` polling.
  Events are **notifications only** — `{event_type, vehicle_id, message}`, no
  state, no revision.
- Sync: `/sync/push` (per-item, returns conflicts), `/sync/pull?since=<ts>`.
- The historical "Dashboard 5 vs real 4" bug was a JOIN that multiplied vehicle
  rows by their reservation/maintenance rows; it is **already fixed** by routing
  everything through `compute_effective_statuses` (which buckets each vehicle
  exactly once). Increment 1 confirms this holds on 14 vectors.

### Desktop — offline-first, widget-owned state
- `SyncEngine` (asyncio, on its own thread) does `uploads → push → pull`;
  `apply_pulled_items` merges rows into SQLite.
- `MainWindow` orchestrates: a 30 s `_sync_timer`, a `RealtimeEventsClient`
  that on any event schedules a sync in 250 ms, and `EventBus.data_refreshed`
  wired to `_on_global_data_refreshed`.
- Every mutation path (`_create_vehicle`, `_save_maintenance`, …) does
  `session.commit()` then `get_event_bus().data_refreshed.emit()` then
  `_run_sync()`.
- `data_refreshed` → **refresh storm**: 5 full table re-queries + 1 dashboard
  recompute + 1 server round-trip, for every single create/update/delete.
- Dashboard: `_refresh_dashboard` renders instantly from
  `dashboard_cache.compute_local_overview()` (local SQLite), then a
  `DashboardFetcher` QThread overwrites with `/dashboard/stats`; a
  `_dashboard_generation` counter drops stale responses.

### Mobile — the closest to reactive, undermined by refresh strategy
- Room `@Query … Flow<List<Entity>>` → `FleetRepository` `.map` →
  `FleetViewModel` `stateIn(WhileSubscribed(5000))` → Compose. A Room write
  **does** auto-propagate to every collector — this part is correct.
- But: `refreshX()` = `clearAll()` + `insert` (fact F); metrics & notifications
  are `MutableStateFlow` pushed by hand (lost on process death, not Room-backed);
  effective status is taken from the server DTO, never re-derived locally, so
  offline + time passing shows stale state.
- `RealtimeSyncManager`: WS + 20 s poll; on event → `fleetRepository.handleRealtimeEvent`;
  on reconnect → `refreshAll()`.

---

## 3. WHY IT FAILED (mapping symptoms → root)

| Symptom you have seen | Structural fact | Mechanism |
|---|---|---|
| Dashboard ≠ Vehicles count | A + C | two derivations, or one page's refresh callback threw and was swallowed |
| Reservation ends, vehicle still "RENTED" until you click | **D** | no time-boundary trigger; quiet sync emits no pulse |
| Create maintenance, Reservations tab still shows the cancelled booking as active | B + C | `data_refreshed` fired before the reservations page existed / its refresh threw |
| Mobile shows a value the desktop already changed | E + F | timestamp pull missed the row (same-second / skew), or a full-wipe refresh raced |
| Brief blank list on mobile pull | F | `clearAll()` emits `[]` before `insert` |
| "Dead button": click → DB changes → UI stale | B + C | mutation committed and emitted, but the owning widget's refresh path failed silently |
| Double-booking slips through under load | E | client availability check reads a local cache that a concurrent pull has not yet updated |

---

## 4. NEW ARCHITECTURE — "one derivation · versioned projection · boundary clock"

Five principles. Each maps to one or more increments in §5.

### P1 — ONE effective-state calculator, one spec, enforced across runtimes
- `shared/fleet_status_reference.py` is the **normative pure-function spec**
  (no ORM/DB/network). `shared/fleet_status_cases.json` is the vector set.
- Backend, desktop, and mobile each keep their own implementation for
  performance, but **each has a parity test that asserts byte-equality with the
  reference on every vector.** Drift becomes a red build, not a production
  incident. *(Increment 1 — done for backend + desktop; mobile test specified.)*
- Every client computes effective status **locally from raw rows**
  (`vehicle.status` + reservation intervals + maintenance intervals + `now`).
  The server's `effective_status` field becomes a cross-check hint, never the
  source of truth — so offline + time passing still shows the correct state.

### P2 — Desktop: one `DomainStore`; views are pure subscribers
- New `desktop/app/state/domain_store.py`:
  - owns the **only** in-memory snapshot `{vehicles, reservations, maintenances, clients}`, loaded from SQLite;
  - holds a monotonic `revision: int`;
  - `store.mutate(fn)` runs `fn` in **one** SQLite transaction; on commit it
    bumps `revision`, reloads the touched slices, and emits
    `changed(revision, kinds)`. It is the **only** write path.
  - `store.apply_pull(items, server_revision)` — idempotent upsert keyed by
    `(id, version)`; never `clearAll`.
- Views call `store.subscribe(kinds, cb)`. `cb` gets `(snapshot, revision)`.
  Each view stores `last_seen_revision`; on show/focus, if
  `store.revision > last_seen_revision` it re-renders itself — **self-healing,
  no missed pulse possible.**
- Dashboard KPIs are a method **on the store** over the same snapshot ⇒
  Dashboard ≠ Vehicles becomes structurally impossible.
- `EventBus.data_refreshed` (the level-less pulse) is **deleted**. Realtime
  events call `store.mark_stale(kinds)` → triggers a scoped pull → normal
  `changed`.

### P3 — Boundary-aware clock (kills the time gap with zero polling)
- New `desktop/app/state/boundary_clock.py`: after each snapshot reload it
  computes `next_boundary = shared.fleet_status_reference.next_boundary(...)`
  (earliest future reservation.start / reservation.end / maintenance.start /
  maintenance.effective_end that is `> now`). Arms **one**
  `QTimer.singleShot(next_boundary - now)`. On fire →
  `store.recompute_effective()` (re-bucket in memory, **no DB, no network**) →
  `changed` → re-arm.
- Cost: exactly one timer, firing only at real boundaries (minutes–hours
  apart). Never per-vehicle, never per-widget, never 1 s.
- Mobile equivalent: a `tickerFlow` = `flow { while(true){ delay(untilNext); emit(Unit) } }`
  folded into `combine(vehiclesFlow, reservationsFlow, maintenanceFlow, tickerFlow) { … recompute locally }`.

### P4 — Versioned sync (server change-log)
- Backend migration: `domain_revision BIGINT` — a single sequence bumped **in
  the same transaction** as any write to vehicle / reservation / maintenance /
  client (a `bump_revision()` call in each service, or a DB trigger).
- `GET /sync/pull?since_revision=<n>` → `{revision, changes:[{table, op, row, version}]}`.
  Row-level upserts/deletes, ordered, gap-free.
- WS event payload gains `{revision}`. Client compares to its
  `synced_revision`; if `event.revision > local + N` it knows it missed events
  and pulls the gap. **A missed update becomes impossible.**
- Apply is idempotent + version-guarded: a pulled row older than a pending
  local optimistic write is rejected per-row.
- Keep `updated_at >= since` as a transitional fallback for one release.

### P5 — Transactional events
- Rule, enforced by making `store.mutate()` / the service layer the only write
  path: **the change signal is emitted after commit, or not at all.** Delete
  every scattered `commit(); emit()` pair on desktop. On the backend, the
  `event_broadcaster.broadcast_event(...)` call moves to *after* the DB
  transaction commits (some already are; audit and fix the rest).

### P6 — Mobile parity
- Replace `clearAll()+insert` with Room `@Upsert` + `deleteByIdNotIn(keepIds)`
  → one coherent emission, no flicker/zero-flash.
- Move metrics + notifications into Room (process-death-safe, shared).
- `combine(...)` with the boundary ticker + the Kotlin port of the reference
  calculator.

### Target state graph

```
              PostgreSQL  +  domain_revision (monotonic)
                     │
        GET /sync/pull?since_revision=N  →  {revision, ordered row changes}
        WS event {type, entityId, revision}
                     │
     ┌───────────────┴────────────────┐
     ▼                                ▼
 Desktop SQLite                  Mobile Room
     │  store.apply_pull(items, rev)      │  upsert + deleteByIdNotIn
     ▼                                ▼
 DomainStore(snapshot, revision)   Repository Flows
     │  changed(rev, kinds)              │
     │  + BoundaryClock singleShot       │  + tickerFlow(nextBoundary)
     ▼                                ▼
 Views subscribe; re-heal if          combine{ recompute effective
   store.revision > last_seen            locally from raw rows }
     ▼                                ▼
        LOCAL derivation via shared/fleet_status_reference semantics
     └───────────────┬────────────────┘
                     ▼
              SAME VISIBLE TRUTH
```

---

## 5. IMPLEMENTATION PLAN — 6 increments, each test-gated & revertible

> **Increment 0 (recommended, not yet done):** commit the current 94-file tree
> to a branch as a known-good base (it passes its suites per
> `FINAL_RELEASE_INTEGRATION_GATE.md`). Committing is non-destructive and is
> *not* on the forbidden list. Do this before Increment 2 touches UI wiring.

| Inc | Title | Files | Risk | Proof gate |
|-----|-------|-------|------|------------|
| **1** ✅ | **Cross-runtime parity net** — normative spec + vectors + backend & desktop parity tests | `shared/fleet_status_reference.py`, `shared/fleet_status_cases.json`, `backend/tests/test_fleet_status_crossruntime.py`, `desktop/tests/test_fleet_status_crossruntime.py` | none (additive) | **DONE** — backend 14/14, desktop 14/14, reference self-check pass (§17) |
| 2 ✅ | **Desktop `DomainStore`** — one canonical snapshot + monotonic revision + isolated subscribers + transactional `mutate()`; Vehicles & Dashboard render from the snapshot; hand fan-out replaced by a store subscriber; self-heal on tab visit | `desktop/app/state/domain_store.py` (new), `main_window.py`, `tests/conftest.py` | — | **DONE** — backend 115, desktop 177 (+16), Increment-1 parity still 14/14 each. See `FINAL_INCREMENT_2_DOMAINSTORE_FORENSIC.md`. Verdict: **PARTIAL** — L1 (time-boundary) deferred to Inc 3. |
| 3 ✅ | **Desktop `BoundaryClock`** — one single-shot timer at `next_boundary`, no polling; `DomainStore.recompute_effective(now)` re-derives in memory (no SQLite, no network) and publishes only on real change; `fleet_status.py` refactored to one pure core shared by build + recompute | `desktop/app/state/boundary_clock.py` (new), `domain_store.py`, `fleet_status.py`, `main_window.py` | — | **DONE** — 12 clock unit tests + 6 temporal incl. a real-clock/real-QTimer forensic proof (RENTED→AVAILABLE with zero user action, rev N→N+1, 1 notification). See `FINAL_INCREMENT_3_BOUNDARYCLOCK_FORENSIC.md`. |
| 4 ✅ | **Mobile `BoundaryTicker` + Kotlin `FleetStatus` port + midnight rollover (desktop + mobile)** — mobile local effective-status re-derivation from Room intervals; `next_boundary_rows(include_midnight)`; `compute_overview_rows` (now-aware) | `mobile/.../data/fleet/*` (new), `FleetRepository.kt`, `Entities.kt`, `Models.kt`; `desktop/.../fleet_status.py`, `dashboard_cache.py`, `domain_store.py`, `boundary_clock.py` | — | **DONE** — mobile 41 (+15: 8 ticker, 1 parity/14 vectors, 6 temporal incl. real-clock forensic + midnight); desktop 15 cross-client + 2 midnight; backend 115. See `FINAL_INCREMENT_4_MOBILE_MIDNIGHT_FORENSIC.md`. Verdict: mobile temporal + midnight **PROVEN**; whole-product still NOT 100% LIVE (needs Inc 5 versioned sync + live rig). |
| 5 | **Versioned sync** — backend `domain_revision` + `/sync/pull?since_revision=` + WS `{revision}`; idempotent version-guarded apply on desktop + mobile; delete `clearAll()`; close mobile sparse-cache gap | alembic migration; `sync_service.py`, `event_broadcaster.py`; `sync/engine.py`; mobile `FleetRepository` `@Upsert`/`deleteByIdNotIn` | medium | `test_domain_revision.py`; `test_apply_pull_idempotent.py`; mobile `FleetRepositoryUpsertTest` |
| 6 | Desktop L2/L3 cleanup — Reservations/Maintenance render from snapshot, delete dead `entity_changed`, migrate 7 mutation handlers to `store.mutate()` | `desktop/app/ui/*` | low | existing suites stay green |

Each increment: **write → run its gate + the layer's full suite → record result
in this file → only then delete the superseded code (Phase 18).**

---

## 6. STATE OWNERSHIP (target)

| Layer | Sole owner of in-memory truth | Views |
|---|---|---|
| Backend | PostgreSQL rows + `domain_revision` | stateless request handlers |
| Desktop | `DomainStore.snapshot` + `DomainStore.revision` | subscribers; hold only `last_seen_revision` |
| Mobile | Room DB | `Flow`→`StateFlow`; Compose reads only |

No widget, ViewModel, or `MutableStateFlow` holds business state that is not a
projection of the owner above it.

---

## 7. DASHBOARD TRUTH

- **One query path**: `DomainStore.dashboard_overview()` (desktop) /
  `DashboardService` → `compute_fleet_counts` (backend), both over the same
  snapshot/rows that feed the Vehicles list.
- **Canonical KPI definitions** (unchanged, now centrally enforced):
  - `total_vehicles` = vehicles NOT IN (SOLD, INACTIVE). Counts **vehicles**,
    never a reservation/maintenance JOIN.
  - `available + reserved + rented + maintenance == total_vehicles` (mutually
    exclusive; asserted by every parity vector).
  - `active_maintenance_tickets == maintenance` (one maintenance number).
  - Revenue(period) = `SUM(total_price) WHERE status IN (ACTIVE, COMPLETED) AND start_datetime ∈ [period_start, period_end)`, Africa/Casablanca midnight, week starts Monday.
- Increment 1 proves the count identity holds on 14 scenarios for backend and
  desktop today.

---

## 8. DESKTOP LIVE STATE — see P2 + P3. Net effect for the user

| Action | Before | After |
|---|---|---|
| Create/edit/cancel anything | 5 table reloads + server round-trip; sibling tab may miss it | `store.mutate` → one transaction → `changed(rev)` → every visible view updates from the new snapshot; hidden views re-heal on show |
| Reservation ends at 18:00, nobody clicks | stale until next action (up to ∞) | `BoundaryClock` fires at 18:00:00 → vehicle flips AVAILABLE everywhere, no network |
| A page's refresh throws | that page frozen silently | other views unaffected; the frozen page re-heals on next `changed` or on show |

---

## 9. MOBILE LIVE STATE — see P1 + P6

Room stays the reactive core (it already works). Fixes: no full-wipe refresh,
local effective-status derivation (offline-correct), boundary ticker for time
transitions, Room-backed metrics/notifications, Kotlin parity test.

---

## 10. AUTHENTICATION / SESSION

Current state (from `FINAL_TRUTH_RESPONSIVITY_FORENSIC_REPORT.md` +
`car-rental-mobile-session-fix`): the mobile repeated-login bug is fixed —
only `{401,403}` clear the session; timeout/5xx/429 never do; Splash-gated
restore; `SessionRestoreFlowTest` 9/9. **One residual, out of scope for the
live-state work but tracked here:** `TokenAuthenticator` clears tokens on a
mid-session refresh rejection but does not update
`AuthRepository._currentUserSession`, so the UI does not bounce to login until
next app start. Fix = emit the cleared session into the StateFlow. Desktop:
`api_client._request` retries on read-timeout with a widened timeout (cold-start
tolerant); token refresh propagates to `RealtimeEventsClient.update_token`.
Acceptance criteria for §Phase 15 are otherwise met by the existing tests.

---

## 11. SYNC / REALTIME — see P4

Timestamp pull → revision pull; notification-only WS events → WS events carrying
`{revision}` so clients detect and close gaps; idempotent version-guarded apply.

---

## 12. TIME BOUNDARIES — see P3

Centralised `next_boundary()` (already implemented in
`shared/fleet_status_reference.py`, tested via the reference self-check). One
timer per client. No polling, no per-entity timers.

---

## 13. BUTTON AUDIT (Phase 14) — method, run during Increment 2

For every mutating control, assert the chain in a test:
`click → service/store.mutate → single commit → revision bump → changed emitted
→ every subscribed view reflects it → no exception swallowed → correct error
class on failure`. Candidates enumerated from `main_window.py` signal wiring
(lines 321–347): add/edit/delete vehicle, maintenance request/save, reservation
create/activate/complete/cancel, client create/edit, document upload, logout,
manual refresh, language/theme. Each becomes a row in a
`test_button_convergence.py` matrix.

---

## 14. FAILURE RECOVERY (Phase 13) — matrix, built in Increments 2/4/5

DB failure → `store.mutate` rolls back, **no** `changed`, dialog stays open.
Network timeout / 5xx / 429 → session retained, offline banner, pull retried.
401/403 → session cleared, route to login (desktop + mobile).
Stale / duplicate / out-of-order event → revision comparison ignores or
gap-fills; idempotent apply makes duplicates no-ops.
Process death (mobile) → Room + DataStore rehydrate; `synced_revision`
persisted.
Clock jump / sleep-resume → on resume, `BoundaryClock` recomputes from
`now`; next pull reconciles.

---

## 15. PERFORMANCE (Phase 17) — bounded by design

| Metric | Before | After (target) |
|---|---|---|
| Desktop refreshes per mutation | 5 full re-queries + dashboard recompute + HTTP | 1 transaction + 1 in-memory snapshot reload of touched slices |
| Desktop timers | 30 s sync + 5 s realtime poll + 250 ms debounce | same + **1** boundary singleShot |
| Mobile emissions per refresh | 2 (empty, then full) | 1 |
| Poll cadence | unchanged (WS primary, poll is fallback only) | unchanged |

No "refresh everything every second" anywhere.

---

## 16. DELETED OLD ARCHITECTURE (Phase 18) — only after proof

Scheduled for removal, each after its replacing increment is green:
- `EventBus.data_refreshed` + `_on_global_data_refreshed` refresh storm (Inc 2)
- dead `EventBus.entity_changed` signal (Inc 2 — never emitted)
- per-widget one-shot `session.query` state copies (Inc 2)
- `clearAll()+insert` mobile refresh (Inc 5)
- `updated_at >= since` pull path (Inc 4, after one transitional release)
- scattered `commit(); emit()` pairs in `main_window.py` (Inc 2)

Nothing is deleted in this pass.

---

## 17. TESTS — status

### Increment 1 (this pass) — GREEN

```
shared/fleet_status_reference.py   reference self-check ............ ALL PASS (14/14 vectors)
backend/tests/test_fleet_status_crossruntime.py ................... 14 passed
desktop/tests/test_fleet_status_crossruntime.py ................... 14 passed
```

**Finding:** the backend and desktop effective-status derivations **currently
agree** with the normative spec on all 14 vectors (including the half-open
boundary cases, open-ended maintenance, maintenance-wins, SOLD/INACTIVE
exclusion, and the mixed-fleet sum identity). They were **not** drifting today —
but nothing prevented it. There is now a test that fails the moment any of the
three runtimes diverges.

**Not yet verified:** mobile (Kotlin) parity — needs `gradlew testDebugUnitTest`
and the Kotlin port (Increment 6).

### Full regression (this pass) — GREEN

```
backend  full suite ....... 115 passed  (101 before + 14 new cross-runtime)   12.96s
desktop  full suite ....... 161 passed  (147 before + 14 new cross-runtime)  174.52s
```

Increment 1 adds only additive test files + `shared/` spec modules; **no
existing source file was modified**, so the pre-existing 101/147 are unchanged
and the deltas are exactly the 14 new parametrised parity cases per layer.

### Planned (Increments 2–6)
`test_domain_store_convergence.py`, `test_boundary_clock.py`,
`test_domain_revision.py`, `test_apply_pull_idempotent.py`,
`test_button_convergence.py`, `FleetStatusParityTest.kt`,
`FleetRepositoryUpsertTest.kt`, cross-client convergence harness.

---

## 18. BUILD ARTIFACTS

Not rebuilt in this pass (Increment 1 changes no shipped source — it adds
`shared/` spec modules + test files only). Current artifacts unchanged:
- Windows EXE `3dc5f134…` / ZIP `99fec183…` (2026-08-29 19:17) — still current
  for the desktop app; contains all desktop fixes through 19:09.
- Debug APK `71dc95b7…` (2026-08-29 22:31).
Increments 2, 3, 5 will require a desktop rebuild; Increment 6 an APK rebuild.

---

## 19. REMAINING RISKS

1. **The whole verified state (incl. Increment 1) is uncommitted** on `df9b96d`;
   12 commits unpushed. Increment 0 (checkpoint commit) should precede Inc 2.
2. Increment 2 rewires every desktop page — highest-risk step; must land behind
   the `CAR_RENTAL_DOMAIN_STORE` flag with both paths tested before the old one
   is deleted.
3. Increment 4 is a schema migration — must be exercised only against throwaway
   DBs (no production PostgreSQL access from here anyway).
4. No Android device / emulator and no production backend in this environment ⇒
   cross-client convergence and on-device time-boundary behaviour cannot be
   proven here, only unit/integration-tested.
5. Backend `event_broadcaster` ordering vs commit not yet fully audited (Inc 5).
6. `datetime` handling is centralised on desktop (`parse_datetime_utc`) and
   backend, but mobile date parsing (`FleetRepository.formatIsoDate`) is
   separate — fold into the Kotlin reference port (Inc 6).

---

## 20. NOT VERIFIED (cannot be, from this environment)

- On-device Android: live convergence, time-boundary flip, process-death restore
- Two desktop instances against one deployed backend (cross-client)
- Windows EXE runtime (no Windows host)
- Production PostgreSQL migration for `domain_revision`
- Real WebSocket reconnect / gap-fill against `fly.dev`
- Signed release APK (keystore is CI-only)

---

## ROOT-CAUSE LEDGER

| ROOT CAUSE | CATEGORY | LOCATION | PROOF | FIX | TEST | STATUS |
|---|---|---|---|---|---|---|
| No single ordered observable stream of committed domain state; state is copied and re-synced by version-less pulses | architecture / state ownership | `desktop/app/services/event_bus.py`, `main_window._on_global_data_refreshed`, mobile `FleetRepository.refreshX` | §1 facts A–F with code refs; `entity_changed` never emitted; `_on_sync_finished` skips emit on quiet sync | P2 `DomainStore` + P4 versioned sync | `test_domain_store_convergence.py`, `test_domain_revision.py` | **DESIGNED — Inc 2/4** |
| Three independent effective-status implementations, nothing enforcing equality | correctness / duplication | `backend/app/services/fleet_status.py`, `desktop/app/utils/fleet_status.py`, mobile `FleetRepository.mapVehicleDtoToDomain` | 3 code paths; zero equality tests pre-Inc-1 | P1 normative spec + per-runtime parity tests | `test_fleet_status_crossruntime.py` (be+desktop), `FleetStatusParityTest.kt` | **be+desktop DONE; mobile Inc 6** |
| Wall-clock time changes truth but emits no event | correctness / liveness | `compute_fleet_sets` callers; `main_window._on_sync_finished` conditional emit | fact D | P3 `BoundaryClock` + `next_boundary()` | `test_boundary_clock.py`; reference self-check covers `next_boundary` | **spec fn DONE; wiring Inc 3/6** |
| Timestamp-based pull can miss/re-pull rows; no global revision | correctness / sync | `backend/app/services/sync_service.py` `pull_changes` | fact E | P4 `domain_revision` + `since_revision` | `test_domain_revision.py` | **DESIGNED — Inc 4** |
| Mobile full-wipe refresh → flicker + possible clobber of local writes | correctness / UX | `mobile/.../FleetRepository.refreshVehicles` etc. | fact F | P6 `@Upsert` + `deleteByIdNotIn` | `FleetRepositoryUpsertTest.kt` | **DESIGNED — Inc 5/6** |
| Widgets own state; a swallowed refresh exception freezes a tab | robustness | `main_window._on_global_data_refreshed` try/except | fact C | P2 subscribers + re-heal on show | `test_domain_store_convergence.py` (throwing-subscriber case) | **DESIGNED — Inc 2** |
| Change signal can precede commit in some paths | correctness | scattered `commit(); emit()` in `main_window.py`; backend broadcast vs txn | P5 audit | P5 single write path emits post-commit | `test_button_convergence.py` (DB-failure row) | **DESIGNED — Inc 2/5** |

---

## FINAL VERDICT

**NOT READY — `TRUE 100% LIVE SHOWROOM` cannot be declared.**

- The fundamental architectural limitation is identified with code evidence
  (§1), and it is **solvable** — the target architecture (§4) removes it.
- Increment 1 (the cross-runtime parity net) is **implemented and green**:
  backend 14/14, desktop 14/14 against one normative spec.
- Increments 2–6 are fully specified with per-increment test gates. They are
  real work (desktop UI rewire, backend migration, mobile changes) and must
  land one at a time.
- Final acceptance (`PASS`) additionally requires on-device + deployed-backend +
  two-desktop verification that this environment cannot provide.

Next action: **Increment 0** (checkpoint-commit the current tree to a branch),
then **Increment 2** (`DomainStore`).
