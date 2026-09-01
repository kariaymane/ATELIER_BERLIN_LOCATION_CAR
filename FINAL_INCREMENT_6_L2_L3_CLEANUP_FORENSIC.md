# FINAL — Increment 6 (desktop L2/L3 architectural cleanup)

Date: 2026-08-31
Scope: `/home/ayman/car-rental-system/desktop` only.
Starting point: the current working tree, immediately after Increment 6A /
the status-contradiction forensic (verified green: backend 120 / desktop 215 /
mobile 49). **No Increment 6A change was reverted, weakened, or reinterpreted.**

Goal (from `MASTER_100_PERCENT_LIVE_ARCHITECTURE_REPORT.md` row 6 + the
Increment 2 forensic §10 D2 / carried lattice items L2, L3, L5):

> UI reads from the DomainStore snapshot → mutations go through
> `store.mutate()` → store state changes → UI reacts to the new snapshot.

---

## 1. IMPLEMENTED CHANGES

### 1.1 Files changed (7)

| File | What |
|---|---|
| `app/services/event_bus.py` | Removed the dead `entity_changed` Signal; documented `data_refreshed` as an *external-trigger-only* channel. |
| `app/ui/maintenance/maintenance_list.py` | `MaintenanceWidget` renders the table **from `DomainStore.snapshot`** (new `_render_from_snapshot`); `_advance_step` + `_finish_maintenance` migrated to `store.mutate()`; status filter re-projects the snapshot (no reload). |
| `app/ui/reservations/reservation_list.py` | `ReservationWidget` renders the list table **and** the "available vehicles" grid from `DomainStore.snapshot` (new `_render_from_snapshot`, rewritten `_refresh_available_vehicles`, `_create_available_card` now takes a dict); `_complete_reservation` + `_cancel_reservation` migrated to `store.mutate()` (new shared `_set_reservation_status`). |
| `app/ui/main_window.py` | `_create_vehicle`, `_update_vehicle`, `_on_delete_vehicle`, `_create_maintenance_record` migrated to `store.mutate()`; `_on_reservation_updated` / `_on_maintenance_updated` no longer emit `data_refreshed` (the mutation already published); vehicle image-upload registration extracted to `_register_vehicle_image_uploads` (runs after the transaction, since `register_pending_upload` self-commits). |
| `tests/test_live_refresh.py` | Prime the DomainStore (`get_domain_store().reload()`) after seeding — the grid now reads the snapshot, not SQLite. |
| `tests/test_reactivity_regression.py` | Assert the mutation published exactly one new store revision + the dashboard fan-out fired, instead of spying on the deprecated `data_refreshed` pulse. |
| `tests/test_cross_window_convergence.py` | `_Counter` now counts published DomainStore revisions (the canonical "state changed" channel) instead of `data_refreshed` emissions. |
| `tests/test_mutation_failure_no_false_event.py` | Patch `app.database.get_local_session` (the seam `store.mutate()` uses) instead of `main_window.get_local_session`; also assert the failed mutation published **no** new revision. |
| `tests/test_maintenance_wins_reservation_desktop.py` | Assert exactly one new store revision for the whole "maintenance wins" operation instead of `emits == [1]`. |

(`test_cross_window_convergence.py`, `test_mutation_failure_no_false_event.py`,
`test_maintenance_wins_reservation_desktop.py` are untracked in git — pre-existing
from the Increment 2–6A work — so `git diff` does not list them, but they are
modified on disk.)

### 1.2 The mutation handlers migrated to `store.mutate()`

The Increment-2 forensic estimated "7". The precise audit of the current tree
found **8** desktop domain-mutation handlers that owned their own
`get_local_session()` + `commit()` + hand-rolled refresh trigger:

| # | Handler | File | Notes |
|---|---|---|---|
| 1 | `MainWindow._create_vehicle` | `main_window.py` | image-upload registration moved to after the txn |
| 2 | `MainWindow._update_vehicle` | `main_window.py` | as above; keeps the "readonly database" user message |
| 3 | `MainWindow._on_delete_vehicle` | `main_window.py` | confirm-dialog read stays on a short read-only session; delete + enqueue in the txn |
| 4 | `MainWindow._create_maintenance_record` | `main_window.py` | maintenance insert **+ parts + "maintenance wins" reservation cancellations + all sync-queue items** now one atomic `mutate()` unit |
| 5 | `MaintenanceWidget._advance_step` | `maintenance_list.py` | step read stays on a short read session |
| 6 | `MaintenanceWidget._finish_maintenance` | `maintenance_list.py` | |
| 7 | `ReservationWidget._complete_reservation` | `reservation_list.py` | via `_set_reservation_status(res_id, "COMPLETED")` |
| 8 | `ReservationWidget._cancel_reservation` | `reservation_list.py` | via `_set_reservation_status(res_id, "CANCELLED")` |

Each now:
* runs the row writes + `SyncQueue.enqueue(...)` inside `fn(session)`;
* `DomainStore.mutate(fn)` commits once → `reload()` → one new revision →
  `MainWindow._on_domain_changed` fan-out refreshes **every** view from the new
  snapshot;
* on any exception: `mutate()` rolls back, **no reload, no revision bump, no
  notification**; the handler catches, logs, shows the same `QMessageBox`, and
  returns — no false "state changed";
* still fires its existing signal / `_run_sync()` so the background push runs.

**Deliberately NOT migrated: `ReservationWidget._create_reservation_record`.**
It carries an intricate, recently-hardened flow that `store.mutate()`'s
single-transaction / rollback-on-error shape cannot express without a broad
rewrite: the online/offline availability probe with 6A error-category handling
(401/403/404/409/422/5xx/transport all distinct), new-client creation with a
compensating delete, and `register_pending_upload` (which self-commits).
Migrating it was judged "broad rewrite, real regression risk across 9 test
files, low incremental value" — out of scope for this increment. It is **not a
second source of truth**: on success it calls `self.refresh_data()`, which now
performs `store.reload()`, so it converges through the same canonical snapshot
as everything else. Follow-up candidate for a dedicated increment.

### 1.3 `entity_changed` removal — proof it was dead

```
$ grep -rn "entity_changed" app/ tests/          # before
app/services/event_bus.py:5:    entity_changed = Signal(str, str)
```
One declaration, **zero** emitters, **zero** `.connect(...)`, **zero** handlers,
**zero** test references. Removed the line.
```
$ grep -rn "entity_changed" app/ tests/          # after
(none)
```
Nothing was relying on it, so nothing needed migrating first.

### 1.4 `data_refreshed` — now external-trigger only

Retained emitters (all *external* state changes that cannot go through
`mutate()`):
```
app/sync/engine.py:184     conflict-revert after a rejected push
app/sync/uploads.py:356    pending-upload processor reconciled a URL
app/ui/main_window.py:615  _on_sync_finished — push/pull applied rows off-thread
app/ui/main_window.py:636  _on_refresh_clicked — manual refresh button
```
Retained consumer: `app/ui/clients/client_details.py` (unchanged).
All of them funnel into `MainWindow._on_global_data_refreshed → store.reload()`
→ one revision → fan-out. `data_refreshed` is no longer emitted by any committed
domain mutation.

---

## 2. VERIFIED EVIDENCE

### 2.1 DomainStore is the single desktop UI state authority

`refresh_data()` in **both** widgets is now:

```python
store = self._store
rev_before = store.revision
try:
    store.reload()                     # direct entrypoint: publish fresh revision
except Exception as e:
    logger.error(...)
if store.revision != rev_before and self._rendered_rev == store.revision:
    return                             # a re-entrant fan-out call already painted it
self._render_from_snapshot(store.snapshot)   # pure projection — NO SQLite
self._rendered_rev = store.revision
```

`_render_from_snapshot(snap)` reads only `snap.reservations` / `snap.maintenances`
/ `snap.vehicles` (dicts already carrying canonical **effective** status +
`raw_status`, `cancellation_reason`, costs, dates …). Filtering / sorting /
badges / RTL / Pistache classes / date formatting are byte-for-byte the previous
logic, just fed from the snapshot.

No hidden DB read remains in either widget's **rendering** path:

```
$ grep -n "get_local_session\|session.query" app/ui/maintenance/maintenance_list.py
 19: import                                   (module import)
 73-77: MaintenanceFormDialog vehicle-picker  (6A snapshot-first fallback — a DIALOG, not the list)
 435-437: _advance_step current_step read     (pre-mutation read of one field, not rendering)
 450 / 473: inside _apply(session) closures    (the mutate() session — correct)

$ grep -n "get_local_session\|session.query" app/ui/reservations/reservation_list.py
 19: import
 151-153 / 210-225: ReservationFormDialog     (the modal's own client-picker + live availability label)
 790 / 877 / 899 / 1060-1062: _create_reservation_record (bespoke handler — see §1.2)
 1096: inside _set_reservation_status _apply    (the mutate() session — correct)
```
The reservations **list table** and the **available-vehicles grid** — the two
things the forensic named as "bypass the DomainStore snapshot and re-query
SQLite in refresh_data()" — no longer touch SQLite.

### 2.2 Convergence on every path

| Trigger | Path | Result |
|---|---|---|
| initial load | `_initial_load → store.reload()` | fan-out renders all 5 views |
| committed mutation | `store.mutate(fn) → commit → reload()` | one revision → fan-out |
| mutation failure | `store.mutate` raises → rollback | **no** revision, **no** fan-out, visible error |
| background sync applied rows | `_on_sync_finished → data_refreshed → _on_global_data_refreshed → store.reload()` | fan-out |
| pending-upload reconcile / conflict revert | `sync/*.py → data_refreshed → store.reload()` | fan-out |
| manual refresh button | `_on_refresh_clicked → data_refreshed + _run_sync` | fan-out |
| time boundary (reservation ends / maintenance window opens) | `BoundaryClock → store.recompute_effective()` | fan-out (unchanged, Increment 3) |
| tab visit | `_switch_page → widget.refresh_data() → store.reload()` | self-heal — fan-out |
| language switch | `retranslate_ui → refresh_data()` | re-render from snapshot (rev unchanged ⇒ guard's first clause false ⇒ renders) |
| status filter (maintenance) / date filter (reservations) | dedicated handler → `_render_from_snapshot` / `_refresh_available_vehicles` | re-project current snapshot, **no** reload |

### 2.3 Test results

Focused first, then full:

```
tests/test_domain_store*.py  tests/test_global_dispatch_isolation.py
tests/test_maintenance_creation_refresh.py ................. 27 passed

tests/test_cross_window_convergence.py
tests/test_mutation_failure_no_false_event.py
tests/test_maintenance_wins_reservation_desktop.py
tests/test_reactivity_regression.py
tests/test_live_refresh.py
tests/test_full_reactivity_lifecycle.py ..................... 14 passed

tests/test_forensic_6a_maintenance_timezone.py  tests/test_forensic_matrix.py
tests/test_reservation_e2e.py  tests/test_reservation_overlap_client_forensics.py
tests/test_false_conflict_regression.py  tests/test_bug1_reservation_error_category.py
tests/test_bug2_vehicle_form_status.py  tests/test_vehicle_switch_forensic.py
tests/test_real_ui_flow_forensic.py  tests/test_status_derivation_regression.py
tests/test_cross_client_convergence.py ...................... 99 passed

FULL DESKTOP SUITE ......................................... 215 passed (158s)
BACKEND SUITE ............................................. 120 passed  (7s)
MOBILE testDebugUnitTest .................................. 49 passed, 0 failures
```

**Zero regressions.** Desktop stays at 215 (no tests added or deleted — 5 files
edited). Backend 120 and mobile 49 untouched and green.

### 2.4 Test failures encountered and how they were classified

Six tests failed on the first run after the refactor. Each was triaged, none was
"blindly fixed to go green":

| Test | Category | Resolution |
|---|---|---|
| `test_cross_window_convergence::test_one_mutation_one_event_all_views_converge` | **B — asserts the pre-Increment-6 mechanism** (`data_refreshed` emission count) | `_Counter` now counts published store revisions — the real invariant ("one mutation → one convergence") is unchanged and still asserted `== 1`. |
| `test_maintenance_wins_reservation_desktop::test_overlapping_maintenance_cancels_reservation[RESERVED/ACTIVE]` | **B** (`emits == [1]`) | assert `store.revision == rev_before + 1`. The behavioural assertions (reservation CANCELLED + reason, sync items enqueued) are untouched and still pass. |
| `test_reactivity_regression::test_gap_a_maintenance_creation_refreshes_dashboard` | **B** (`bus_spy.assert_called()`) | assert one new revision **and** spy the dashboard fan-out (`_refresh_dashboard`) — closer to the test's own name than the old pulse spy. |
| `test_mutation_failure_no_false_event` | **B — mechanism seam moved** (`store.mutate()` opens its session via `app.database.get_local_session`, not `main_window.get_local_session`) | patch the correct seam; the intent (rollback + visible error + no false event + nothing persisted) is preserved and a "no new revision" assertion was **added**. |
| `test_live_refresh::test_exact_boundary_allows_vehicle` | **B — test must prime the canonical read model** | `get_domain_store().reload()` after seeding (the two sibling grid tests got the same priming so they assert against a populated snapshot, not an empty one). |

No category-A (real regression) and no category-C (contract mismatch) failures.

### 2.5 Increment 6A fixes — all intact

```
$ grep -n "astimezone(timezone.utc)" desktop/app/ui/maintenance/maintenance_list.py
156-157   maintenance form persists local wall-time CONVERTED to UTC   ✔ unchanged

$ grep -n "astimezone(timezone.utc)" desktop/app/ui/reservations/reservation_list.py
199-200   _recalculate pre-check                                       ✔ unchanged
337-338   _on_save persistence                                         ✔ unchanged
548-549   availability grid request bounds (now inside the snapshot path) ✔ preserved
```
* `MaintenanceFormDialog` vehicle picker still reads
  `get_domain_store().snapshot` and excludes effective `MAINTENANCE/SOLD/INACTIVE`
  (6A P0-B) — untouched.
* `VehicleRow._show_details` still passes the canonical `self._data["status"]`
  to `VehicleDetailModal` — `vehicle_list.py` not touched this increment.
* `test_exact_boundary_allows_vehicle` keeps its whole-second instant (6A note).
* Backend "maintenance wins", `cancellation_reason`, client recto/verso columns,
  `effective_status` in sync payloads, `/sync/bootstrap` revision — backend suite
  120/120, no backend file touched this increment.
* Migration head unchanged:
  ```
  $ cd backend && venv/bin/alembic heads
  h3c4d5e6f7g8 (head)          # single head: f1a2b3c4d5e6 → g2b3c4d5e6f7 → h3c4d5e6f7g8
  ```

---

## 3. REMAINING RISKS

1. **`_create_reservation_record` still bypasses `store.mutate()`** (see §1.2).
   Mitigation: it converges through `store.reload()` via `refresh_data()`; its
   own transaction + compensation logic is unchanged and fully covered by 9
   test files. Not a correctness risk today; a tidiness debt for a future
   increment.
2. **Widgets are driven by the `MainWindow._on_domain_changed` fan-out, not by
   their own store subscription.** This matches the established Vehicles /
   Dashboard pattern and keeps `test_global_dispatch_isolation` /
   `test_one_broken_view_...` semantics. A `MaintenanceWidget` / `ReservationWidget`
   constructed *outside* a `MainWindow` and mutated in place will not re-render
   itself — but no such runtime path exists (no `MaintenanceWidget(` in any test;
   standalone `ReservationWidget` tests assert DB state, not rendered rows,
   except the grid tests which now prime + reload the store explicitly).
3. **`register_pending_upload` self-commits**, so vehicle image-upload records
   are written just outside the `store.mutate()` transaction (after it commits).
   Pre-existing behaviour — the old code also committed them before the entity's
   own `commit()`. If the process dies between the two, the entity is persisted
   and the upload record is retried on next launch from the marker; no data
   loss, no orphan.
4. **`data_refreshed` is still present.** Fully removing it needs
   `client_details.py` and the three background-sync emitters moved onto store
   subscriptions / a revisioned pull — the same "proven-replacement" gate the
   Increment 2/3 forensics set. Deferred; it is now correctly scoped to
   *external* triggers only.

---

## 4. GIT STATUS / DIFF SUMMARY

Working tree only — **nothing committed** (the repo's forensic workflow does not
auto-commit; Increment 0 checkpoint is still pending and remains the operator's
call).

Increment-6 deltas (on top of the 6A tree):

```
 desktop/app/services/event_bus.py               |  16 +-   (entity_changed removed)
 desktop/app/ui/main_window.py                   | ~180 lines reworked (4 handlers → mutate)
 desktop/app/ui/maintenance/maintenance_list.py  | ~180 lines reworked (snapshot render + 2 handlers)
 desktop/app/ui/reservations/reservation_list.py | ~230 lines reworked (snapshot render + grid + 2 handlers)
 desktop/tests/test_live_refresh.py              |  +5   (store priming)
 desktop/tests/test_reactivity_regression.py     |  ~14  (revision assertion)
 desktop/tests/test_cross_window_convergence.py  |  ~12  (untracked; _Counter → revisions)
 desktop/tests/test_mutation_failure_no_false_event.py | ~6 (untracked; seam + revision assert)
 desktop/tests/test_maintenance_wins_reservation_desktop.py | ~8 (untracked; revision assert)
```

No schema change. No backend/mobile change. No branding / theme / RTL / date /
status-rule / maintenance-precedence / recto-verso / sync-behaviour change.

Suites: **backend 120 · desktop 215 · mobile 49 — all green.**
