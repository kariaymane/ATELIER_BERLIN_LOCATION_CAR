# Dashboard Canonical Source-of-Truth — Architecture Review

**Reviewer role:** Principal Architect / independent senior reviewer
**Repository:** `/home/ayman/car-rental-system`
**HEAD at review:** `53dfed3fb203a0b454256eda6fd3539ccd70a18f` (clean working tree except untracked reports)
**Date:** 2026-09-04
**Source files modified by this review:** **NONE**

---

## VERDICT

> ## `ARCHITECTURE REQUIRES REDESIGN`

Per ABSOLUTE RULE #1 and PART 25, **no source code has been modified** and none will be until you
respond to this review.

**Why this verdict, in one sentence:** the proposed architecture is rejected not because it is
badly designed, but because **it is a remediation plan for a defect that does not exist**, and
roughly 80 % of what it proposes is *already implemented and working* at `53dfed3`.

---

## 3. EXACT ROOT CAUSE OF THE `0 vs 2` PROBLEM

### The reported symptom is not a defect. The two numbers are correct.

Read-only probe of **live production** (`https://car-rental-system.fly.dev`), 2026-09-04 20:56 UTC,
GET-only, no mutation:

```
GET /api/v1/dashboard/stats
{
  "total_vehicles": 3,
  "available":      2,     <-- "Prêts à louer"        = 2
  "rented":         0,     <-- "Véhicules en location" = 0
  "reserved":       0,
  "maintenance":    1
}

GET /api/v1/vehicles/stats
{ "status_counts": { "AVAILABLE": 2, "MAINTENANCE": 1 } }

GET /api/v1/vehicles                                       (total = 3)
  koo              raw=AVAILABLE    eff=AVAILABLE
  pppppppppppppp   raw=AVAILABLE    eff=AVAILABLE
  SYNC_7613        raw=MAINTENANCE  eff=MAINTENANCE
```

**Invariant check:** `available(2) + reserved(0) + rented(0) + maintenance(1) = 3 = total_vehicles` ✅

`Véhicules en location` and `Prêts à louer` are **two different canonical metrics**
(`RENTED` and `AVAILABLE`) that are *mutually exclusive by construction*. Their values are
`0` and `2`. There is no reality in which they should be equal. Two of the three vehicles
are idle, none is out on rental, one is in maintenance. Both screens are telling the truth,
and they are telling the *same* truth.

**Classification (PART 3): `(B) different valid concepts, misleading juxtaposition`** — with a
strong contributing factor from `(H)` below. Explicitly **not** (A), (C), (D), (F) or (G):
no stale data, no local/server divergence, no duplicate rule, no cache bug is involved in
these two numbers.

### The contributing factor that most likely triggered the report — `(H)`

`SYNC_7613` is a **forensic probe vehicle sitting in production**. It is one of the exact markers
PART 24 lists. It is `MAINTENANCE`, and it is therefore inflating **two** live operator-facing
figures right now:

* `total_vehicles`: 3 instead of the real fleet size 2
* `maintenance` / `Véhicules en maintenance`: 1 instead of 0

An operator who knows they own two cars, sees `Prêts à louer = 2`, and then sees a fleet total of
3 and a maintenance count of 1 will reasonably conclude "the dashboard is wrong". The dashboard is
arithmetically right; **the production dataset is contaminated**.

Per PART 24 I have **deleted nothing and changed nothing**. This is reported for your decision.

### Second contributing factor — a real semantic collision on the same screen

`today_rentals = 0` while `today_revenue = 700.0 DH`.

Both are correct: `today_rentals` counts rentals whose **start date** is today
(`shared/revenue_reference.rentals_started_between`), whereas `today_revenue` is **pro-rata accrual**
for any rental whose window overlaps today. They are adjacent on the dashboard and read as a
contradiction ("zero rentals but 700 DH revenue"). This is the *same failure mode* as the reported
`0 vs 2`: correct numbers, colliding labels.

---

## 1. CURRENT ARCHITECTURE (verified from source, not from reports)

```
                shared/fleet_status_reference.py   <- NORMATIVE SPEC (pure, no ORM/DB/net)
                shared/money_time.py               <- NORMATIVE time/period spec
                shared/revenue_reference.py        <- NORMATIVE pro-rata revenue spec
                            |
        +-------------------+--------------------+
        |                   |                    |
  backend/app/services/  desktop/app/utils/  mobile/.../data/fleet/
  fleet_status.py        fleet_status.py     FleetStatus.kt
  (async SQLAlchemy)     (sync/pure rows)    (Kotlin port)
        |                   |                    |
  DashboardService     DomainStore          FleetRepository
  /dashboard/stats     (immutable,          (Room + flows)
  /vehicles/stats       revisioned,               |
        |               validated)          performanceMetricsFlow
        |                   |                     |
   FastAPI DTO      snapshot -> ALL views    DashboardScreen / VehiclesScreen
```

Three runtimes, one written specification, driven by shared cross-runtime vectors
(`shared/fleet_status_cases.json`, 14 cases; `shared/revenue_cases.json`).

**What already exists that the proposal asks for:**

| Proposal item | Status at `53dfed3` |
| --- | --- |
| One canonical metric dictionary | ✅ `shared/fleet_status_reference.py` (precedence, half-open intervals, blocking statuses) |
| One fleet calculation engine | ✅ one per runtime, all parity-tested against the shared vectors |
| Atomic immutable snapshots | ✅ `DomainSnapshot` is `@dataclass(frozen=True)`, built in one pass, published once |
| Revision / generation + stale rejection | ✅ `DomainStore._revision`; `update_server_dashboard` drops `generation < _server_generation` (`domain_store.py:151`) |
| Integrity checker rejecting bad state | ✅ `DomainStore._validate_snapshot` — on failure keeps the last valid snapshot (`domain_store.py:255-258`) |
| Event-driven invalidation | ✅ `store.mutate()` → commit → `reload()` → fan-out; `BoundaryClock` arms one timer at `snapshot.next_boundary` |
| Explicit time model | ✅ `now_business()`, half-open `[start, end)`, `test_no_naive_now` forbids bare `datetime.now()` in `backend/app` and `desktop/app` |
| Authority matrix | ⚠️ implemented in code, never written down |
| No widget-level KPI computation (desktop) | ✅ Dashboard cards and Vehicles page both read `_store.snapshot`; `_load_vehicles_from_local` never queries SQLite |

Building a second `CanonicalDashboardState` layer on top of `DomainSnapshot` would be building
`DomainSnapshot` again. That is precisely what your own NON-NEGOTIABLE PRINCIPLES forbid:
*"never add architecture layers without proving they are beneficial."*

---

## 2. CURRENT ARCHITECTURAL WEAKNESSES (the real ones)

The business **rules** were unified. The **primitives underneath them were not**, and the parity
harness cannot see the gap.

### W1 — Four contradictory "naive datetime" policies (P1, latent)

Three docstrings in this repo claim there is "ONE naive-datetime policy across the whole product".
There are two, in six places:

| Location | Naive value read as |
| --- | --- |
| `shared/money_time.to_business` | Africa/Casablanca |
| `shared/fleet_status_reference._parse` (`:79`) | Africa/Casablanca |
| `shared/revenue_reference._as_datetime` (`:84`) | Africa/Casablanca |
| `desktop/app/utils/datetime_utils.parse_datetime_utc` (`:40,:46`) | Africa/Casablanca |
| `desktop/app/sync/dashboard_cache._to_biz` (`:47`) | Africa/Casablanca |
| `backend/app/services/fleet_status.py` (`:128-132`, **start only**) | Africa/Casablanca |
| `backend/app/services/fleet_status.py` — **`end_datetime`, filtered in SQL at `:120`** | **untreated** |
| `backend/app/api/v1/maintenance._as_utc` (`:26`) | **UTC** |
| `backend/app/services/sync_service._as_utc` (`:40`) | **UTC** |
| `mobile/.../FleetStatus.parseUtcMillis` (`:93`) | **UTC** |

Two of those carry comments asserting the opposite of what they do:

* `backend/app/api/v1/maintenance.py:22` — *"Naive values are interpreted as UTC — the same policy
  the fleet-status derivation uses."* The fleet-status derivation uses **Casablanca**.
* `mobile/.../FleetStatus.kt:32` — *"Naive ISO strings are interpreted as UTC, matching
  `parse_datetime_utc`."* `parse_datetime_utc` uses **Casablanca**.

**Executable proof of divergence** (`shared` reference vs `desktop` engine vs the mobile parser
rule, same rows, same instant):

```
now = 2026-09-04T22:00:00+00:00   (Casablanca 23:00)
reservation stored naive: 22:30 -> 23:30

shared reference (naive == Casablanca):  rented=1  available=0  reserved=0
desktop          (naive == Casablanca):  rented=1  available=0  reserved=0
mobile           (naive == UTC)        :  rented=0  available=0  reserved=1
```

**Desktop says "en location = 1". Mobile says "en location = 0" and "réservés = 1". Same rows,
same instant.** This is the exact *shape* of the contradiction you reported — it is just not the
instance you reported, and it is currently latent (see Blast radius).

### W2 — The parity harness has zero coverage of the divergent input class (P1)

All **37** interval literals across the 14 cases in `shared/fleet_status_cases.json` carry an
explicit `Z`. **Not one naive datetime is exercised.** The cross-runtime parity tests
(`backend/tests/test_fleet_status_crossruntime.py`, `desktop/tests/test_fleet_status_crossruntime.py`,
`mobile/.../FleetStatusParityTest.kt`, `CrossClientConvergenceTest.kt`) therefore pass green while
W1 is live in the code. This is PART 2 item #14 realized in the current tree: *tests pass while a
UI representation uses another calculation path*.

**This is the single most important finding in this review.** The parity harness is the mechanism
this whole architecture depends on to keep three runtimes honest, and it has a hole exactly where
the runtimes disagree.

### W3 — Mobile silently switches metric authority mid-flight (P1)

`mobile/.../FleetRepository.kt:196-225`:

```kotlin
val fleetFromLocal = totalLocal == totalApi && totalLocal > 0
api.copy(
  readyVehicles  = if (fleetFromLocal) local.readyVehicles  else api.readyVehicles,
  rentedVehicles = if (fleetFromLocal) local.rentedVehicles else api.rentedVehicles,
  ...
)
```

When the Room vehicle pool and the API pool disagree, the Dashboard fleet cards fall back to
**server** counts — while `VehiclesScreen` keeps rendering `deriveEffectiveVehicles(...)`, i.e. the
**local** derivation (`FleetRepository.kt:116-133`). During that window the same metric has two
publishers on the same device, and the switch is **silent** — no diagnostic, no marker.

This violates PART 19 (one metric, one source) and PART 20 (contradictions must be detectable,
never silently normalized). Desktop does not have this problem: `DomainStore` *always* overwrites
the server's fleet keys with the local canonical counts (`domain_store.py:166-169`, `:458-463`;
`main_window.py:549-552`), so desktop has exactly one fleet publisher.

### W4 — Backend start/end asymmetry (P2, latent)

`compute_effective_statuses` coerces `start_datetime` in Python (`fleet_status.py:128-132`) but
filters `end_datetime > now` **in SQL** (`:120`) with no coercion. Under PostgreSQL the columns are
`TIMESTAMP(timezone=True)` so rows are always aware and this is inert in production; under SQLite
(the backend test database) tz is lost and the two ends of the same interval are interpreted under
different rules.

### W5 — Production data contamination (P1, operational)

`SYNC_7613` — a PART 24 forensic marker — is a live production vehicle in `MAINTENANCE`, inflating
`total_vehicles` to 3 and `maintenance` to 1. `koo` and `pppppppppppppp` are also non-business-looking
registrations. Nothing separates probe rows from real rows at the schema level, so no automated
check can ever exclude them.

### W6 — Authority and metric semantics are undocumented (P2)

The authority split is real and correct in code, but it lives only as prose in docstrings. Nothing
tells a future maintainer that *fleet counts are local-authoritative and revenue is
server-authoritative*, which is the non-obvious decision the whole design turns on.

### Blast radius of W1/W2 — why these are P1, not P0

Naive datetimes are currently **rare on the mainline**: `reservation_list.py:374` converts
business-local → aware UTC before persisting, desktop stores datetimes as `String(50)` and
round-trips them verbatim, and the backend's `TIMESTAMPTZ` columns always serialize aware ISO.
So W1 bites only on legacy rows, direct DB edits, or a future code path that forgets the
conversion — and when it does, it produces a **silent one-hour cross-runtime disagreement** with
no test able to catch it. That is a latent P1, not an active P0.

---

## 4-5. DUPLICATED BUSINESS LOGIC — inventory

| Metric | Backend | Desktop | Mobile | Same rule? |
| --- | --- | --- | --- | --- |
| `RENTED` / `AVAILABLE` / `RESERVED` / `MAINTENANCE` | `services/fleet_status.py` | `utils/fleet_status.py` | `FleetStatus.kt` | ✅ same rule — **except naive inputs (W1)** |
| `total_vehicles` | sum of buckets | `total - rented - reserved - maint` | sum of buckets | ✅ algebraically identical |
| `/vehicles/stats` | `VehicleService.get_status_counts` → **same** `compute_effective_statuses` | — | — | ✅ (the raw `count_by_status` in `vehicle_repository.py:103` exists but is **not** wired to any dashboard path) |
| revenue (all periods) | `revenue_service.revenue_between` | `dashboard_cache` | `RevenueEngine.kt` | ✅ parity-tested via `revenue_cases.json` |
| period bounds | `shared/money_time.period_bounds` | imports shared | `periodBounds` (Kotlin port) | ✅ |
| naive-datetime parsing | 3 policies | 2 policies | 1 policy | ❌ **W1** |

**Result: there is no duplicated *business rule*.** The duplication is one level down, in the
**datetime primitive**. That is why every previous fix — which correctly targeted business rules —
kept leaving a residue.

---

## PART 2 — the common cause behind the 14 historical defects

Grouping them by mechanism rather than symptom:

* **#1, #2, #12, #22 (orphan rows, raw-vs-operational status)** → *raw persistence was read as
  business state*. **Fixed and holding.** `53dfed3`'s orphan guards are intact at three
  independent layers: `domain_store.py:331-342`, `fleet_status.py:87-90/104-107`, and
  `_rows_from_session` `:203-207`, with both native and `str()` ID forms normalized.
* **#3, #9, #10, #11 (flicker, stale-on-reload, differing calculations)** → *no single
  atomic publisher*. **Fixed** by `DomainStore` + revisioned snapshot + fan-out.
* **#4, #5, #6 (server overwrote local canonical, divergence)** → *authority was implicit*.
  **Fixed on desktop** (fleet keys always reconciled to local canonical). **Not fixed on
  mobile** → W3.
* **#7, #8 (naive/aware divergence, false overlap positives)** → *no single time primitive*.
  **NOT fixed** → W1/W4. This is the one root cause that survived every previous remediation.
* **#13 (forensic contamination)** → **NOT fixed** → W5, live in production today.
* **#14 (tests green while UI diverges)** → **NOT fixed** → W2, and it is the reason #7/#8
  and #13 could survive.

**The one common architectural cause: the project unified its business rules but never unified
the primitives beneath them, and built a parity harness whose vectors cannot exercise the
un-unified primitive.**

---

## 6-8. ALTERNATIVES CONSIDERED, AND THE RECOMMENDATION

| Model | Integrity | Offline | Dup-logic risk | Stale risk | Testability | Migration | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **A** Backend-authoritative metrics | High online | **Fails** — dashboard dies offline | Low | High (every fetch a race) | Easy | Large | ❌ rejected: this product is offline-first; also re-opens defect #4 |
| **B** Shared canonical engine, Backend + Desktop | High | Good | Low | Low | Good | Large | ❌ rejected: cannot include Kotlin/Room without a JVM-Python bridge; leaves mobile out of the very guarantee it needs |
| **C** Backend-authoritative online + deterministic local authority offline | High | Good | Low | Low | Good | Medium | ~ this is roughly what mobile does today, and W3 is the bug it produces: authority that changes at runtime is authority you cannot reason about |
| **D** **Normative shared spec + one mechanical port per runtime, parity-tested from shared vectors; fleet local-authoritative, revenue server-authoritative** | **High** | **Excellent** | **Low** | **Low** | **Excellent** | **None — already built** | ✅ **RECOMMENDED** |

**Model D is the architecture the repository already has.** My recommendation is therefore to
**keep it and close its four gaps**, not to add a layer on top of it.

Model D beats the proposal because it puts the invariant in the **test harness**, where a violation
becomes a red build, rather than in a **runtime checker**, where a violation becomes a log line
nobody reads. A `CanonicalDashboardState` + integrity-checker layer would not have caught W1 — both
runtimes would each have published a *self-consistent, invariant-satisfying* snapshot, one hour
apart from each other. Only a cross-runtime vector catches that. The proposal adds cost exactly
where the system is already strong and adds nothing where it is weak.

### Answers to PART 6's challenge questions

1. **Is the proposal the best architecture?** No — it re-implements `DomainStore` and adds a
   runtime checker that would not catch the real defects.
2. **Is there still duplicate domain logic?** Not at the rule level. Yes at the datetime-primitive
   level (W1).
3. **Shared domain module?** Already exists (`shared/*_reference.py`). It cannot be *executed* by
   Kotlin — which is why the **shared test vectors** are the load-bearing artifact, and why W2 is
   the priority fix.
4. **Should backend own all operational metrics?** No. Offline-first is a product requirement; the
   current split (fleet local, revenue server) is correct and should be **written down**, not changed.
5. **Offline desktop?** Works today via `DomainStore` + `BoundaryClock`. Unchanged.
6. **Is desktop SQLite a cache, replica, or authority?** It is a **replica that is authoritative for
   time-derived fleet state**. This is the design's key non-obvious decision and must be documented.
7. **Should mobile compute metrics?** Yes — it must, for offline. But it must do so
   **unconditionally**, never switching to the server mid-flight (W3).
8. **Could canonical state go stale?** Yes — which is why `next_boundary` + `BoundaryClock` exist.
   Already solved.
9. **Too many layers?** The proposal would add one too many.
10. **Harder to debug?** Yes — a second snapshot layer doubles the places a number can be wrong.
11. **Where should semantics live?** `shared/*_reference.py` + the shared JSON vectors. Already correct.
12. **Where should time logic live?** `shared/money_time.py` — and **one** naive policy must be
    mechanically enforced across all runtimes (W1).
13. **Where should conflict resolution live?** In the authority matrix, decided **statically per
    metric**, never dynamically per response (W3).

---

## 9. SEMANTIC METRIC CONTRACT

| Canonical ID | Meaning | FR label | Rule |
| --- | --- | --- | --- |
| `TOTAL_VEHICLES` | vehicles neither `SOLD` nor `INACTIVE` | (fleet total) | structural exclusion |
| `AVAILABLE` | no maintenance, no reservation covering or upcoming | **Prêts à louer** | residual bucket |
| `RENTED` | blocking reservation with `start <= now < end` | **Véhicules en location** | time-derived, **not** `status == ACTIVE` |
| `RESERVED` | blocking reservation with `now < start` | Réservés | upcoming only |
| `MAINTENANCE` | active ticket with `start <= now < COALESCE(actual_end, expected_end, +inf)` | En maintenance | highest non-structural precedence |

**`Véhicules en location` and `Prêts à louer` are DIFFERENT metrics** (`RENTED` vs `AVAILABLE`),
mutually exclusive by construction, and **must never be reconciled to each other**. The labels are
already unambiguous in French; the confusion is one of *adjacency*, not of naming.

Two metric pairs genuinely do need clearer labels, because they are adjacent and differently defined:

* `today_rentals` ("Réservations (Ce jour)" — counts rentals **started** today) vs
  `today_revenue` ("Chiffre d'affaires" — **pro-rata accrual** across today)
* `maintenance` (fleet bucket: vehicles occupied **now**) vs `active_maintenance_tickets`
  (**all** open tickets, including future-dated)

---

## Authority matrix (PART 8) — as actually implemented

| Domain | Raw authority | Business-rule authority | Online metric source | Offline source | UI source |
| --- | --- | --- | --- | --- | --- |
| Vehicles / reservations / maintenance rows | PostgreSQL | `shared/fleet_status_reference.py` | server rows → local mirror | SQLite / Room | `DomainStore.snapshot` (desktop), `FleetRepository` flows (mobile) |
| Fleet counts (`AVAILABLE/RENTED/RESERVED/MAINTENANCE`) | derived, never stored | shared spec | **local canonical** (desktop: always; mobile: **conditional — W3**) | local canonical | snapshot / flow |
| Revenue (all periods) | PostgreSQL | `shared/revenue_reference.py` | **server** | local pro-rata engine | dashboard panel |
| Period bounds / "now" | — | `shared/money_time.py` | `now_business()` | `now_business()` | — |
| UI state | — | — | — | — | one atomic snapshot per revision |

---

## 10. RECOMMENDED PLAN (**not executed** — awaiting your decision)

Five targeted changes. No new layers, no new abstractions.

| # | Change | Files | Risk |
| --- | --- | --- | --- |
| **R1** | Add naive-datetime cases to `shared/fleet_status_cases.json` (+ `revenue_cases.json`), incl. an interval straddling the Casablanca/UTC offset. Regenerate expectations with `scripts/regen_fleet_status_cases.py`. **Expect mobile parity tests to go RED — that is the proof W1 is real.** | `shared/*.json` | none (test data) |
| **R2** | Fix `FleetStatus.parseUtcMillis` to read naive as `Africa/Casablanca`; correct the stale comment at `:32`. R1 turns green. | `mobile/.../FleetStatus.kt` | low, covered by R1 |
| **R3** | Align the two `_as_utc` helpers to the business-local policy; correct the false comment at `maintenance.py:22`. Fix the backend `end_datetime` SQL asymmetry (W4). | `backend/app/api/v1/maintenance.py`, `backend/app/services/sync_service.py`, `backend/app/services/fleet_status.py` | medium — sync path, needs its own regression |
| **R4** | Make mobile fleet counts **unconditionally** local-derived, matching desktop; delete the `fleetFromLocal` switch. If the pools disagree, that is a *sync* problem to surface, not a metric to silently swap. | `mobile/.../FleetRepository.kt` | low |
| **R5** | Add `test_naive_datetime_policy` asserting every naive-coercion site in `backend/app`, `desktop/app`, `shared` resolves to `BUSINESS_TZ` — the guard that stops W1 from ever returning. | new test | none |

**Separately, and requiring your explicit authorization (PART 24 — I will not act on this):**
decide what to do about `SYNC_7613` in production. `scripts/purge_forensic_probes.sql` exists but
**I have not run it and will not without a direct instruction.**

Deliberately **not** recommended: `CanonicalDashboardState`, a runtime integrity-checker layer,
a metric-identifier registry, generation counters beyond the existing ones. Each duplicates
something already present and none would have caught W1, W3 or W5.

---

## 11. TEST STRATEGY

Baseline measured this session, on the unmodified tree:

```
Backend:  229/229 passed   (10.07s)   backend/venv/bin/python -m pytest tests -q
Desktop:  324/324 passed   (693.92s)  desktop/venv/bin/python -m pytest tests -q
Mobile:   not run — no source changed, and the Gradle/JVM toolchain was not exercised
```

Under R1-R5 the gate would be: both suites green, mobile unit tests green, R1 vectors red-then-green
across all three runtimes, and R5 present.

---

## 21-24. PRODUCTION SAFETY & ARTIFACT IMPACT

* **Production access this session: READ-ONLY.** One `POST /auth/login` to obtain a token; every
  other call was a `GET`. No row created, updated, or deleted. No deploy. No push. No purge SQL run.
* **Source code modified: NONE.** The only file added is this report.
* **Artifacts:** `ATELIER_BERLIN_LOCATION_CAR_53dfed3.apk`,
  `ATELIER_BERLIN_LOCATION_CAR_WINDOWS_53dfed3.zip` and the `.exe` were built from `53dfed3`.
  Because **no source changed, the existing release artifacts remain valid and must not be
  rebuilt** (PART 27).
* **P0 orphan regression (PART 22): INTACT.** Verified by reading all three guard layers; both
  native and string vehicle-ID forms are normalized, so an orphan reservation or maintenance row
  has zero fleet effect and cannot bypass validation via ID type.

---

## 24. FORENSIC MARKERS FOUND (inspection only — nothing deleted)

| Marker | Where | State |
| --- | --- | --- |
| `SYNC_7613` | **live production**, vehicle `41f1ff38-…`, `MAINTENANCE` | inflating `total_vehicles`→3 and `maintenance`→1 **right now** |
| `koo`, `pppppppppppppp` | live production vehicles | non-business registrations; your call whether real |
| `ForensicBrand`, `ProofModel`, `CRT-`, `REV-` | not present in the live vehicle list | — |

---

## FINAL RELEASE VERDICT

> ## `NO-GO — DASHBOARD DATA CONSISTENCY NOT VERIFIED`

To be explicit about *why*, because the reasoning is unusual:

The reported `0 vs 2` defect **does not exist** — those two numbers are correct, consistent, and
provably satisfy the fleet invariant against live production data. If that were the only open
question, this would be a GO.

It is `NO-GO` because the architecture review it triggered surfaced **four genuine defects that
were not previously known** (W1-W4) plus **live production data contamination** (W5), and PART 20
requires that a contradiction be *detectable*. Today W1 is a real cross-runtime contradiction that
**no test in this repository can detect**. Until R1 exists, the honest statement is that dashboard
consistency is *unproven*, not *broken*.

Per ABSOLUTE RULE #1 and PART 25, **implementation stops here pending your decision.**
