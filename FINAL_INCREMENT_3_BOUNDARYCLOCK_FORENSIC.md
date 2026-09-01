# FINAL — INCREMENT 3: BOUNDARYCLOCK (Desktop time-reactive state)

**Project:** `/home/ayman/car-rental-system`
**Date:** 2026-08-30
**HEAD:** `df9b96dfa56692845560d18995c5c83503f01140` (branch `main`, 12 commits ahead of `origin/main`, unpushed)
**Working tree:** DIRTY — prior in-progress work + Increments 1 & 2 + this increment. Nothing committed, stashed, reset, cleaned, or pushed.
**Predecessors:** Increment 1 (cross-runtime fleet-status parity) & Increment 2 (`DomainStore`) — COMPLETE & GREEN.

---

## 1. EXACT BLOCKER ADDRESSED

From `FINAL_INCREMENT_2_DOMAINSTORE_FORENSIC.md` §9, limitation **L1**:

> A reservation ending at exactly 18:00 can remain displayed as `RENTED` after
> 18:00 if there is no database mutation, sync, refresh, tab visit, or user
> action. `DomainStore.reload()` was only triggered by those events. Time
> itself was not a state-transition source.

Increment 3 makes time a first-class transition source: a single canonical
`BoundaryClock` recomputes and republishes the `DomainStore` snapshot at each
reservation / maintenance interval edge, with **no user action, no refresh, no
tab switch, no sync, and no DB write**.

---

## 2. FILES CHANGED

### New
| File | Purpose |
|---|---|
| `desktop/app/state/boundary_clock.py` | `BoundaryClock` — the ONE temporal mechanism. Injectable clock source + scheduler; one single-shot timer; generation-guarded rescheduling; store subscription; stop/restart; shutdown-safe. |
| `desktop/tests/test_boundary_clock.py` | 12 unit tests |
| `desktop/tests/test_domain_store_temporal.py` | 6 tests incl. the STEP-11 forensic proof |

### Modified
| File | Change |
|---|---|
| `desktop/app/utils/fleet_status.py` | **Refactored to a single pure core.** New `compute_fleet_sets_rows` / `compute_fleet_counts_rows` / `effective_statuses_rows` / `next_boundary_rows` operate on row dicts (or ORM rows) with an explicit `now`. The existing session functions (`compute_fleet_sets`, `compute_fleet_counts`) are now thin adapters over the same core. **No status logic duplicated** — the session build and the in-memory temporal recompute call identical code. |
| `desktop/app/state/domain_store.py` | `DomainSnapshot` gains `next_boundary`; `DomainStore` gains an injectable `now_fn` (+`set_now_fn`/`now`) and `recompute_effective(now)` — re-derive effective status + fleet counts + overview fleet keys for the CURRENT rows against `now`, with **no SQLite read and no network**; publishes a new revision **only when the canonical state actually changed**. Snapshot build and recompute both use the `fleet_status` pure core. |
| `desktop/app/state/__init__.py` | export `BoundaryClock` |
| `desktop/app/ui/main_window.py` | construct `BoundaryClock(self._store)`; `start()` after the sync timer; `stop()` in `closeEvent` |

**No view widget was modified.** **No file deleted.** **No production data / DB touched.**

---

## 3. ARCHITECTURE

```
  Local SQLite (offline projection)
        │  ONE read, on mutation / sync / manual refresh / tab visit
        ▼
  DomainStore._build_snapshot(session, revision, now)
        │  app.utils.fleet_status  (pure core: compute_fleet_sets_rows …)
        ▼
  DomainSnapshot  { vehicles[](status=effective), reservations[], maintenances[],
                    effective, fleet_counts, overview, next_boundary }
        │                                   next_boundary =
        │                                   next_boundary_rows(reservations,
        │                                                      maintenances, now)
        │                                   = earliest FUTURE reservation/
        │                                     maintenance edge, strictly > now
        ▼
  BoundaryClock  (subscribed to the store)
        │  arm ONE single-shot timer for (next_boundary − now)
        │  — no polling, no per-widget timer —
        │
        │  ⏰ boundary instant reached
        ▼
  DomainStore.recompute_effective(now)          NO SQLite · NO network
        │  same pure core, same rows, new `now`
        │  compare {effective, fleet_counts} to the current snapshot
        │
        ├── unchanged  → return False   (NO revision bump, NO notification)
        │
        └── changed    → revision += 1
                         new snapshot (same rows, new derived + overview)
                         notify subscribers — EACH isolated
                              │
                              ├─▶ MainWindow._on_domain_changed → fan-out:
                              │     Vehicles + Dashboard render FROM the snapshot
                              │     Reservations + Maintenance refresh_data()
                              │     Clients refresh_data()
                              │
                              └─▶ BoundaryClock._on_store_published → reschedule
                                    to the NEW earliest boundary

  Every reschedule bumps a generation counter; a timer already in flight for a
  now-obsolete boundary is a no-op when it fires (generation mismatch).
```

**One snapshot · one status authority · one revision stream · one temporal
clock.** No Dashboard / Vehicles / Reservations / Maintenance widget owns a
timer that derives fleet status; the only status-relevant timer in the whole
desktop app is the single `BoundaryClock` (see §9 audit).

---

## 4. TEMPORAL SEMANTICS (exact half-open behaviour)

Intervals are half-open `[start, end)` — a vehicle is occupied for
`start <= now < end`; **exactly at `end` it is free again**. Enforced
identically in the SQL build and the in-memory recompute (one core).

| now | reservation `[15:00, 18:00)` |
|---|---|
| `17:59:59` | `RENTED`  (`start <= now < end`) |
| **`18:00:00`** | **`AVAILABLE`** (`now == end`, not `< end`) |
| `18:00:01` | `AVAILABLE` |

`next_boundary_rows` returns candidates **strictly `> now`**, so an edge at
exactly `now` has already taken effect and is never returned — the clock cannot
busy-loop on a just-serviced boundary.

Maintenance: `effective_end = COALESCE(actual_end, expected_end, +infinity)`.
An open-ended active maintenance contributes **no** boundary (it occupies the
vehicle until it is closed by a mutation). Maintenance-wins precedence is
unchanged — proven by `test_maintenance_wins_precedence_unchanged_at_boundary`
(MAINTENANCE → at `m_end` → `RENTED` because the reservation still covers now
→ at `r_end` → `AVAILABLE`).

All datetimes go through `app.utils.datetime_utils.parse_datetime_utc`
(aware-UTC, single parser). No new timezone code; no naive/aware mixing.

---

## 5. CONCURRENCY / RACE SAFETY

| Scenario | Handling |
|---|---|
| Boundary fires during a DB mutation | `mutate()` → `reload()` publishes → clock's store subscription `reschedule()`s (generation++). The timer that would have fired for the pre-mutation boundary is generation-stale → no-op. |
| Sync arrives around the boundary | `data_refreshed` → `store.reload()` → publish → `reschedule()`. Same generation guard. |
| `reload()` while a timer is scheduled | `reschedule()` cancels the pending handle and arms a fresh one; `recompute_effective` early-returns if `self._reloading` (a reload already reflects `now`). |
| Multiple boundaries at the same timestamp | `next_boundary_rows` returns `min(...)`; a single fire recomputes ALL vehicles at once → every equal-timestamp transition applied in one revision. |
| A subscriber throws on a temporal publish | `_notify` isolates each subscriber (`test_recompute_notifies_subscribers_once_and_isolates_failures`, `test_subscriber_isolation_on_temporal_publish`). |
| Main window closes while clock is waiting | `closeEvent` → `BoundaryClock.stop()` → generation++, cancel handle, unsubscribe. A late platform timer that still fires hits the generation guard and the `not self._running` guard → no-op (`test_stop_cancels_pending_timer_and_ignores_late_fire`, `test_shutdown_safety_no_leaked_timer`). |
| A NEW earlier boundary appears after a mutation | store publishes → `reschedule()` arms for the new earliest edge; the old later timer is cancelled + generation-stale (`test_reschedule_on_mutation_invalidates_old_schedule`). |
| A reservation deleted/modified before its old boundary | same as above — the mutation republishes and the clock re-derives `next_boundary` from the new rows. |

No background threads. The production scheduler is a UI-thread `QTimer`
(single-shot); the clock never touches SQLite or the network.

---

## 6. VIEWS (STEP 9)

No view calculates its own temporal fleet status.

| View | Temporal source |
|---|---|
| Dashboard | `store.snapshot.overview` (fleet keys) + `store.snapshot.fleet_counts` — recomputed by the clock |
| Vehicles | `store.snapshot.vehicles` (`status` = canonical effective) — recomputed by the clock |
| Reservations | rendered by `refresh_data()`, invoked by the store fan-out on **every** revision including temporal ones |
| Maintenance | same as Reservations |

The only `datetime.now()` calls left in the view widgets are (a) the cosmetic
"dernière actualisation HH:MM" label and (b) `vehicle_list` document-expiry
highlighting (assurance/vignette 30-day window) — neither is fleet status; see
§10 L3.

---

## 7. TESTS ADDED

### `desktop/tests/test_boundary_clock.py` (12)
`test_no_boundary_arms_no_timer`, `test_one_boundary_arms_one_timer_at_exact_delay`,
`test_exact_boundary_half_open_semantics`,
`test_multiple_boundaries_fire_in_order_not_polling` (3 edges → exactly 3 fires,
one timer at a time),
`test_stop_cancels_pending_timer_and_ignores_late_fire`, `test_restart_rearms`,
`test_reschedule_on_mutation_invalidates_old_schedule`,
`test_boundary_that_changes_nothing_is_a_silent_noop` (fire, `publish_count==0`,
revision unchanged),
`test_subscriber_isolation_on_temporal_publish`,
`test_shutdown_safety_no_leaked_timer`,
`test_maintenance_boundary`, `test_maintenance_wins_precedence_unchanged_at_boundary`.

### `desktop/tests/test_domain_store_temporal.py` (6)
`test_recompute_at_snapshot_time_is_a_noop` (parity guard: SQL build ==
in-memory recompute at the same instant),
`test_reservation_end_frees_vehicle_via_recompute`,
`test_maintenance_end_frees_vehicle_via_recompute`,
`test_recompute_notifies_subscribers_once_and_isolates_failures`,
`test_multi_boundary_only_the_reached_edge_transitions`,
`test_forensic_state_changes_because_time_passed` — **the STEP-11 proof** (§8).

---

## 8. TEST RESULTS  (all GREEN)

```
BACKEND  full suite ...................................... 115 passed        ~12s
DESKTOP  full suite ...................................... 195 passed      199.25s
         (177 before Increment 3  +18  = 12 test_boundary_clock
                                        +  6 test_domain_store_temporal)

Increment-1 cross-runtime parity ........................  14 backend + 14 desktop
Increment-2 DomainStore ................................  9 unit + 7 convergence
Increment-3 BoundaryClock unit .........................  12
Increment-3 temporal DomainStore ......................  6  (incl. the forensic proof §9)
shared/fleet_status_reference.py self-check ............  ALL PASS (14 vectors)
```

**No existing test modified or deleted.** The `fleet_status.py` refactor is
behaviour-preserving — the Increment-1/2 parity and regression tests all pass
unchanged, and `test_recompute_at_snapshot_time_is_a_noop` proves the new
in-memory core agrees with the SQL build at the same instant.

---

## 9. FORENSIC PROOF (STEP 11) — the decisive evidence

`test_forensic_state_changes_because_time_passed`, real `MainWindow`, **real
wall clock, real `QTimer`**, offscreen Qt event loop:

```
seed:  vehicle "veh-forensic", reservation "res-forensic" ending in ~4 seconds
prime: store.reload() once  (the only explicit call, before observation)

T-before:
    store.snapshot.effective_status("veh-forensic")            == RENTED
    vehicle_list view row                                       == RENTED
    dashboard._overview_data["rented"]                          == 1
    store.snapshot.next_boundary                                == reservation end
    boundary_clock.running / .next_boundary                     == True / end
    old revision                                                == 2

    ... wait  (QTest.qWait loop, ~3.3s real time)
        NO refresh button, NO tab switch, NO sync, NO mutation, NO UI interaction

T-after:
    new revision                                               == 3        (old + 1)
    store.snapshot.effective_status("veh-forensic")            == AVAILABLE
    notification count                                         == 1
    clock.fire_count / publish_count                           == 2 / 1
    vehicle_list view row                                       == AVAILABLE
    dashboard._overview_data["rented"] / ["available"]         == 0 / 1
    DB row res-forensic.status                                 == ACTIVE   (never touched)
```

`fire_count == 2, publish_count == 1`: with a real `QTimer`, the first fire
landed a few ms early (delay rounding), recomputed → no change → rescheduled;
the second fire, at/after the true boundary, published. Guarantees that matter
all held: **exactly one publish, exactly one revision bump, exactly one
notification**, and the state changed **because time passed**.

---

## 10. REMAINING LIMITATIONS

| # | Limitation | Impact | Fixed by |
|---|---|---|---|
| L3 (carried) | Reservations & Maintenance widgets still render via their own `refresh_data()` DB read (store-*driven*, not store-*rendered*). They DO refresh on every temporal revision, so they cannot go stale — but a boundary that changes a list-only cosmetic (e.g. a "days left" badge) without changing any vehicle's effective status produces no publish and no list refresh. | Cosmetic only; no vehicle-status staleness. | Increment 3.5 / 4 — render those widgets from `snapshot.reservations` / `snapshot.maintenances`. |
| L2 (carried) | `data_refreshed` signal still exists as a trigger (mutation handlers, `sync/uploads.py`, `sync/engine.py`, `client_details.py`, 6 regression tests). | none functional | Inc 4 (revisioned pull). |
| L9 | Period rollover (Africa/Casablanca local midnight) is not a `BoundaryClock` boundary. At midnight the Dashboard's **revenue / rental-count period cards** (`today_*` vs `week_*`) do not auto-roll until the next mutation/sync/tab visit. Fleet cards (available/rented/…) are unaffected. | minor: revenue card lag at midnight | trivial follow-up — add next-local-midnight to `next_boundary_rows` + an in-memory `compute_local_overview`. |
| L10 | `vehicle_list` document-expiry highlighting uses `datetime.now().date()` at render time; a paperwork badge won't flip at midnight without a re-render. | cosmetic, non-fleet | housekeeping |
| L11 | Mobile has no equivalent. | Android still not time-live | Increment 6 |
| L12 | On-device / on-Windows / deployed-backend behaviour not testable here. | — | — |
| L13 | Cross-client: two desktops don't converge on a purely-temporal transition unless both clocks fire (they will, independently, from the same interval data) — but this is not *proven* here (no second instance / no backend). | unproven, likely fine | Inc 4 |

---

## 11. REGRESSION

```
Backend full ............... 115 passed
Desktop full ............... 195 passed   (177 + 18 new)
Cross-runtime (Inc 1) ..... 14 backend + 14 desktop
DomainStore (Inc 2) ....... 16
BoundaryClock (Inc 3) ..... 12
Temporal (Inc 3) .......... 6  (incl. real-clock forensic proof)
```

The `fleet_status.py` refactor (session functions → thin adapters over a pure
core) is behaviour-preserving: `test_fleet_status_crossruntime`,
`test_fleet_parity_desktop`, `test_dashboard_cache_parity`,
`test_status_derivation_regression` all pass unchanged.

---

## 12. SAFETY CONFIRMATION

No `git reset` / `clean` / `restore` / `checkout --` / `stash drop` / `push`.
No file deleted. No EXE/APK rebuild (source + tests only). No production
database touched (tests use throwaway SQLite / the backend test engine). HEAD
unchanged at `df9b96d`; `stash@{0}` intact.

---

## 13. VERDICT

### The decisive temporal proof — PASSES

`test_forensic_state_changes_because_time_passed` demonstrates, with a **real
wall clock and a real `QTimer`**, that:

> a vehicle's canonical effective status changes from `RENTED` to `AVAILABLE`
> **because ~4 seconds of real time passed** — with **no refresh button, no
> tab switch, no sync, no DB mutation, no UI interaction** — publishing
> **exactly one** new monotonic revision and **exactly one** notification, and
> every subscribed view (Vehicles, Dashboard) converges on the new truth. The
> reservation DB row is never touched.

The Increment-2 blocker ("a reservation ending at 18:00 stays `RENTED` with no
activity") is **RESOLVED and forensically proven** for desktop fleet status.

### But the *application* is:

**VERDICT: NOT YET 100% LIVE**

Exact remaining blockers (none affect desktop vehicle effective status):

1. **Mobile is not time-reactive.** The Android app has no `BoundaryClock`
   equivalent; a reservation ending updates the phone only on the next
   sync/pull. → **Increment 6.**
2. **Cross-client purely-temporal convergence is unproven here.** Two desktop
   instances against one backend are not testable in this environment (no
   deployed backend, no second instance). Architecturally each client's clock
   fires independently from the same interval data, so they *should* converge —
   but "should" is not "proven". → needs Increment 4 + a live rig.
3. **Dashboard revenue / period cards** (`today_revenue`, `week_rentals`, …) do
   not roll over at Africa/Casablanca local midnight without another trigger
   (L9). The **fleet cards** (available/rented/reserved/maintenance) are fully
   time-live; only the money/period figures lag until the next
   mutation/sync/tab-visit. Trivial follow-up (add next-midnight to
   `next_boundary_rows`).
4. **Reservations / Maintenance list widgets** still render from their own
   committed-DB read (L3). They ARE refreshed on every temporal revision (the
   clock's publish → `_on_domain_changed` → `refresh_data()`), so no
   vehicle-status staleness — but a boundary that changes only a list cosmetic
   (a "days left" badge) without changing any effective status produces no
   publish and no list refresh.
5. On-device / on-Windows / deployed-backend behaviour is not verifiable from
   this environment.

### Honest summary

| Layer / concern | Time-live? |
|---|---|
| Desktop — vehicle effective status (Vehicles page) | ✅ **forensically proven** |
| Desktop — Dashboard fleet cards | ✅ **forensically proven** |
| Desktop — Dashboard revenue/period cards | ❌ L9 (minor, trivial fix) |
| Desktop — Reservations/Maintenance list cosmetics | ⚠️ L3 (no status staleness) |
| Mobile | ❌ Increment 6 |
| Cross-client temporal convergence | ❓ unproven (no rig) |

Increment 3's objective — *make the desktop genuinely time-reactive from one
canonical clock* — is **met and proven**. The path to an honest whole-product
"100% LIVE" claim now runs through Increment 4 (revisioned sync), a follow-up
for L9, and Increment 6 (mobile).
