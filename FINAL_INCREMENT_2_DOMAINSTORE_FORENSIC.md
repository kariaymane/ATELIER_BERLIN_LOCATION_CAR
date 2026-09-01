# FINAL — INCREMENT 2: DOMAINSTORE (Desktop canonical reactive state)

**Project:** `/home/ayman/car-rental-system`
**Date:** 2026-08-30
**HEAD:** `df9b96dfa56692845560d18995c5c83503f01140` (branch `main`, 12 commits ahead of `origin/main`, unpushed)
**Working tree:** DIRTY — prior in-progress work + Increment 1 + this increment. Nothing committed, stashed, reset, cleaned, or pushed.
**Predecessor:** Increment 1 (cross-runtime fleet-status parity) — COMPLETE & GREEN, unchanged by this increment.

---

## 1. EXACT ROOT CAUSE ADDRESSED

From `MASTER_100_PERCENT_LIVE_ARCHITECTURE_REPORT.md` §1, the root cause is:

> **There is no single, ordered, observable stream of committed domain state
> that every screen derives from.** State is *copied* (SQLite → per-view query →
> widget) and re-synchronised by an argument-less `data_refreshed` pulse that
> MainWindow fanned out by hand. A missed or throwing callback left a tab
> silently stale; two views could disagree; and there was no notion of "which
> version am I showing".

Increment 2 removes the **desktop** manifestation of this: it introduces one
authoritative in-memory projection (`DomainStore`) with a monotonic
`revision`, isolated subscriber notification, a transactional `mutate()` write
path, and a self-heal on tab visit. Dashboard and Vehicles now render **from
the same snapshot**; Reservations/Maintenance are refreshed **by** the store
(never independently deciding *when*).

Increment 2 explicitly does **not** address the time-boundary gap (that is
Increment 3 — `BoundaryClock`). See §9.

---

## 2. FILES CHANGED

### New (canonical state layer)
| File | Purpose |
|---|---|
| `desktop/app/state/__init__.py` | package export |
| `desktop/app/state/domain_store.py` | `DomainStore`, `DomainSnapshot`, `get_domain_store()`, `reset_domain_store()` — the one canonical local domain-state layer above SQLite |

### Modified
| File | Change |
|---|---|
| `desktop/app/ui/main_window.py` | subscribe to `DomainStore`; `_on_global_data_refreshed` → thin `store.reload()` trigger; new `_on_domain_changed` isolated fan-out (subscriber); `_load_vehicles_from_local` + `_refresh_dashboard` render **from the snapshot** (no own query, no own status derivation); `_initial_load` primes the store; `_switch_page` self-heals via the store; `closeEvent` unsubscribes |
| `desktop/tests/conftest.py` | new autouse `_reset_domain_store` fixture — every test gets a fresh store singleton with no leaked subscribers from a previous test's destroyed `MainWindow` |

### New tests
| File | Coverage |
|---|---|
| `desktop/tests/test_domain_store.py` | store unit contract (9 tests) |
| `desktop/tests/test_domain_store_convergence.py` | whole-window convergence (7 tests) |

**No mutation-handler bodies were rewritten** (see §10, decision D2).
**No files deleted.**

---

## 3. OLD STATE FLOW

```
 mutation handler (_create_vehicle, _create_maintenance_record, …)
   session = get_local_session()
   …build rows…
   session.commit()
   get_event_bus().data_refreshed.emit()      ← argument-less pulse
   self._run_sync()
        │
        ▼
 MainWindow._on_global_data_refreshed()        ← hand fan-out
   for fn in (_load_vehicles_from_local,        each fn:
              _refresh_dashboard,                 - opens its OWN SQLite session
              _reservations.refresh_data,         - runs its OWN query
              _maintenance.refresh_data,          - derives its OWN fleet status
              _clients_page.refresh_data):        - builds widgets
        try: fn()
        except: log      ← a throw here leaves THAT view stale forever
                            (until an unrelated mutation happens to fire again)

 + no revision  →  a view cannot tell it missed an update
 + Dashboard used compute_local_overview() (own session);
   Vehicles used compute_fleet_sets() (own session)  → two reads, can skew
 + background sync / uploads emitted data_refreshed cross-thread
```

---

## 4. NEW STATE FLOW

```
 any trigger:  mutation handler emits data_refreshed  ─┐
               background sync/uploads emit data_refreshed ─┤
               tab visit (_switch_page) ─────────────────────┤
               _initial_load / _on_sync_finished ────────────┤
                                                             ▼
                          MainWindow._on_global_data_refreshed()
                                     └─▶ DomainStore.reload()
                                           1. ONE SQLite read
                                           2. build DomainSnapshot:
                                                - vehicles[] each carrying the
                                                  CANONICAL effective status
                                                  (app.utils.fleet_status — the
                                                  Increment-1 spec, never re-derived)
                                                - reservations[], maintenances[]
                                                - fleet_counts (canonical buckets)
                                                - overview (compute_local_overview,
                                                  same session → cannot skew vs vehicles)
                                           3. revision += 1   (monotonic)
                                           4. notify subscribers — EACH isolated:
                                              one raising subscriber is logged and
                                              never blocks or propagates
                                     │
                                     ▼
                    MainWindow._on_domain_changed(snapshot, revision)
                       isolated fan-out, in order:
                         vehicles     → render window._vehicle_list FROM snapshot
                         dashboard    → render window._dashboard    FROM snapshot
                         reservations → window._reservations.refresh_data()
                         maintenance  → window._maintenance.refresh_data()
                         clients      → window._clients_page.refresh_data()
                       records _last_applied_revision

 mutate(fn)  (canonical write path, used by new code + tests):
     session = get_local_session()
     fn(session);  session.commit()          → on success: reload()  (revision++, notify)
     on ANY exception: session.rollback(); re-raise; NO reload, NO revision bump,
                       NO subscriber notification  (no false "state changed")

 SELF-HEAL:  a direct call to a view entrypoint (tab visit, or the next
     mutation's fan-out) calls store.reload() first, which republishes to the
     view that previously threw. A persistently-bad row still fails that one
     view but never the others, and recovers the instant the data is valid.
```

Key invariant: **the snapshot is the only in-memory domain truth.** Vehicles
and Dashboard hold no independent copy or derivation. Reservations/Maintenance
still render from a fresh committed-DB read, but only *when the store tells
them to* — they no longer own the refresh decision (see §11 audit rows R6/R7).

---

## 5. MIGRATED VIEWS

| View | Before | After |
|---|---|---|
| **Dashboard** | `compute_local_overview()` on its own session, applied by `_refresh_dashboard` | renders `store.snapshot.overview` (built by the store in the same read as the vehicle list) — Dashboard ≠ Vehicles is now structurally impossible |
| **Vehicles** | `_load_vehicles_from_local` opened a session, called `compute_fleet_sets`, built dicts | renders `store.snapshot.vehicles` (each dict already carries the canonical effective `status` + `raw_status`) — no query, no derivation |
| **Reservations** | `refresh_data()` on its own DB read, called by hand fan-out | `refresh_data()` unchanged internally, but invoked **by the store fan-out** on every revision + on tab visit; never decides *when* to refresh |
| **Maintenance** | same as Reservations | same — store-driven |
| **Main-window vehicle-status surface** (`_vehicle_list._vehicles_data`, the tally the Dashboard is checked against) | populated by `_load_vehicles_from_local`'s own derivation | populated from `store.snapshot` — one source |
| Clients | API-driven `refresh_data()` | unchanged; still invoked by the fan-out. Canonical client data is server-authoritative; folding it into the store is Increment 3 (audit row R8). |

---

## 6. REFRESH MECHANISMS REMOVED / REWIRED

| Mechanism | Before | Now |
|---|---|---|
| `MainWindow._on_global_data_refreshed` hand fan-out over 5 self-querying views | the primary state mechanism | **repurposed** to a one-line `store.reload()` trigger; the fan-out moved to `_on_domain_changed` (a store subscriber) and now reads the snapshot |
| Vehicles page independent SQLite query + `compute_fleet_sets` call | in `_load_vehicles_from_local` | **removed** — renders from snapshot |
| Dashboard independent `compute_local_overview()` call | in `_refresh_dashboard` | **removed** — renders from `snapshot.overview` |
| `data_refreshed` as a *level-less state channel* | consumers reacted with a full self-refresh | **demoted to a trigger only**; the actual state is the revisioned snapshot |
| No revision / no staleness detection | — | `revision` monotonic; `_last_applied_revision` tracked; `_switch_page` self-heals |

**Not removed this increment** (proven-replacement rule, Phase 18):
`data_refreshed` the *signal* still exists (mutation handlers, `sync/uploads.py`,
`sync/engine.py` conflict-revert, `client_details.py`, and 6 regression tests
still emit/consume it). It is now purely a trigger into `store.reload()`.
Removing the signal entirely is Increment 3 once `client_details` and the
background-sync paths are moved onto `store` subscriptions / a revisioned pull.

---

## 7. TESTS ADDED

### `desktop/tests/test_domain_store.py` (9)
- `test_initial_state` — revision 0, empty snapshot
- `test_reload_builds_snapshot_and_bumps_revision` — snapshot content + monotonic revision (bumps even with identical data)
- `test_subscription_receives_snapshot_and_revision` — cb gets `(snapshot, revision)`; unsubscribe honoured
- `test_multiple_subscribers_all_converge_on_same_revision`
- `test_one_failing_subscriber_does_not_block_the_others` — raising subscriber logged, others still run, store still functional next revision
- `test_mutate_commits_then_reloads` — commit → revision++ → notify; row persisted
- `test_mutate_failure_rolls_back_and_does_not_publish` — rollback, **no** revision bump, **no** notification, staged row gone
- `test_snapshot_effective_status_matches_normative_spec` — snapshot effective status == `shared/fleet_status_reference.py` (Increment 1)
- `test_singleton_and_reset`

### `desktop/tests/test_domain_store_convergence.py` (7)
- `test_vehicle_create_converges_across_all_views_without_tab_switch` — one mutation → one revision → Vehicles view + Dashboard view agree; `dashboard == snapshot == standalone canonical`
- `test_maintenance_creation_cancels_reservation_and_propagates_everywhere` — maintenance-wins cancellation visible in Vehicles + Dashboard + reservation row, live
- `test_maintenance_completion_frees_vehicle_everywhere` — via the **real** `_finish_maintenance` UI path
- `test_sync_applied_change_propagates_through_the_same_path` — `SyncEngine.apply_pulled_items` + the pulse → same convergence
- `test_no_refresh_button_and_no_tab_switch_needed` — `_on_refresh_clicked` and `_switch_page` are booby-trapped to fail the test if called
- `test_one_broken_view_does_not_freeze_the_rest_and_self_heals` — reservations view throws on first publish; others converge; next mutation retries and succeeds
- `test_dashboard_and_vehicles_never_disagree_after_any_mutation` — invariant check after create + maintenance

---

## 8. TEST RESULTS  (all GREEN)

```
BACKEND  full suite ...................................... 115 passed        7.25s
DESKTOP  full suite ...................................... 177 passed      180.98s
         (161 before Increment 2  +16  = 9 test_domain_store
                                        + 7 test_domain_store_convergence)

Increment-1 cross-runtime parity:
  backend/tests/test_fleet_status_crossruntime.py ........  14 passed
  desktop/tests/test_fleet_status_crossruntime.py ........  14 passed
  shared/fleet_status_reference.py self-check ............  ALL PASS (14 vectors)

Increment-2 DomainStore:
  desktop/tests/test_domain_store.py .....................   9 passed
  desktop/tests/test_domain_store_convergence.py .........   7 passed
```

**No existing test was modified or deleted.** The 6 regression tests that are
tightly coupled to `data_refreshed` / `_on_global_data_refreshed`
(`test_global_dispatch_isolation`, `test_cross_window_convergence`,
`test_maintenance_wins_reservation_desktop`, `test_mutation_failure_no_false_event`,
`test_reactivity_regression`, `test_live_ui_audit`) all pass unchanged — the
rewire preserved their exact contracts (one emit per mutation, no emit on
failure, ordered isolated fan-out, `client_details` reload on pulse).

---

## 9. REMAINING LIMITATIONS (precise, no hand-waving)

| # | Limitation | Why it remains | Fixed by |
|---|---|---|---|
| L1 | **Time-boundary state is not live.** A reservation that ends, or a maintenance window that opens/closes, changes the *correct* effective status with no mutation and no event. `DomainStore.reload()` is only triggered by a mutation, a sync, a tab visit, or the manual pulse. Between those, a snapshot built at 17:59 still says "RENTED" at 18:01. | `BoundaryClock` is deliberately out of scope for Increment 2. No timer/polling shim was added (per directive #8). | **Increment 3** |
| L2 | **`data_refreshed` still exists** as a trigger signal. It is emitted by mutation handlers, `sync/uploads.py`, `sync/engine.py` (conflict revert), and consumed by `client_details.py` + 6 regression tests. It is no longer a *state channel* (just a `store.reload()` trigger), but it is not gone. | Removing it needs `client_details` and the background-sync paths moved onto store subscriptions / a revisioned pull first (proven-replacement rule). | Increment 3 |
| L3 | **Reservations & Maintenance views still render from their own committed-DB read** (their `refresh_data()` is unchanged internally). This is always *fresh* (reads committed SQLite) and is now *store-driven* (they don't decide when), so it cannot go stale — but it is a second read, not a pure snapshot render. A micro-skew is theoretically possible if SQLite is written between `store.reload()` and the view's query within the same fan-out (both are on the UI thread, so in practice this window is empty). | Converting their card rendering to consume `snapshot.reservations` / `snapshot.maintenances` is mechanical but sizeable; deferred to keep this increment's blast radius contained. | Increment 3 (or 2.5) |
| L4 | **Clients view is not in the store.** It renders from the live API. Its `data_refreshed` → `_reload_client_locally` wiring in `client_details.py` is untouched. | Client data is server-authoritative; a local projection needs the revisioned pull from Increment 4. | Increment 3/4 |
| L5 | **Mutation-handler bodies were not migrated to `store.mutate()`.** They keep their existing (already-correct) `commit()`-then-`data_refreshed.emit()` pattern. `mutate()` is the canonical path for *new* writes and is fully tested. | Migrating 7 large handlers to closures risked regressions and would break 3 tests that monkeypatch `mw.get_local_session` to force a mid-commit failure. Low value, real risk. | Increment 3 cleanup |
| L6 | **Background sync still cannot call the store directly** (wrong thread). It emits `data_refreshed` (queued to the UI thread) which then calls `store.reload()`. Correct, but indirect. | A thread-safe store or a UI-thread marshalling helper is Increment 4 territory (revisioned pull). | Increment 4 |
| L7 | **A persistently-throwing view** (genuinely bad local row) still shows stale data *in that one view* until the row is fixed or the tab is revisited. The other four views are unaffected and the revision keeps advancing. | This is the correct failure mode (isolation), not a bug — documented for completeness. | n/a |
| L8 | Stale source artifact: `desktop/app/ui/reservations/reservation_list.py.bak.20260825_042143` sits in the tree. Not imported by Python. | Pre-existing cruft, out of scope. | housekeeping |

**This increment does NOT make the desktop app "100% live."** L1 alone means a
purely time-driven transition is still invisible until the next unrelated
trigger.

---

## 10. DESIGN DECISIONS (and why)

- **D1 — `DomainStore` is a plain class, not a `QObject`.** It must be unit-
  testable without a `QApplication`. Subscribers are plain callables. Qt
  consumers (`client_details`) keep using the `data_refreshed` signal for now.
- **D2 — existing mutation handlers keep their `commit(); data_refreshed.emit()`
  shape.** They already commit in one transaction and already suppress the
  emit on failure. Wrapping them in `store.mutate()` closures is deferred
  (L5). `mutate()` exists and is the canonical path going forward.
- **D3 — view entrypoints (`_load_vehicles_from_local`, `_refresh_dashboard`)
  call `store.reload()` themselves.** A direct call (tab visit, test) always
  publishes fresh state; when the call is *re-entered from the fan-out*,
  `reload()` is a re-entrancy no-op and the method renders in place. A
  revision check prevents double-rendering.
- **D4 — `_on_global_data_refreshed` is retained** (not deleted) because
  `test_global_dispatch_isolation` and `test_cross_window_convergence` call /
  disconnect it by name. It is now a one-line `store.reload()`.

---

## 11. FORENSIC DEAD-REFRESH AUDIT (post-implementation)

Every refresh mechanism in `desktop/app/`, classified:

| # | Mechanism | Location | Classification | Note |
|---|---|---|---|---|
| R1 | `EventBus.data_refreshed` signal | `services/event_bus.py` | **REQUIRED (demoted)** | now a trigger into `store.reload()`, not a state channel. Full removal = Increment 3 (needs L2/L4/L6 first). |
| R2 | `EventBus.entity_changed` signal | `services/event_bus.py` | **OBSOLETE** | declared, never emitted anywhere. Safe to delete in Increment 3. |
| R3 | `MainWindow._on_global_data_refreshed` | `ui/main_window.py` | **REQUIRED (rewired)** | one-line `store.reload()`; kept because 2 tests reference it by name. |
| R4 | `MainWindow._on_domain_changed` | `ui/main_window.py` | **KEEP (new)** | the canonical isolated fan-out; store subscriber. |
| R5 | `_load_vehicles_from_local` / `_refresh_dashboard` own SQLite query + status derivation | `ui/main_window.py` | **OBSOLETE → REMOVED** | replaced by snapshot render. |
| R6 | `ReservationWidget.refresh_data()` own DB read | `ui/reservations/reservation_list.py` | **NEXT-INCREMENT** | still a second read; store-driven now, so cannot go stale. Convert to `snapshot.reservations` render in Inc 3 (L3). |
| R7 | `MaintenanceWidget.refresh_data()` own DB read | `ui/maintenance/maintenance_list.py` | **NEXT-INCREMENT** | as R6 (L3). |
| R8 | `ClientsWidget.refresh_data()` / `client_details._reload_client_locally` on `data_refreshed` | `ui/clients/*` | **NEXT-INCREMENT** | server-authoritative; needs revisioned pull (L4). |
| R9 | `_switch_page` per-page refresh on tab visit | `ui/main_window.py` | **KEEP** | now the self-heal path — a tab visit republishes via the store. Not a competing derivation. |
| R10 | `_on_refresh_clicked` manual "Refresh" button | `ui/main_window.py` | **KEEP** | user-facing manual sync trigger; emits `data_refreshed` → `store.reload()` + `_run_sync()`. Not *required* for correctness after Inc 2, but a legitimate "force sync now" affordance. |
| R11 | 30 s `_sync_timer` + realtime 250 ms debounce + `_on_sync_finished` | `ui/main_window.py` | **KEEP** | network sync cadence, unrelated to local reactivity; feeds the store via `data_refreshed` on applied changes. |
| R12 | `sync/uploads.py` + `sync/engine.py` cross-thread `data_refreshed.emit()` | `sync/*` | **REQUIRED (indirect)** | background thread cannot touch the store directly (L6); queued emit → UI-thread `store.reload()`. |
| R13 | `client_list.py:265` `self.refresh_data()` (internal filter) | `ui/clients/client_list.py` | **KEEP** | in-widget filter re-render, reads committed data; not global state. |
| R14 | `reservation_list` / `maintenance_list` internal `self.refresh_data()` after their own save + tab change | `ui/*` | **KEEP (interim)** | harmless; the store fan-out also refreshes them. Redundant post-Inc-3 (R6/R7). |
| R15 | `reservation_list.py.bak.*` | `ui/reservations/` | **OBSOLETE** | stale backup file, not imported. Delete in housekeeping. |

**No competing global fleet-status derivation survives**: the only derivations
are `app.utils.fleet_status` (canonical, Increment 1) invoked once per snapshot
in `DomainStore._build_snapshot`, and `compute_local_overview` (which itself
calls `compute_fleet_counts` — same canon) invoked in the same read. Verified
by `test_domain_store.py::test_snapshot_effective_status_matches_normative_spec`
and `test_domain_store_convergence.py::test_dashboard_and_vehicles_never_disagree_after_any_mutation`.

---

## 12. EXACT REQUIREMENTS FOR INCREMENT 3

1. **`BoundaryClock`** (`desktop/app/state/boundary_clock.py`):
   - after every `DomainStore.reload()`, compute
     `next = shared.fleet_status_reference.next_boundary(reservations, maintenances, now)`;
   - arm exactly **one** `QTimer.singleShot(next - now)` (cap at e.g. 24 h);
   - on fire: `DomainStore.recompute_effective()` — re-bucket the *existing*
     snapshot rows against the new `now` with **no SQLite read and no network**
     — then bump revision + notify; re-arm.
   - Tests: freeze clock; seed a reservation ending in N seconds; assert one
     timer armed; advance; assert exactly one `revision` bump and the vehicle
     flips `RENTED → AVAILABLE`; assert zero DB/HTTP calls.
2. **Convert R6/R7** — `ReservationWidget` / `MaintenanceWidget` render from
   `snapshot.reservations` / `snapshot.maintenances` (delete their `refresh_data`
   DB reads). Removes L3.
3. **Delete `EventBus.entity_changed`** (R2, dead).
4. **Move `client_details._reload_client_locally`** off `data_refreshed` onto a
   `DomainStore` subscription (or leave until Increment 4's revisioned pull).
5. **Migrate the 7 mutation handlers** to `DomainStore.mutate()` closures
   (removes L5); keep the "no emit on failed mutation" guarantee.
6. Housekeeping: delete `reservation_list.py.bak.*` (R15).
7. Do **not** touch the sync contract (`updated_at >= since`) — that is
   Increment 4.

---

## 13. VERDICT

**INCREMENT 2 PARTIAL — the desktop now has a single canonical reactive
domain-state layer; time-driven liveness (L1) and full snapshot-rendering of
Reservations/Maintenance (L3) remain for Increment 3.**

### PROVEN (unit + integration tests, this environment)
- One canonical in-memory domain state exists (`DomainStore.snapshot`); Vehicles
  and Dashboard render **from it** and hold no competing derivation.
- Monotonic `revision`; every committed mutation → exactly one new revision.
- Subscriber notification is isolated — one throwing view never blocks or
  freezes the others (`test_one_failing_subscriber…`, `test_one_broken_view…`).
- A view that missed a publish **self-heals** on the next revision or tab visit
  (`test_one_broken_view_does_not_freeze_the_rest_and_self_heals`).
- `mutate()` is transactional: commit → publish; failure → rollback, **no**
  revision bump, **no** notification (`test_mutate_failure_rolls_back…`,
  and the untouched `test_mutation_failure_no_false_event`).
- One mutation converges Dashboard + Vehicles + Reservations + Maintenance
  with **no tab switch and no refresh-button click**
  (`test_no_refresh_button_and_no_tab_switch_needed`).
- Maintenance-wins cancellation and maintenance completion propagate to every
  view through the store, live.
- A sync-applied change (`apply_pulled_items`) converges through the **same**
  path.
- Dashboard and Vehicles are mathematically equal to the snapshot and to the
  standalone canonical computation after every mutation
  (`test_dashboard_and_vehicles_never_disagree_after_any_mutation`).
- Snapshot effective status == the Increment-1 normative spec on 14 vectors.

### PARTIALLY PROVEN
- **Cross-window** convergence is proven for all views held inside one
  `MainWindow`. A *second* desktop process converging against the same backend
  is not testable here (no deployed backend / no second instance) — it depends
  on Increment 4's revisioned pull.
- Reservations/Maintenance views converge correctly but still via their own
  committed-DB read (store-*driven*, not store-*rendered*) — see L3.

### NOT YET PROVEN / NOT ADDRESSED
- **Time-boundary liveness (L1).** A reservation/maintenance boundary crossing
  with no other activity does **not** update any view. No timer/polling shim
  was added (directive #8). → **Increment 3 (`BoundaryClock`).**
- On-device / on-Windows behaviour (no host in this environment).
- The `data_refreshed` signal is demoted but not removed (L2).

### The application is NOT "100% live" after Increment 2.
L1 alone is disqualifying. Increment 3 (`BoundaryClock` + R6/R7 conversion) is
required before any "live" claim, and Increment 4 (revisioned sync) before any
cross-client claim.

---

## 14. SAFETY CONFIRMATION

No `git reset`, `git clean`, `git restore`, `git checkout --`, `git stash drop`,
or `git push` was run. No file was deleted. No production database was touched
(all tests use throwaway SQLite / the backend test engine). HEAD is unchanged at
`df9b96d`. `stash@{0}` intact. Windows EXE / Android APK **not** rebuilt
(source + tests only; nothing required a rebuild to compile or pass).
