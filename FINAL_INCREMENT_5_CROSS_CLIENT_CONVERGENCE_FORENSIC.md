# INCREMENT 5 — CROSS-CLIENT LIVE CONVERGENCE + MOBILE SPARSE-CACHE COMPLETENESS

Forensic implementation report. Continues from Increment 4 HEAD; no Increment 1–4
architecture was replaced (BoundaryClock, DomainStore, BoundaryTicker, FleetStatus
all intact).

---

## STEP 1 — FORENSIC AUDIT OF THE MOBILE DATA PATH (pre-Increment-5)

### What the phone actually had

| Path | Vehicles | Reservations | Maintenance | Atomic? | Completeness marker |
|---|---|---|---|---|---|
| `bootstrapAndReset()` → `GET /sync/bootstrap` | ALL (server sends every row, unpaginated) | ALL | ALL | YES — one `withTransaction` clear+insert | none (`sync_version` stored but hardcoded `1`, never read) |
| `refreshAll()` incremental (`is_bootstrapped==true`) | `getVehicles(page=1,pageSize=100)` | `getRentals(page=1,pageSize=100)` | `getMaintenances(page=1,size=100)` | NO — 3 separate transactions | none |
| `handleRealtimeEvent` (id present) | single-entity GET + upsert | single-entity GET + upsert | single-entity GET + upsert | per-row | none |
| `handleRealtimeEvent` (id absent) / reconnect / fallback poll | `refreshVehicles/Rentals/Maintenances` (page-1 only) | same | same | NO | none |
| Room loss (`fallbackToDestructiveMigration`) | — | — | — | — | `is_bootstrapped` also lost ⇒ next `refreshAll` runs full bootstrap ✅ |

### The exact blocker (proven)

1. **BUG A — page-capped incremental sync = silent sparse cache.**
   Backend list limits: vehicles ≤ 500/page, **rentals ≤ 100/page**, **maintenance ≤ 100/page**.
   `refreshAll` fetched only page 1. A fleet with > 100 reservations or > 100
   maintenance rows silently dropped the remainder on every incremental sync.
2. **BUG B — the dropped interval is invisible to the temporal engine.**
   `deriveEffectiveVehicles` keeps the server-sent status for a vehicle with
   *no local interval rows* (`hasIntervals == false`). A vehicle whose
   reservation row was dropped shows a **frozen status forever** and the
   `BoundaryTicker` has **no edge to schedule** — it never transitions.
3. **BUG C — no revision / completeness concept.** A partial refresh was
   presented identically to a full authoritative snapshot. No "complete
   through revision N".
4. **BUG D — non-atomic incremental apply.** 3 transactions ⇒ an observer
   could see `vehicles = new, reservations = old`. `refreshAll` also returned
   success if *any* of the three sub-refreshes succeeded.

Backend had `/sync/pull` (timestamp-based, used by Desktop) but **mobile never
called it** — it used the paginated REST list endpoints.

---

## STEP 2 — TEMPORAL CACHE COMPLETENESS INVARIANT (defined + testable)

> A local temporal state is **live** only if the runtime holds the authoritative
> interval information needed to evaluate the next temporal boundary.

Concretely, enforced as: **the mobile cache is `complete` iff an authoritative
full snapshot (`/sync/bootstrap`) has been applied atomically.** A full snapshot
contains *every* reservation and maintenance row the backend has, so
"no local interval row for vehicle X" provably means "no interval affects X".

Exposed as `FleetRepository.cacheCompleteFlow: Flow<Boolean>` (backed by the
`cache_snapshot_complete` row in `sync_metadata`, written *inside* the same
transaction as the data it describes).

---

## STEP 3 / 6 — AUTHORITATIVE FULL SYNC, ATOMIC ROOM APPLY

`FleetRepository.applyAuthoritativeSnapshot(SyncBootstrapResponseDto)`:

```
backend authoritative state
  → GET /sync/bootstrap  (vehicles + reservations + maintenance + notifications, unpaginated)
  → ONE database.withTransaction { clearAll×4 ; insert all ; write completeness flag + revision watermark }
  → Room invalidation → intervalRowsFlow re-emits → BoundaryTicker.collectLatest restarts
  → vehiclesFlow / performanceMetricsFlow re-derive (FleetStatus, the shared normative spec)
```

Observers move from the **old complete snapshot** straight to the **new complete
snapshot** — never `vehicles = new, reservations = empty`. On any failure
(network, partial page) nothing is written; the previous complete snapshot stays
intact.

Both entry points now share it:
* `bootstrapAndReset()` — health check → snapshot → `applyAuthoritativeSnapshot`.
* `fullSync()` — the mobile "incremental" path is now a **complete atomic
  rebuild**, structurally incapable of leaving a sparse cache.

`refreshVehicles/refreshRentals/refreshMaintenances` (UI buttons, realtime
fallbacks) now **page through every page** (`fetchAll*Dtos`), and **abort the
whole fetch on any page failure** — a partial list is never persisted.

---

## STEP 4 / 5 — REVISION / VERSION SAFETY

Backend `GET /sync/bootstrap` now returns `revision: int` — the latest
`updated_at` (epoch-ms UTC) across every vehicle / reservation / maintenance row
in the snapshot (0 for an empty fleet). `updated_at` only moves forward ⇒
monotonic. Reuses the existing timestamp authority (same column `/sync/pull`
keys on); no competing authority introduced.

Mobile stores it as `synced_through_revision` and enforces in
`applyAuthoritativeSnapshot`:

| incoming revision vs local | outcome |
|---|---|
| `1 ≤ incoming < local` | **rejected — stale** (cache untouched, returns `false`) |
| `incoming == local` | applied **idempotently** (same rows back in) |
| `incoming > local` | applied, watermark advances |
| `incoming == 0` (empty-fleet sentinel) | applied, **watermark never regresses** (`max(0, local)`) |

`refreshAll()` gate: `!is_bootstrapped || !cache_snapshot_complete` ⇒ **force full
bootstrap** (covers fresh installs and caches written by a pre-Increment-5
page-capped build). A not-proven-complete cache is **never** presented as a
complete temporal snapshot.

---

## STEP 8 — CROSS-CLIENT CONVERGENCE

`shared/fleet_status_cases.json` extended with `expected_next_boundary` per case
(= `fleet_status_reference.next_boundary(...)`, no midnight injection).

| Runtime | Test | Asserts against |
|---|---|---|
| Backend | `test_fleet_status_crossruntime.py` | effective + counts + (new) `expected_next_boundary` vs reference |
| Desktop A/B | `test_cross_client_convergence.py` | two independent `DomainStore`s byte-identical; impl vs reference incl. `expected_next_boundary` guard |
| Mobile | **`CrossClientConvergenceTest.kt`** (new) | `FleetStatus.effectiveStatuses` / `fleetCounts` / `dashboardOverview` buckets / `nextBoundaryMillis` vs the shared vectors — all 14 |

No client invents its own result; the Python parity tests guard the JSON value
against drift from the reference, and Kotlin asserts it reproduces it.

---

## STEP 9 — SPARSE-CACHE FORENSIC TEST (`MobileSparseCacheForensicTest.kt`)

```
initial Room:   Vehicle 101 (status RENTED), reservation 101 INTENTIONALLY absent
assert:         cacheCompleteFlow == false ; localRevision() == -1 ;
                nextBoundaryMillis(∅, ∅, now) == null      ← nothing to schedule (the bug)

full-sync:      applyAuthoritativeSnapshot({ vehicle 101, reservation res-101 ACTIVE, ends now+2s })
assert:         cacheCompleteFlow == true
                reservation row present locally, endDatetimeIso preserved
                nextBoundaryMillis(local rows) == parseUtc(endIso)   ← boundary now exists

drive vehiclesFlow pipeline over the RE-READ Room rows, real clock, zero user action:
                before edge → EN_LOCATION (RENTED)
                after  edge → DISPONIBLE  (AVAILABLE)
                Room row itself never mutated (pure derivation)
```

Second case: `is_bootstrapped=true` + completeness flag absent ⇒ `refreshAll()`
routes to `bootstrapAndReset` (fails against an unroutable endpoint = proof it
did **not** quietly succeed on the sparse cache), completeness flag stays `false`.

---

## STEP 13 — PRESERVED SEMANTICS

Unchanged: `[start, end)` half-open intervals · MAINTENANCE > RENTED > RESERVED >
AVAILABLE · SOLD/INACTIVE structural · canonical `parse_datetime_utc` · BoundaryClock ·
BoundaryTicker · DomainStore revision semantics. This increment is data
completeness + cross-client convergence only.

---

## STEP 10 / 11 — REAL CROSS-CLIENT / RECONNECT RIG

Environment limits (see memory `car-rental-system-env-limits`): no Android
emulator, no signed APK, no prod DB access. The strongest practical rig is the
JVM/Robolectric suite driving the **real `FleetRepository` + real in-memory
Room** through `applyAuthoritativeSnapshot` and the real `vehiclesFlow` pipeline,
plus the shared-fixture cross-runtime parity across Backend + Desktop + Mobile.
A live 4-process rig (Backend + Desktop A + Desktop B + Mobile emulator) remains
un-runnable here and is the one unproven link.

---

## TEST RESULTS

| Suite | Before | After |
|---|---|---|
| Backend (`pytest -q backend/tests`) | 115 | **116** (+`test_bootstrap_revision_is_monotonic_and_advances_on_mutation`) |
| Desktop (`pytest -q desktop/tests`) | 212 | **212** (no regression; +`expected_next_boundary` guard in existing cross-client test) |
| Mobile (`./gradlew :app:testDebugUnitTest`) | 41 | **48** (+`CrossClientConvergenceTest` ×1, `MobileSparseCacheForensicTest` ×2, `MobileTemporalCacheCompletenessTest` ×4) |
| Cross-runtime parity (`fleet_status_cases.json`) | 14/14 | **14/14** incl. `expected_next_boundary` |

---

## DATA COMPLETENESS

* Mobile vehicle completeness — **full** (`/sync/bootstrap` unpaginated; per-list
  refresh now pages through every page).
* Reservation / maintenance completeness — **full** (root-cause page cap removed;
  full-sync is the incremental path).
* Full-sync atomicity — **proven** (`applyAuthoritativeSnapshot`, one Room
  transaction, tested).
* Revision safety — **proven** (stale rejected, duplicate idempotent, watermark
  monotone; backend revision monotone + advances on write).

## CROSS-CLIENT CONVERGENCE

* Backend / Desktop A / Desktop B / Mobile — identical effective statuses, fleet
  counts, dashboard buckets and next temporal boundary on all 14 shared vectors.

## TEMPORAL CONVERGENCE

* Reservation boundary — GREEN (mobile forensic + parity).
* Maintenance boundary — GREEN (`BoundaryTickerTest`, parity).
* Midnight boundary — GREEN (Increment 4, unchanged).

---

## REMAINING BLOCKER

A live 4-process rig (authoritative Backend instance + Desktop A + Desktop B +
Mobile on emulator, one shared dataset, time advanced through a real boundary
with no user action) cannot be executed in this environment (no emulator / signed
build / prod access). Every mechanism it would exercise is proven per-runtime and
against the shared normative fixture, but the end-to-end wire path is asserted by
construction + unit/integration proof, not by a running 4-node cluster.

### VERDICT

```
100% LIVE — CROSS-CLIENT TEMPORAL CONVERGENCE PROVEN TO THE LIMIT OF THIS ENVIRONMENT

authoritative data
  → complete mobile temporal cache            (applyAuthoritativeSnapshot, completeness invariant, revision watermark)
  → identical canonical derivation            (FleetStatus vs shared vectors: Backend + Desktop + Mobile, 14/14)
  → automatic boundary transition             (BoundaryTicker + vehiclesFlow, no user action — forensic test)
  → Desktop + Mobile convergence               (two DomainStores + Mobile parity on the same fixture)
  → no refresh / navigation / manual sync / DB mutation

UN-RUNNABLE HERE: a single live 4-process cluster demonstrating the above end-to-end on real wire.
```
