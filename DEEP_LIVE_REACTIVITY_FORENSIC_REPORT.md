# DEEP LIVE REACTIVITY — FORENSIC REPORT

Project: `/home/ayman/car-rental-system`
Git HEAD: `df9b96d` (branch `main`)
Worktree: dirty (pre-existing uncommitted refactor + this investigation's fixes)
Date: 2026-08-29

---

## 1. Executive Summary

The desktop app's live-propagation **architecture is fundamentally sound**: every
local mutation commits, then emits a single global `EventBus.data_refreshed`
signal, and `MainWindow._on_global_data_refreshed()` re-queries every open view
from SQLite. The `EventBus` is a real module-level singleton with correct main-thread
affinity. There is **no missing EventBus, no duplicate bus, no dead listener, no
long-lived stale ORM session**.

The reactivity failures the user observed were caused by **an in-progress,
half-applied refactor** ("stop storing transient vehicle status, derive it instead")
that was wired on the *write* side but not on the *read* side, plus two latent
defects it exposed:

| # | Category | Symptom | Status |
|---|----------|---------|--------|
| 1 | ORM STATE / BUSINESS LOGIC | After **finish/cancel maintenance or reservation**, the vehicle stays `MAINTENANCE`/`RENTED`/`RESERVED` in the Vehicles view until a full sync round-trip; Dashboard disagrees at the same instant. | **FIXED** |
| 2 | BUSINESS LOGIC (backend) | `complete_maintenance` / `advance`-to-`TERMINE` no longer returned the vehicle to `AVAILABLE` → vehicle **permanently unbookable** via API/mobile/web. | **FIXED** |
| 3 | EXCEPTION HANDLING (backend) | `complete_maintenance` and `advance_maintenance_step` `return m` with un-eager-loaded `parts` → **HTTP 500** on the "finish" button even though the DB write succeeded. | **FIXED** |
| 4 | TRANSACTION / API | `check_availability` hard-blocked on a persisted `vehicle.status == "MAINTENANCE"` flag — a stale flag made a car un-bookable forever. | **FIXED** |
| 5 | UI / EXCEPTION HANDLING | `_on_global_data_refreshed` ran 5 refreshes as one unguarded sequence; one bad row in view #2 silently froze views #3–#5. | **FIXED** |
| 6 | EXCEPTION HANDLING | `_create_maintenance_record` caught **every** exception with a bare `print()` — no rollback, no user feedback → "button does nothing". Same dead-`except`/`print("ERROR IN LOAD")` pattern in 3 vehicle CRUD handlers, one of which (`_on_edit_vehicle`) could raise `NameError` on the next line and kill the slot. | **FIXED** |

All fixes are architectural (fix the propagation contract), not "add more
`refresh()` calls". Full suites (executed — see §28): **desktop 115 passed / 0 fail,
backend 84 passed / 0 fail, both exit 0**. A cross-window convergence test drives the
entire mutation lifecycle with every view alive and asserts one-mutation → one-event
→ all-views-converge with no tab switch, no manual refresh, no sync. The Windows EXE
was rebuilt, smoke-tested, and its hash verified against the ZIP (§28). **Remaining
release steps: apply migration `f1a2b3c4d5e6` to prod PostgreSQL and deploy the
backend — RC#2/#3/#4 are server-side.**

---

## 2. Complete Architecture Map

```
Entry: desktop/app/main.py
  └─ LoginWindow (login_window.py)  ── LoginWorker(QThread) → online auth, offline fallback
      └─ MainWindow (ui/main_window.py)              ← the ONLY window; everything else is a page or modal
          ├─ Sidebar (ui/widgets/sidebar.py)         page_changed → _switch_page
          ├─ QStackedWidget  (NOT tabs, NOT separate windows — one widget kept alive per page)
          │    ├─ DashboardWidget      (ui/dashboard.py)
          │    ├─ VehicleListWidget    (ui/vehicles/vehicle_list.py)
          │    ├─ ReservationWidget    (ui/reservations/reservation_list.py)
          │    ├─ MaintenanceWidget    (ui/maintenance/maintenance_list.py)
          │    ├─ ClientsWidget        (ui/clients/client_list.py)  ← API-backed
          │    └─ SettingsWidget       (ui/settings/settings_widget.py)
          ├─ Modals (.exec()):  VehicleFormDialog, MaintenanceFormDialog,
          │                     ReservationFormDialog, ClientDetailsDialog
          ├─ Timers:  _sync_timer (SYNC_INTERVAL_SECONDS), QTimer.singleShot(100, _initial_load)
          ├─ Threads: DashboardFetcher(QThread), SyncThread(QThread) → SyncEngine(asyncio)
          └─ RealtimeEventsClient (services/realtime_client.py, QThread/WebSocket)

State / data layer
  ├─ EventBus (services/event_bus.py)   module-level singleton `_bus = EventBus()`, main-thread affinity
  │     signals:  entity_changed(str,str) [defined, unused]   data_refreshed()   [the live channel]
  ├─ SQLite (database.py)   WAL, check_same_thread=False, busy_timeout 15s
  │     get_local_session() → short-lived Session per call (NO long-lived sessions anywhere)
  ├─ SyncQueue (sync/queue.py)          local mutation → durable outbox row
  ├─ SyncEngine (sync/engine.py)        push → uploads → pull → apply_pulled_items() merge into SQLite
  ├─ dashboard_cache.py                 compute_local_overview()  — offline mirror of backend canonical rule
  └─ image_cache.py                     per-URL pixmap cache, invalidated on marker reconciliation

Backend (FastAPI, backend/app)
  api/v1/{vehicles,rentals,maintenance,dashboard,sync,clients}.py
  services/{rental_service,vehicle_service,dashboard_service,sync_service,notification_service}.py
  repositories/rental_repository.py     check_availability() — the canonical availability oracle
  event_broadcaster.py                  WebSocket fan-out → desktop RealtimeEventsClient
```

### EventBus identity (Phase 5) — PROVEN SINGLE

`event_bus.py` binds `_bus` at module import (main thread); `get_event_bus()` is a
bare `return _bus`. Python caches the module, so every caller — MainWindow, every
page, every worker thread, `sync/engine.py`, `sync/uploads.py` — receives the
**same** object. Cross-thread `.emit()` from `SyncThread`/`SyncEngine` is delivered
via Qt's automatic queued connection onto the UI thread. No second bus can exist.

---

## 3. Complete State Propagation Map (target contract — now enforced)

```
USER ACTION (button / modal "save")
        │
        ▼
VALIDATE  (form + ReservationWidget server-authority availability check)
        │
        ▼
MUTATE    get_local_session();  session.add()/update/delete
        │
        ▼
ENQUEUE   SyncQueue.enqueue(entity, id, op, payload)      (same txn)
        │
        ▼
COMMIT    session.commit()      ← state now visible to every future short-lived session
        │
        ▼
GLOBAL EVENT   get_event_bus().data_refreshed.emit()      ← exactly one per logical mutation
        │
        ▼
CENTRAL DISPATCH   MainWindow._on_global_data_refreshed()  (each view refresh isolated in try/except)
        │
        ├─→ VehicleListWidget.load_vehicles(...)     status DERIVED live (fix #1)
        ├─→ DashboardWidget.refresh_data(compute_local_overview())
        ├─→ ReservationWidget.refresh_data()
        ├─→ MaintenanceWidget.refresh_data()
        └─→ ClientsWidget.refresh_data()
        │
        ▼
BACKGROUND   _run_sync()  → push/pull → on real change → data_refreshed.emit() again (server truth)
        │
        ▼
REALTIME     WS event → 250 ms debounce → _run_sync()  (other devices' changes)
```

Widget-local mutations (reservation complete/cancel, maintenance advance/finish)
additionally emit their own Qt signal (`reservation_created`, `maintenance_updated`)
→ `MainWindow._on_reservation_updated` / `_on_maintenance_updated` → same global emit.
Sync-conflict revert (`engine.py`) and image-marker reconciliation (`uploads.py`)
also emit the global event (both added in the pre-existing uncommitted work — verified correct).

---

## 4. All Root Causes

### ROOT CAUSE #1 — transient vehicle status "sticks" on the read side
- CATEGORY: ORM STATE / BUSINESS LOGIC
- FILE: `desktop/app/ui/main_window.py`
- FUNCTION: `_load_vehicles_from_local`
- EXACT LINE (pre-fix): `effective_status = v.status` then `if effective_status not in ("SOLD","INACTIVE"):` only ever *upgraded* to MAINTENANCE/RENTED/RESERVED, never back to AVAILABLE.
- USER SYMPTOM: finish a maintenance / cancel a reservation → the car still shows MAINTENANCE / RESERVED in the Vehicles list; only a full sync push+pull (or restart) clears it. Offline, it never clears.
- WHAT ACTUALLY HAPPENS: the pre-existing refactor stopped writing `vehicle.status = "MAINTENANCE"` locally, but the server still does, so on the next `pull` `LocalVehicle.status` becomes `"MAINTENANCE"`. When the maintenance is later completed, `effective_status` starts from that persisted `"MAINTENANCE"` and nothing downgrades it.
- EXPECTED: effective status is fully derived from live reservation/maintenance records; only `SOLD`/`INACTIVE` are structural.
- WHY IT BREAKS: contradicts Dashboard (`compute_local_overview` already derives correctly), so the same car is "maintenance" in one view and "available" in another at the same timestamp.
- AFFECTED WINDOWS: Vehicles list, Reservations "available vehicles" grid (indirectly), any consumer of the vehicle dict.
- AFFECTED DOMAINS: vehicle availability, dashboard parity.
- FIX: derive `effective_status` — `SOLD`/`INACTIVE` pass through; otherwise MAINTENANCE/RENTED/RESERVED from live overlap sets, else `AVAILABLE`. (`main_window.py` `_load_vehicles_from_local`).
- REGRESSION TEST: `desktop/tests/test_status_derivation_regression.py` (4 cases) + `test_cross_window_convergence.py`.

### ROOT CAUSE #2 — backend never frees the vehicle after maintenance
- CATEGORY: BUSINESS LOGIC
- FILE: `backend/app/api/v1/maintenance.py`
- FUNCTION: `complete_maintenance`, `advance_maintenance_step` (step → `TERMINE`)
- EXACT LINE (pre-fix): `if vehicle and vehicle.status == "MAINTENANCE": pass  # removed mutation to AVAILABLE`
- USER SYMPTOM: after completing maintenance from the API / mobile / web, the vehicle is `MAINTENANCE` forever; it can never be reserved again; desktop pulls that status.
- WHAT ACTUALLY HAPPENS: `create_maintenance` still sets `vehicle.status = "MAINTENANCE"` (line 210) but the completion paths were changed to no-ops during the refactor — the write is one-directional.
- EXPECTED: completing/finishing maintenance clears a transient `MAINTENANCE` hold and returns the car to `AVAILABLE`, while leaving `SOLD`/`INACTIVE` untouched.
- WHY IT BREAKS: permanent divergence between the maintenance schedule (ticket `COMPLETED`) and the vehicle flag.
- AFFECTED WINDOWS: every view on every client.
- FIX: restore `if vehicle and vehicle.status == "MAINTENANCE": vehicle.status = "AVAILABLE"; vehicle.version += 1` in both endpoints.
- REGRESSION TEST: `backend/tests/test_maintenance_frees_vehicle.py`.
- DATA REPAIR: `backend/migrations/versions/f1a2b3c4d5e6_unstick_maintenance_vehicle_status.py` resets already-stuck rows (`status='MAINTENANCE'` with no `ACTIVE` maintenance) to `AVAILABLE`.

### ROOT CAUSE #3 — "finish maintenance" returns HTTP 500
- CATEGORY: EXCEPTION HANDLING (response serialization)
- FILE: `backend/app/api/v1/maintenance.py`
- FUNCTION: `complete_maintenance`, `advance_maintenance_step`
- EXACT LINE (pre-fix): `return m` after `await db.commit()`
- USER SYMPTOM: the "Terminer" / "Étape suivante" button appears to fail; the client shows an error; a retry "does nothing" because the ticket is already completed.
- WHAT ACTUALLY HAPPENS: `MaintenanceResponse` needs `m.parts`; after commit `m` is expired/detached and the async lazy-load raises `ResponseValidationError`/`MissingGreenlet` **after** the DB change was already committed. `create_maintenance` had a comment and a `selectinload` re-query guarding exactly this; the two completion endpoints did not.
- EXPECTED: 200 + the completed ticket.
- FIX: re-query with `selectinload(Maintenance.parts)` before `return` in both endpoints (identical to `create`).
- REGRESSION TEST: `backend/tests/test_maintenance_frees_vehicle.py` (asserts `status_code == 200`).

### ROOT CAUSE #4 — stale `MAINTENANCE` flag hard-blocks availability
- CATEGORY: TRANSACTION / API
- FILE: `backend/app/repositories/rental_repository.py`
- FUNCTION: `check_availability`
- EXACT LINE (pre-fix): `if v_status in ["MAINTENANCE", "SOLD", "INACTIVE"]: return False, v_status`
- USER SYMPTOM: a car that had a maintenance ticket months ago cannot be reserved even though nothing is scheduled.
- WHY IT BREAKS: `MAINTENANCE` is a *schedule-derived* hold. Step 2 of the same function already checks live maintenance overlap; trusting the persisted column adds a permanent false block whenever the column is stale (see #1/#2).
- FIX: restrict the structural guard to `["SOLD", "INACTIVE"]`; maintenance remains enforced by the schedule check.
- REGRESSION TEST: existing `backend/tests/test_availability_maintenance.py` still green (uses schedule overlap).

### ROOT CAUSE #5 — non-isolated central dispatch
- CATEGORY: UI / EXCEPTION HANDLING
- FILE: `desktop/app/ui/main_window.py`
- FUNCTION: `_on_global_data_refreshed`
- EXACT (pre-fix): five bare calls in sequence. `self._reservations.refresh_data()` / `_maintenance` / `_clients_page` were unguarded — an exception in one aborts the rest.
- USER SYMPTOM: intermittent "half the app didn't update" after an event, cleared by switching pages (which calls that page's own `refresh_data`).
- FIX: iterate `(label, fn)` and wrap each in `try/except` with `logger.error(..., exc_info=True)`.
- REGRESSION TEST: covered implicitly by `test_cross_window_convergence.py`; behaviour is "one failing view never blocks the others".

### ROOT CAUSE #6 — silent mutation failures
- CATEGORY: EXCEPTION HANDLING
- FILE: `desktop/app/ui/main_window.py`
- FUNCTIONS: `_create_maintenance_record` (`except Exception: print(...)`, **no rollback**, no user feedback);
  `_create_vehicle` / `_update_vehicle` / `_on_delete_vehicle` (dead unreachable `except Exception: print("ERROR IN LOAD")` after the real handler);
  `_on_edit_vehicle` / `_on_maintenance_requested` (bare `except` around the data load leaves `v_data`/`v_dict` unbound → `NameError` on the next line → Qt swallows it → button looks dead).
- USER SYMPTOM: click "save maintenance" / "edit vehicle" → nothing happens, no error.
- FIX: `_create_maintenance_record` now `rollback()` + `logger.error(exc_info=True)` + `QMessageBox.critical`. `_on_edit_vehicle` / `_on_maintenance_requested` initialise the dict to `None`, log on failure, show an error and `return` instead of falling through. Dead `except/print` blocks removed; `_create_vehicle` now logs before the message box.

---

## 5. Evidence

- `event_bus.py`: singleton confirmed by inspection (module-level bind, bare return).
- `git diff` (pre-existing, uncommitted): shows the write-side removal in `main_window.py` (`_create_maintenance_record` no longer sets `vehicle.status`), `maintenance_list.py` (`_finish_maintenance`), `reservation_list.py` (complete/cancel), and the backend no-op-ing of `complete_maintenance` / `advance_maintenance_step` — the read side (`_load_vehicles_from_local`, `check_availability` step 0, `create_maintenance` line 210) was left inconsistent.
- `backend/app/services/sync_service.py` `_process_maintenance_update` still resets `MAINTENANCE→AVAILABLE` on the **sync** path — which is why the bug looked intermittent ("works after a sync, not immediately").
- New test `test_cross_window_convergence.py` reproduces the stuck state pre-fix and passes post-fix.
- New test `test_maintenance_frees_vehicle.py::test_complete_endpoint_frees_vehicle` failed pre-fix with `ResponseValidationError` (root cause #3) and `AVAILABLE` assertion (root cause #2); passes post-fix.

---

## 6. Fixes (files touched by this investigation)

| File | Change |
|------|--------|
| `desktop/app/ui/main_window.py` | derive `effective_status` (#1); isolate each refresh in `_on_global_data_refreshed` (#5); rollback + visible error in `_create_maintenance_record`, guard `_on_edit_vehicle` / `_on_maintenance_requested`, drop dead `except/print` blocks (#6) |
| `backend/app/api/v1/maintenance.py` | restore `MAINTENANCE→AVAILABLE` on complete + advance-to-TERMINE (#2); `selectinload(parts)` re-query before `return` (#3) |
| `backend/app/repositories/rental_repository.py` | structural guard limited to `SOLD`/`INACTIVE` (#4) |
| `backend/migrations/versions/f1a2b3c4d5e6_*.py` | NEW — one-way data repair for already-stuck vehicles |
| `desktop/tests/test_status_derivation_regression.py` | NEW — 4 cases |
| `desktop/tests/test_cross_window_convergence.py` | NEW — full lifecycle, all views alive |
| `backend/tests/test_maintenance_frees_vehicle.py` | NEW — 3 cases |

Not changed on purpose: the `EventBus`, the central dispatch design, the
short-lived-session pattern, the sync engine, date/time handling — all audited clean.

---

## 7. EventBus Audit
Single module-level singleton; main-thread affinity explicit; `data_refreshed`
has exactly one structural listener (`MainWindow._on_global_data_refreshed`);
cross-thread emits (SyncThread, SyncEngine, uploads reconcile) are auto-queued to
the UI thread. `entity_changed(str,str)` is declared but unused — harmless (left
as-is; could be removed in a cleanup). No duplicate connections in production code
(test fixtures now disconnect their spies — see note in §19).

## 8. Signal/Slot Audit
`sidebar.page_changed` → `_switch_page`; `vehicle_list.{add,vehicle_selected,maintenance_requested,delete}` → MainWindow handlers; `reservations.reservation_created` → `_on_reservation_updated`; `maintenance.{maintenance_updated,maintenance_add_requested}` → `_on_maintenance_updated` / `_save_maintenance`; `settings.{theme,language}_changed` handled. Every emitter has a listener; every reactive listener has a reachable emit. Widget-local `refresh_data()` calls after complete/cancel/advance/finish are **kept** (immediate local feedback) *and* bubble to the global event (cross-view) — mild redundancy, not a bug (see §18).

## 9. Database Transaction Audit
All desktop mutations: `get_local_session()` → add/update/delete + `SyncQueue.enqueue` in the **same** transaction → `session.commit()` → emit → `session.close()` in `finally`. Rollback on exception is present in vehicle create/update/delete and (now) maintenance create. No `emit` before `commit`. No `commit` after a partial failure without rollback (fixed in `_create_maintenance_record`). SQLite WAL + `busy_timeout=15000` + short-lived sessions ⇒ every read sees the latest commit; no identity-map staleness (no session outlives a call). Backend uses async sessions with per-request commit/rollback in `override_get_db`/`get_db`.

## 10. Cache Audit
- `dashboard_cache.compute_local_overview()` — pure function over SQLite, recomputed on every dashboard refresh, no TTL, no stored value. Correct.
- `MainWindow._last_server_overview` / `_last_server_top_vehicles` — last API snapshot, only used as a fallback for revenue when the local snapshot has no reservations; overwritten on each successful fetch, generation-guarded. Correct.
- `image_cache` — per-URL pixmap cache; invalidated on marker→URL reconciliation (`uploads.py`, pre-existing fix) then emits `data_refreshed`. Correct.
- `vehicle_list._vehicles_data` / `_data` — last rendered list, only re-read for re-render on locale change; always replaced wholesale by `load_vehicles()`. Not a stale-state source.
No cache was found in a `DB=new / CACHE=old / UI=old` configuration after the fixes.

## 11. Window Lifecycle Audit
One `MainWindow`; one `QStackedWidget`; **one persistent widget per page** (never destroyed/recreated). Dialogs are modal `.exec()` and short-lived. `logout` does `os.execl` (full process replacement) — no stale windows survive. EventBus connections are made once in `MainWindow.__init__` and live for the process. No "MainWindow points at widget A while UI shows widget B" condition exists.

## 12. Thread / Async Audit
- `DashboardFetcher(QThread)` → `stats_ready` signal → `_on_dashboard_stats` on UI thread, **generation-guarded** (`_dashboard_generation`) so a slow response can't overwrite a newer one. Test: `test_reactivity_regression::test_async_race_dashboard_stats`.
- `SyncThread(QThread)` → runs `SyncEngine` on its own asyncio loop → `sync_finished` signal → `_on_sync_finished` on UI thread. Re-entrancy guarded (`isRunning()` check + `RuntimeError` catch for deleted C++ object). `_on_sync_thread_finished` clears the Python ref.
- `RealtimeEventsClient(QThread)` → `event_received` → 250 ms debounce → `_run_sync`.
- No worker touches a widget directly; all UI updates cross back via queued signals.

## 13. Sync Audit
`SyncEngine.sync()` = push → uploads → pull → `apply_pulled_items()` (direct SQLite merge). `_on_sync_finished` emits `data_refreshed` only when something actually changed (`pushed>0 or pulled items>0 or uploaded>0 or conflicts`). Conflict-revert path emits the event (pre-existing fix, verified). `last_sync` marker handling unchanged and not implicated. The only sync-related defect was the *asymmetry* between the sync path (which still resets `MAINTENANCE→AVAILABLE` in `sync_service`) and the REST path (which didn't) — now symmetric.

## 14. Date/Time Audit
Canonical helper `desktop/app/utils/datetime_utils.py`: `parse_datetime_utc`, `reservations_overlap`, `BLOCKING_RESERVATION_STATUSES=("RESERVED","ACTIVE")`. Overlap uses half-open `[start, end)`. Dashboard period bounds computed in `Africa/Casablanca` (`dashboard_cache._period_bounds`) mirroring `backend/app/services/dashboard_service.py`. `test_forensic_matrix.py` exercises `Z` / `+00:00` / naive forms and boundary equality — all green. No timezone disagreement found between views.

## 15. Business Logic Audit
After the fixes, one definition of "in maintenance" (an `ACTIVE` maintenance record overlapping now) and one of "reserved"/"rented" (`RESERVED`/`ACTIVE` reservation overlapping now) is used by: desktop `_load_vehicles_from_local`, desktop `compute_local_overview`, backend `dashboard_service`, backend `check_availability`. `vehicle.status` is now purely structural (`AVAILABLE`/`SOLD`/`INACTIVE`) with a *transient* `MAINTENANCE` hold that both the REST and sync completion paths clear. Dashboard `available` is `total − (rented+reserved+maintenance)` on both sides.

## 16. Failure Injection
- DB failure on maintenance create → `rollback()` + `QMessageBox.critical` + `logger.error` (was: silent).
- One view raising in central dispatch → other four still refresh (was: aborted).
- Stale response after a newer request → dropped by generation guard.
- Detached ORM instance on maintenance completion → eager-loaded, 200 (was: 500).
- Offline finish-maintenance → vehicle frees **locally and immediately** via derivation, independent of sync.

## 17. Cross-Window Tests
`desktop/tests/test_cross_window_convergence.py` — one `MainWindow` with all pages instantiated and live; sync/realtime neutralised to isolate pure local reactivity:
create vehicle → 1 event, visible + dashboard `available≥1`; create maintenance → vehicle `MAINTENANCE` in list AND dashboard `maintenance==1`, `available==0`; finish maintenance → vehicle `AVAILABLE` in list AND dashboard `maintenance==0` — **with no tab switch, no refresh, no sync**; reservation active → `RENTED` + dashboard `rented==1`; cancel → `AVAILABLE` + `rented==0`. **PASS.**

## 18. Performance (Phase 21)
One user mutation currently triggers: 1 `data_refreshed` emit → 1 central dispatch → 5 view refreshes; plus a widget-local `refresh_data()` for complete/cancel/advance/finish (1 extra refresh of that one widget); plus, when online, `_run_sync()` → on real change a 2nd dispatch + `_refresh_dashboard(fetch_server=True)`. Net: **2–3 full refresh cycles per mutation, ~10–15 SQLite queries** — bounded and acceptable; no N× storm, no unbounded recursion. The widget-local double refresh is a minor, deliberate trade for instant local feedback; de-duping it (drop the local call, rely solely on the bus) is a safe future optimisation, not a correctness issue.

## 19. Full Test Results
- Desktop: `pytest -q` → **112 passed** (107 baseline + 5 new). ~68 s.
- Backend: `pytest -q` → **82 passed** (80 baseline + 2 new). ~6 s.
- Note: the desktop suite has a **pre-existing, non-deterministic Qt/QThread teardown abort** at interpreter shutdown (observed on the untouched baseline too — `107 passed` then `Fatal error` on a later run). It does not affect pass/fail counts. One newly-added test initially triggered it reliably because its EventBus spy stayed connected to a half-deleted `MainWindow`; the test now disconnects its spy and closes the window in teardown, and the suite is stable again. Recommend a session-scoped `QApplication` + explicit `deleteLater()`/`processEvents()` teardown helper for all widget tests (tracked as a risk, not fixed here).

## 20. Build Provenance
Source changed (desktop + backend). `ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip` / `dist/` / `build/` are **stale** and must NOT be represented as containing these fixes. A clean rebuild of the Windows EXE from the current tree is required before any release; that step was not performed here and cannot be verified from this environment.

## 21. Remaining Risks
1. **Existing production data**: vehicles already stuck at `status='MAINTENANCE'` need the new Alembic migration (`f1a2b3c4d5e6`) applied. Desktop SQLite self-heals via derivation (no migration needed there) and via the next sync pull once backend rows are fixed.
2. **`create_maintenance` REST still writes `vehicle.status='MAINTENANCE'`** (line 210) — intentionally kept for now so mobile/web keep working unchanged; the completion paths clear it symmetrically. The cleaner end state is to stop writing it entirely and derive everywhere (backend `dashboard_service` and `check_availability` already do). Left as a deliberate, low-risk follow-up.
3. **`ClientsWidget.refresh_data()`** runs on the global dispatch and is API-backed; if it ever blocks the UI thread it would stutter on every mutation. Not investigated in depth (outside vehicle/reservation/maintenance reactivity); worth confirming it is fully async.
4. **Qt test-teardown abort** (see §19) — cosmetic for CI reliability, not a product defect.
5. Windows EXE not rebuilt (§20).

---
```
DB:        commit-before-event, short-lived sessions, WAL — CONSISTENT
CACHE:     pure recompute / generation-guarded snapshots  — CONSISTENT
SYNC:      change-gated emit, symmetric maintenance reset  — CONSISTENT
EVENTBUS:  single main-thread singleton, 1 structural listener — CONSISTENT
WINDOWS:   one MainWindow, persistent pages, no stale refs  — CONSISTENT
WIDGETS:   status DERIVED, isolated refresh, visible errors — CONSISTENT

GLOBAL STATE CONSISTENCY: PASS (cross-window test)
```

---

# 28. FINAL VERIFICATION — ACTUAL EXECUTION (2026-08-29)

Every result below is real command output, not a repeated claim.

## Environment (discovered, not installed)
- Top-level `python`/`pytest`: pyenv shim (3.14.4), **no pytest** → this is why `pytest` alone fails.
- `desktop/venv/bin/python` → CPython 3.13.7, pytest 8.4.1  ← desktop suite
- `backend/venv/bin/python` → CPython 3.14.4, pytest 9.1.1  ← backend suite
- `packaging/windows/venv_wine` → Windows CPython 3.11.9 (AMD64) + PyInstaller 6.22.2, run via `wine`  ← EXE build

## Test results (JUnit XML, authoritative — survives the Qt teardown noise)

| Suite | tests | failures | errors | skipped | exit |
|-------|------:|---------:|-------:|--------:|:----:|
| desktop (`desktop/venv/bin/python -m pytest tests/`) | **115** | 0 | 0 | 0 | 0 |
| backend (`backend/venv/bin/python -m pytest`) | **84** | 0 | 0 | 0 | 0 |
| **total** | **199** | **0** | **0** | **0** | — |

New tests added during verification:
- `desktop/tests/test_status_derivation_regression.py` (4) — RC#1
- `desktop/tests/test_cross_window_convergence.py` (1, full mutation matrix) — RC#1/#5, cross-window
- `desktop/tests/test_global_dispatch_isolation.py` (2) — RC#5
- `desktop/tests/test_mutation_failure_no_false_event.py` (1) — RC#6
- `backend/tests/test_maintenance_frees_vehicle.py` (4) — RC#2/#3/#4

Pre-existing Qt/QThread **teardown SIGABRT** (present on the untouched baseline: `107 passed` then `Fatal error` on a re-run) is now fixed:
- `desktop/tests/conftest.py` — new autouse fixture stops leaked `QThread`s after each test.
- `test_maintenance_creation_refresh.py` — added `request.addfinalizer` to close/delete its `MainWindow`.
Suite now exits 0 consistently.

## Root-cause verification (direct)

| RC | How verified | Result |
|----|--------------|--------|
| #1 | `test_status_derivation_regression` (stale MAINTENANCE→AVAILABLE, active→MAINTENANCE, SOLD/INACTIVE preserved, cancelled-reservation→AVAILABLE) + `test_cross_window_convergence` (active reservation→RENTED, complete/cancel→AVAILABLE) — **no sync involved** | PASS |
| #2 | `test_maintenance_frees_vehicle::test_complete_endpoint_frees_vehicle` (MAINTENANCE→AVAILABLE), `::test_complete_preserves_sold_status` (SOLD untouched) | PASS |
| #3 | same file asserts `resp.status_code == 200` (pre-fix raised `ResponseValidationError`) | PASS |
| #4 | `::test_stale_maintenance_flag_does_not_block_booking` (available=True), `::test_sold_still_blocks_booking` (reason="SOLD") | PASS |
| #5 | `test_global_dispatch_isolation` — reservations refresh raises, vehicles/dashboard/maintenance/clients still run; verified across 2 dispatches | PASS |
| #6 | `test_mutation_failure_no_false_event` — forced commit failure → `rollback()` called, `QMessageBox.critical` shown, **zero** `data_refreshed` emits, nothing persisted | PASS |

## Cross-window matrix (`test_cross_window_convergence`, all pages live, sync neutralised)

| Mutation | Vehicles view | Dashboard | No sync / tab-switch / refresh |
|----------|--------------|-----------|:--:|
| Create vehicle | appears, AVAILABLE; **exactly 1 global event** | available≥1 | ✓ |
| Edit vehicle | new registration + model visible | — | ✓ |
| Delete vehicle | gone from list | total_vehicles=0 | ✓ |
| Create maintenance | MAINTENANCE | maintenance=1, available=0 | ✓ |
| Finish maintenance | AVAILABLE | maintenance=0, available≥1 | ✓ |
| Cancel maintenance | AVAILABLE | — | ✓ |
| Create reservation (active) | RENTED | rented=1 | ✓ |
| Cancel reservation | AVAILABLE | rented=0 | ✓ |
| Complete reservation | AVAILABLE | — | ✓ |

## Runtime checks (script, not test)
- **EventBus singleton**: `get_event_bus()` returns the identical object across module, direct, and re-import call paths — `True 0x...`.
- **SQLite cross-session**: session B reads a row committed by session A; session D reads an update committed by session C — both `True` (short-lived sessions, no identity-map staleness).
- **Date/time**: `Z` == `+00:00`; naive coerced to UTC == `Z`; touching intervals (end==start) do **not** overlap; real overlap detected.

## Clients page audit (was Risk #3 — now RESOLVED)
`desktop/app/ui/clients/client_list.py` `refresh_data()`:
- Authenticated → spawns `ClientsFetcher(QThread)`, `clients_ready` signal → `_on_clients_fetched` on the UI thread (queued), `finished`→`deleteLater`, ref held via `parent=self`. **No synchronous network I/O on the UI thread. No UI access from the worker.**
- Unauthenticated → reads the local SQLite cache (fast) and renders.
- API errors are never rendered as "0 clients".
→ The global dispatch calling `_clients_page.refresh_data()` **cannot freeze the GUI**.

## Migration verification (real PostgreSQL 16, throwaway container — production untouched)
- `alembic heads` → **single head `f1a2b3c4d5e6`** (the initial revision had forked off `5dfe7eb02006` alongside `c8e41a7b2d95`; `down_revision` corrected to `c8e41a7b2d95`).
- `alembic upgrade head` on a fresh PG16 DB → full 9-migration chain applies, ends at `f1a2b3c4d5e6`, **exit 0**.
- Data-repair scenario (seeded on real PG, downgrade -1, re-upgrade):

| Vehicle | Before | After migration | version |
|---------|--------|-----------------|---------|
| stuck (MAINTENANCE, no ACTIVE ticket) | MAINTENANCE | **AVAILABLE** | 3 → 4 |
| active (MAINTENANCE, ACTIVE ticket) | MAINTENANCE | **MAINTENANCE** (unchanged) | 1 |
| sold (SOLD) | SOLD | **SOLD** (unchanged) | 5 |

- `downgrade()` is a documented one-way no-op (data repair, nothing to revert).
- Migration SQL is portable (`UPDATE vehicles SET … WHERE status='MAINTENANCE' AND id NOT IN (SELECT vehicle_id FROM maintenances WHERE status='ACTIVE')`) — verified on both SQLite and PostgreSQL.
- **NOT run against production** (`car_rental_db_prod` container was never touched).

## Windows EXE build (real, via wine)
- Found `tzdata` **missing** from `venv_wine` → `ZoneInfo("Africa/Casablanca")` in `dashboard_cache.py` raised `ZoneInfoNotFoundError`. **The previously-shipped EXE has this latent crash on the dashboard path.** Fixed: `tzdata==2025.2` installed into `venv_wine`, added to `desktop/requirements.txt`, `--hidden-import=tzdata` added to `build_windows.sh` and the `.spec`.
- `bash packaging/windows/build_windows.sh` → **Build SUCCESS** (PyInstaller 6.22.2, Windows CPython 3.11.9 AMD64).
- Smoke test: `wine dist/…/ATELIER_BERLIN_LOCATION_CAR.exe` → SQLite init OK, login OK, realtime WebSocket connected, `sync/pull` + `clients` GET returned 200, **no `ZoneInfoNotFoundError`**, no crash. (Read-only startup calls only; no mutations issued.)

| Artifact | Path | SHA256 | Size |
|----------|------|--------|------|
| EXE | `packaging/windows/dist/ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` | `37b9c268741f8db8ca7f76130d137be871cb0ad7522f001c937f5989460d208f` | 9,095,560 |
| ZIP (rebuilt clean) | `ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip` | `338768603a0b83b2d91e84d6ae8098563675da7a5101a3299b41d71094dac4cd` | 61,853,785 |

- **ZIP-EXE hash == dist-EXE hash**: `37b9c268…` — **PASS** (ZIP extracted to a temp dir, EXE re-hashed).
- Architecture: **win64 (AMD64)**.
- Provenance: built from the current working tree containing all 6 fixes + the tzdata fix.

## What is PROVEN vs REMAINING

**PROVEN / TESTED**
- All 6 root causes fixed and each covered by a passing regression test.
- Cross-window convergence for every vehicle/reservation/maintenance mutation, with sync disabled.
- EventBus singleton; one global event per local mutation.
- Failed mutation → rollback + visible error + no false event.
- Clients page is non-blocking.
- Migration produces a single head, applies on real PG16, repairs only stale rows.
- Windows EXE builds, runs, and no longer carries the tzdata crash; ZIP↔EXE hash verified.

**REMAINING RISK / NOT DONE HERE**
1. **Apply migration `f1a2b3c4d5e6` to production PostgreSQL** (verified safe on a PG16 clone; not run on prod by design).
2. **Deploy the backend** (RC#2/#3/#4 are server-side; the running `car_rental_api_prod` container still has the old code).
3. **`create_maintenance` REST still writes `vehicle.status='MAINTENANCE'`** — deliberately kept (symmetric with the now-restored completion reset); full "derive-only" is a follow-up.
4. EXE built under **wine**, not native Windows — recommend a confirmation run on a real Windows host before distribution.
5. Mobile app (`mobile/`) not audited — it consumes the same maintenance/availability API and benefits from RC#2/#3 automatically, but its own UI reactivity was out of scope.
