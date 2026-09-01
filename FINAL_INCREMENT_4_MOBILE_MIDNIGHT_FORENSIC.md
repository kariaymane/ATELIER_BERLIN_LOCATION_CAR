# FINAL — INCREMENT 4: MOBILE TEMPORAL LIVENESS + MIDNIGHT ROLLOVER

**Project:** `/home/ayman/car-rental-system`
**Date:** 2026-08-30
**HEAD:** `df9b96dfa56692845560d18995c5c83503f01140` (branch `main`, 12 commits ahead of `origin/main`, unpushed)
**Working tree:** DIRTY — prior work + Increments 1–3 + this increment. Nothing committed, stashed, reset, cleaned, or pushed.
**Predecessors:** Increments 1 (cross-runtime parity), 2 (`DomainStore`), 3 (desktop `BoundaryClock`) — all COMPLETE & GREEN, unchanged in substance.

---

## 1. WHAT INCREMENT 4 DELIVERS

| Target | Result |
|---|---|
| **A — Mobile temporal liveness** | The Android app now re-derives the CANONICAL effective vehicle status locally from reservation/maintenance intervals against `now`, driven by ONE lifecycle-safe coroutine boundary ticker. A reservation ending at 18:00 flips the phone's vehicle to `DISPONIBLE` at 18:00 with **no API call, no Room write, no manual refresh, no navigation, no UI click** — forensically proven with a real clock. |
| **B — Midnight rollover** | Local midnight (Africa/Casablanca) is now a first-class temporal boundary on **both** platforms. The Desktop `DomainStore` recomputes the dashboard period (today/week/month) revenue + rental cards at 00:00; the Mobile dashboard recomputes them locally from Room at the midnight tick. No 1-second polling anywhere. |

---

## 2. FORENSIC AUDIT (STEP 1) — findings

### Mobile, before
- `VehicleEntity.status` stored the **server-computed** effective status; there was **no local re-derivation** from intervals. A time-driven transition reached the phone only on the next sync.
- `Reservation.startDate` / `endDate` and `MaintenanceTicket.scheduledDate` were **localized display strings** (`"dd MMM yyyy, HH:mm"`) — not machine-parseable. The raw ISO edges were dropped on the floor for reservations (kept for maintenance `expected_end`/`actual_end`).
- `performanceMetricsFlow` = a `MutableStateFlow` pushed only by `refreshDashboard()` (API). No local computation, no time reactivity.
- Room flows (`Flow<List<Entity>>`) are genuinely reactive; `FleetViewModel` uses `stateIn(WhileSubscribed(5000))` — a good lifecycle-scoped collection point.
- **No suitable existing temporal abstraction.** `RealtimeSyncManager` has a 20 s fallback *poll* and a WS heartbeat — neither is a boundary scheduler.
- `minSdk = 24`, **no core-library desugaring** → `java.time` is unavailable; the codebase uses `SimpleDateFormat` + epoch-millis + `Calendar`.

### Desktop / Shared, before
- `BoundaryClock` (Increment 3) — reservation/maintenance edges only. `next_boundary_rows` did not know about date periods.
- `dashboard_cache.compute_local_overview` computed period buckets from `datetime.now(TZ)` internally — not `now`-injectable, so a temporal recompute could not roll it.

---

## 3. MOBILE — architecture

```
 Room  vehicleDao / reservationDao / maintenanceDao  (Flow<List<Entity>>)
        │
        ▼  FleetRepository
 intervalRowsFlow = combine(reservations, maintenances) → List<ReservationRow>, List<MaintenanceRow>
        │                                    (raw ISO edges: startDatetimeIso / endDatetimeIso)
        ├──────────────────────────────┐
        ▼                              ▼
 BoundaryTicker.ticks(intervalRowsFlow)         (the ONE mobile temporal mechanism)
   channelFlow {
     trySend(now)                                // prime
     intervals.collectLatest { (res, maint) ->   // sync/mutation → cancel + restart
       while (isActive) {
         nb = FleetStatus.nextBoundaryMillis(res, maint, now, includeMidnight = true) ?: break
         delayFn(nb - now)                        // sleep until the edge — NO polling
         trySend(now)
       }
     }
   }
        │  Flow<Long>  (a tick per boundary)
        ▼
 vehiclesFlow      = combine(vehicles, intervalRowsFlow, boundaryTicks) {
                       FleetRepository.deriveEffectiveVehicles(v, res, maint, now())   // PURE
                     }.distinctUntilChanged()
 localMetricsFlow  = combine(vehicles, intervalRowsFlow, boundaryTicks) {
                       FleetStatus.dashboardOverview(v, res, maint, now())             // PURE
                     }.distinctUntilChanged()
 performanceMetricsFlow = combine(localMetricsFlow, _liveMetrics) { local, api -> local ?: api }
        │
        ▼  FleetViewModel  .stateIn(viewModelScope, WhileSubscribed(5000), …)
        ▼  Compose  collectAsState()   →  recomposition
```

**Canonical status (STEP 2).** `com.example.data.fleet.FleetStatus` is a
**mechanical port of `shared/fleet_status_reference.py`** — same precedence
(`SOLD/INACTIVE > MAINTENANCE > RENTED > RESERVED > AVAILABLE`), same half-open
`[start, end)`, same open-ended-maintenance rule. It is proven identical to
Desktop / Backend / the normative spec by `FleetStatusParityTest`
(`shared/fleet_status_cases.json`, all 14 vectors). No business rule lives in
UI code. A vehicle with **no** local interval rows keeps the server status
(sparse-cache safety; a full re-sync closes that in Increment 5).

**Temporal scheduler (STEP 3).** `com.example.data.fleet.BoundaryTicker` — a
cold `channelFlow`. Guarantees, all from **structured concurrency** (no
hand-rolled bookkeeping):
- **injectable clock + delay** (`nowMillis`, `delayFn`) for virtual-time tests;
- **lifecycle-safe / no leak** — cold, runs only while collected; the ViewModel
  collects it inside `viewModelScope` with `WhileSubscribed(5000)`, so it stops
  with the last screen and restarts on return;
- **one active schedule / obsolete invalidation** — `collectLatest` on the
  interval data cancels the pending `delay` and restarts on any sync/mutation;
- **cancellable / restartable** — cancelling the collector cancels everything;
  a fresh collection re-arms;
- **no per-screen timers** — the only `delay()` in `ui/` is a 300 ms search
  debounce in `ClientsScreen`, unrelated to status.

**Datetime (STEP 4).** `FleetStatus.parseUtcMillis` mirrors `parse_datetime_utc`
(naive ISO → UTC; `Z`/offset/`.fff`/SQLite forms). All math is epoch-millis
UTC; midnight uses `Calendar` + `TimeZone.getTimeZone("Africa/Casablanca")`.
No `java.time` dependency added; no naive/aware mixing.

---

## 4. MIDNIGHT — architecture (STEP 7 / STEP 8)

`next_boundary_rows(..., include_midnight=False, tz_name="Africa/Casablanca")`
— **new optional arg**, default `False` so every existing caller is unchanged.
When `True` it also considers `next_local_midnight(now, tz)`. The Desktop
`BoundaryClock._target_boundary` and `DomainStore._build_snapshot` /
`recompute_effective` pass `include_midnight=True`; Mobile's `BoundaryTicker`
is constructed with `includeMidnight = true`.

`dashboard_cache.compute_overview_rows(reservation_rows, fleet_counts, now)` —
**new PURE function**: the today/week/month buckets keyed off
`_period_bounds(now)` (Africa/Casablanca local midnight, week starts Monday).
`compute_local_overview(session, now=None)` is now a thin adapter over it.
`DomainStore.recompute_effective` recomputes the FULL overview via this
function and publishes when `effective`, `fleet_counts`, **or `overview`**
changed — so 00:00 rolls the revenue/rental cards.

`DomainStore` contract is preserved: monotonic `revision`, per-subscriber
isolation, `mutate()` commit→publish / failure→rollback→no-publish, re-entrancy
guard. A midnight recompute that changes nothing is a silent no-op.

---

## 5. FILES CHANGED

### Mobile — new
| File | Purpose |
|---|---|
| `mobile/.../data/fleet/FleetStatus.kt` | normative port: `effectiveStatuses`, `fleetCounts`, `nextBoundaryMillis` (+midnight), `dashboardOverview`, `parseUtcMillis` |
| `mobile/.../data/fleet/BoundaryTicker.kt` | the ONE mobile temporal scheduler (cold `channelFlow`) |
| `mobile/.../test/FleetStatusParityTest.kt` | 14 shared vectors |
| `mobile/.../test/BoundaryTickerTest.kt` | 8 scheduler unit tests |
| `mobile/.../test/MobileTemporalStateTest.kt` | 6 — temporal state, multi-boundary, sync race, midnight ×2, real-clock forensic |

### Mobile — modified
| File | Change |
|---|---|
| `data/repository/FleetRepository.kt` | injectable `nowMillis` / `tickerDelay`; `intervalRowsFlow`; `boundaryTicker` + `boundaryTicks`; `vehiclesFlow` re-derives effective status locally; new pure `deriveEffectiveVehicles`; `localMetricsFlow`; `performanceMetricsFlow` prefers local; DTO mappers populate ISO edges |
| `data/local/Entities.kt` | `+ReservationEntity.startDatetimeIso/endDatetimeIso`, `+MaintenanceEntity.startDatetimeIso` |
| `data/local/AppDatabase.kt` | Room `version 7 → 8` (`fallbackToDestructiveMigration` — the cache re-bootstraps) |
| `data/model/Models.kt` | `+Reservation.startIso/endIso`, `+MaintenanceTicket.startIso` |

### Desktop — modified
| File | Change |
|---|---|
| `app/utils/fleet_status.py` | `+next_local_midnight()`; `next_boundary_rows(..., include_midnight=False, tz_name=...)` |
| `app/sync/dashboard_cache.py` | `+compute_overview_rows()` (pure, `now`-aware); `_period_bounds` tz-normalises `now`; `compute_local_overview(session, now=None)` |
| `app/state/domain_store.py` | `_build_snapshot` uses `compute_overview_rows` + `include_midnight`; `recompute_effective` recomputes full overview + publishes on overview change |
| `app/state/boundary_clock.py` | `_target_boundary` passes `include_midnight=True`; `+slack_seconds` (fire a hair *after* the edge so a real timer's early wake still sees the transition) |

### Desktop — new / adjusted tests
`test_cross_client_convergence.py` (new, 15); `test_domain_store_temporal.py` (+2 midnight);
`test_boundary_clock.py` / `test_domain_store_temporal.py` — 3 Increment-3 assertions updated
(`next_boundary` is now the midnight edge, never `None`, by design).

**No file deleted. No production DB touched. No EXE/APK rebuilt.**

---

## 6. TEST RESULTS  (all GREEN)

```
BACKEND  full suite ......................................  115 passed        ~13s
DESKTOP  full suite ......................................  212 passed      167.18s
         (195 before Inc 4  +17  = 15 test_cross_client_convergence
                                  +  2 test_domain_store_temporal midnight)
MOBILE   testDebugUnitTest ...............................   41 passed        ~38s
         (26 before Inc 4  +15  = 8 BoundaryTickerTest
                                 + 1 FleetStatusParityTest (14 vectors)
                                 + 6 MobileTemporalStateTest)

Cross-runtime parity (Inc 1):
  backend  test_fleet_status_crossruntime .......... 14 passed
  desktop  test_fleet_status_crossruntime .......... 14 passed
  mobile   FleetStatusParityTest ................... 1 test / 14 vectors passed
  desktop  test_cross_client_convergence ........... 15 passed

Increment-3 (desktop temporal) still green:
  test_boundary_clock ........................... 12
  test_domain_store_temporal ................... 10 (+2 midnight)

Increment-4 mobile:
  BoundaryTickerTest ........................... 8
  MobileTemporalStateTest ..................... 6  (incl. real-clock forensic + midnight)
```

---

## 7. FORENSIC PROOF

### Mobile — real clock (`MobileTemporalStateTest.REAL clock — vehicle frees itself with zero user action`)

```
seed  vehicle "veh-real", reservation ending in ~2s real time
observe:  status == EN_LOCATION            (RENTED)
... DO NOTHING — no API, no Room write, no refresh, no navigation, no UI click ...
after the real boundary:
  boundary timestamp : 2026-08-30T03:21:03
  old status         : EN_LOCATION
  new status         : DISPONIBLE          (AVAILABLE)
  emission count     : 2
  Room row           : status == "RENTED"  (never touched)
```

### Mobile — virtual clock (deterministic)
`reservation end frees the vehicle purely because time passed` — `EN_LOCATION`
→ advance virtual time to the exact edge → `DISPONIBLE`; emissions == exactly
`[EN_LOCATION, DISPONIBLE]`; Room untouched.

### Midnight — desktop
`test_local_midnight_rolls_the_dashboard_period_cards`: at 23:59:59 local
`today_revenue == 500`; advance to 00:00:01, `recompute_effective()` (NO SQLite,
NO network) → `today_revenue == 0`, `week_revenue == 500` (same week), exactly
one publish, `revision N → N+1`. A no-change midnight recompute → silent no-op.

### Midnight — mobile
`dashboard metrics flow re-emits at the midnight tick with no mutation`: today
revenue `500 → 0` when virtual time crosses 00:00 Africa/Casablanca, driven by
the `BoundaryTicker`, no Room write.

### Cross-client
`test_two_desktop_stores_derive_identical_state`: two independent `DomainStore`
instances, same data + same `now` → byte-identical `effective`, `fleet_counts`,
`overview`, `next_boundary`; advance both → still identical. Plus all 4 runtimes
(Desktop-A, Desktop-B, Mobile, Backend) assert against the one
`shared/fleet_status_cases.json` — including `next_boundary` parity
(`test_cross_client_convergence`).

---

## 8. MULTIPLE BOUNDARIES / SYNC RACE (STEP 5 / STEP 6)

`BoundaryTickerTest.multiple boundaries fire in order, one at a time, never polling`:
3 edges (12:05 / 12:10 / 12:15) → **exactly 3 boundary ticks** (+1 prime),
`maxConcurrentDelays == 1`.

`sync with an earlier boundary invalidates the pending wait`: while waiting for
an 18:00 edge, a sync brings a 13:30 edge → `collectLatest` cancels the old
wait → tick fires at **13:30**, not 18:00.

`MobileTemporalStateTest.a sync that lands near a boundary — newest data wins`:
a sync extends the reservation 4 s before its old edge → the old 12:00:05 edge
does nothing, the vehicle stays `RENTED`, and frees only at the new 13:00 edge.

---

## 9. REMAINING LIMITATIONS

| # | Limitation | Impact | Fix |
|---|---|---|---|
| L3 (carried) | Desktop Reservations/Maintenance widgets still render via their own `refresh_data()` DB read (store-driven, converge on every revision incl. temporal — no status staleness; list-cosmetic edges only). | cosmetic | Inc 5 |
| L2 (carried) | Desktop `data_refreshed` signal still exists as a trigger. | none functional | Inc 5 |
| M1 | Mobile: a vehicle with **no** local interval rows keeps the server status (never re-derived). If the server said `RENTED` but the reservation row never synced, the phone won't free it on time. | needs sparse cache | Increment 5 (versioned full sync) |
| M2 | Mobile `refreshDashboard()` (API) is now a warm fallback shadowed by the local computation. It still runs on sync; the local value wins. Mirrors Desktop. | none (local is canonical) | — |
| M3 | Mobile: no on-device / instrumentation run in this environment (JVM/Robolectric unit tests only). No signed APK. | on-device unverified | device rig |
| M4 | Cross-client convergence is proven by all runtimes asserting one normative vector set + two independent Desktop stores. A **live** three-client rig (2 desktops + 1 phone against a deployed backend) is not available here. | not live-proven | Inc 5 + rig |
| L14 | Month/year period rollover: `_period_bounds` handles month correctly (`month_start`/`month_end` via calendar), and mobile `periodBounds` handles month via `Calendar.add(MONTH, 1)`. Year is implicit in month. A dedicated month-boundary test at 31 Dec 23:59 → 1 Jan is not yet written (the mechanism covers it). | untested edge | quick follow-up |

---

## 10. VERDICT

### Mobile temporal liveness — **FORENSICALLY PROVEN**
Real clock: `RENTED → AVAILABLE` because ~2 s passed, zero user action, zero
Room mutation, zero API call. One canonical status authority (`FleetStatus`,
parity-proven), one temporal mechanism (`BoundaryTicker`), lifecycle-safe,
multi-boundary correct, sync-race correct, no per-screen timers, no polling.

### Midnight rollover — **PROVEN** (desktop + mobile)
Local midnight is a real temporal boundary on both platforms; the dashboard
period cards recompute at 00:00 with no user action; publish only on real
change.

### Whole-product honest position:

**VERDICT: NOT YET 100% LIVE**
**BLOCKER: cross-client *live* convergence + mobile sparse-cache completeness (Increment 5).**

- The **temporal mechanism** is complete and proven on all three runtimes
  (desktop forensic in Inc 3, mobile forensic + midnight here).
- What is **not** yet proven end-to-end:
  1. a **live** rig — two desktop instances + one phone against the deployed
     backend, all converging on a purely-temporal transition (no rig here);
  2. mobile **sparse-cache** completeness — a vehicle whose interval rows never
     reached the phone is not re-derived (M1); the versioned full-sync of
     Increment 5 closes this;
  3. carried desktop items L2/L3.

The decisive per-runtime requirement — *time passes → state changes
automatically → observers converge, with no user action / refresh / sync / DB
mutation* — is now **met and forensically proven on desktop AND mobile**.
Increment 5 (versioned sync) is required before the whole distributed product
can honestly be called 100% live.

---

## 11. SAFETY CONFIRMATION

No `git reset` / `clean` / `restore` / `checkout` / `stash drop` / `push`. No
file deleted. No production database touched (tests use throwaway SQLite / the
backend test engine / in-memory constructs). No EXE rebuilt. The APK was **not**
rebuilt — `git status` / `git diff --stat` before and after confirm only the
files in §5 changed. HEAD unchanged at `df9b96d`; `stash@{0}` intact.
