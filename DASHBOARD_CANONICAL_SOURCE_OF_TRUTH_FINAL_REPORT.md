# Dashboard Canonical Source-of-Truth — Architecture Review, Remediation & Release Verification

**Reviewer role:** Principal Architect / independent senior reviewer
**Repository:** `/home/ayman/car-rental-system`
**Baseline reviewed:** `53dfed3fb203a0b454256eda6fd3539ccd70a18f`
**Remediation commit:** `de6b493ad59cd5ed847038be52690493004df3fb` (`de6b493`)
**Branch:** `fix/cross-runtime-datetime-policy-and-fleet-authority` (**not pushed**)
**Date:** 2026-09-04

---

## 1. ARCHITECTURE VERDICT

> ### `ARCHITECTURE REQUIRES REDESIGN` — the *proposal* was rejected; the *existing* architecture was kept.

The proposed direction (a new `CanonicalDashboardState` layer, a runtime integrity checker, a
metric registry, additional generation counters) was rejected on two grounds:

1. **It was a remediation plan for a defect that does not exist** (§2).
2. **~80 % of it already existed** at `53dfed3` — `DomainSnapshot` is already frozen, atomic,
   revisioned, validated, and fanned out to every view; stale server generations are already
   dropped; `BoundaryClock` already handles temporal invalidation.

Decisive argument: a per-runtime integrity checker **would not have caught any of the four real
defects**. Under W1 each runtime published a *self-consistent, invariant-satisfying* snapshot —
they were simply an hour apart from each other. Only a cross-runtime vector catches that. The
approved work therefore put the guarantee in the **test harness**, where a violation is a red
build, not in a runtime checker, where it is a log line nobody reads.

This verdict was accepted, and remediation R1–R5 was authorised and is now complete.

---

## 2. THE ORIGINAL `0 vs 2` — SEMANTIC EXPLANATION

**The reported symptom was not a bug.** Read-only probe of live production (GET only):

```
GET /api/v1/dashboard/stats
  total_vehicles: 3
  available:      2      <- "Prêts à louer"          = 2
  rented:         0      <- "Véhicules en location"  = 0
  reserved:       0
  maintenance:    1

invariant: 2 + 0 + 0 + 1 = 3 = total_vehicles          ✅
GET /api/v1/vehicles/stats -> {AVAILABLE: 2, MAINTENANCE: 1}   (agrees, bucket for bucket)
```

`Véhicules en location` is the canonical metric **`RENTED`**; `Prêts à louer` is **`AVAILABLE`**.
They are **mutually exclusive buckets by construction** — there is no reality in which they should
be equal. Two cars idle, none out on rental, one in maintenance.

**Classification: `(B)` different valid concepts, misleading juxtaposition** — with a contributing
factor from `(H)` (real data contamination, §9).

**These two metrics have NOT been merged and must never be.** `RENTED != AVAILABLE` is now asserted
explicitly in three test suites (§7).

**Contributing factor.** `SYNC_7613` — a forensic probe from the PART 24 marker list — is a live
production vehicle in `MAINTENANCE`. It inflates `total_vehicles` to 3 and `maintenance` to 1. An
operator who owns two cars sees a fleet of three and reasonably concludes the dashboard is wrong.
The dashboard is arithmetically right; the dataset is contaminated. **Nothing was deleted** (§9).

**Second, genuine, same-class collision:** `today_rentals = 0` alongside `today_revenue = 700 DH`.
Both correct — one counts rentals *started* today, the other is *pro-rata accrual* across today —
and they sit next to each other on screen. Flagged as a P2 labelling issue (§10).

---

## 3. ROOT CAUSES W1–W4

The project had unified its **business rules** but never unified the **primitives beneath them**,
and built a parity harness whose vectors could not exercise the un-unified primitive.

### W1 — Four contradictory naive-datetime policies (P1)

Three docstrings claimed "ONE naive-datetime policy across the whole product". There were **two**,
across **eight** sites:

| Site | Naive read as |
| --- | --- |
| `shared/money_time.to_business` | Casablanca |
| `shared/fleet_status_reference._parse` | Casablanca |
| `shared/revenue_reference._as_datetime` | Casablanca |
| `desktop/app/utils/datetime_utils.parse_datetime_utc` | Casablanca |
| `desktop/app/sync/dashboard_cache._to_biz` | Casablanca |
| `backend/app/services/fleet_status` (start only) | Casablanca |
| `backend/app/api/v1/maintenance._as_utc` | **UTC** |
| `backend/app/services/sync_service._as_utc` | **UTC** |
| `mobile/.../FleetStatus.parseUtcMillis` | **UTC** |

Two carried comments asserting a parity their own code contradicted
(`maintenance.py:22`, `FleetStatus.kt:32`).

Executable proof of the divergence, before the fix:

```
now = 2026-09-04T22:00Z (Casablanca 23:00); reservation stored naive 22:30 -> 23:30
  desktop/backend (naive == Casablanca):  rented=1  reserved=0
  mobile          (naive == UTC)       :  rented=0  reserved=1
```

Desktop: "en location = 1". Mobile: "en location = 0". **Same row, same instant.**

### W2 — The parity harness could not see it (P1, the key finding)

All **37** interval literals in `shared/fleet_status_cases.json` carried an explicit `Z`. **Zero**
naive coverage — the exact input class where the runtimes disagreed. The cross-runtime parity tests
passed green while W1 was live. This is PART 2 item #14 realised, and it is why W1 survived every
previous remediation round.

### W3 — Mobile switched metric authority at runtime (P1)

`FleetRepository.kt`: `fleetFromLocal = (totalLocal == totalApi && totalLocal > 0)`. On any pool
disagreement the **Dashboard** silently fell back to server counts while **VehiclesScreen** kept
deriving locally — one metric, two publishers, on one device, with no diagnostic. Violated PART 19
and PART 20.

### W4 — Backend SQL/Python asymmetry — **wider than first diagnosed** (P1)

Static review found one instance (reservation `end_datetime`). The R1 vectors found **four**:
only `Reservation.start_datetime` was coerced in Python; reservation **end**, maintenance **start**
and maintenance **end** were all filtered raw in SQL.

Characterisation probe (`TIMESTAMP(timezone=True)` under SQLite):

```
stored: aware 13:00+01:00 (== now)   -> text '2026-08-30 13:00:00.000000'   [offset DISCARDED]
        naive 13:00                  -> text '2026-08-30 13:00:00.000000'   [identical]
SQL    `ts > now`   -> [1, 2, 3]   ... matched a row where ts == now   (half-open violation)
Python `ts > now`   -> [3]         ... correct
```

So the backend disagreed **with itself** between SQLite and PostgreSQL. Also found while aligning
these helpers: `COALESCE(actual_end, expected_end)` had its **operands reversed in three places**,
holding a ticket closed early in `MAINTENANCE` until its original estimate.

---

## 4. THE CANONICAL DATETIME POLICY

> **A datetime carrying no UTC offset is BUSINESS-LOCAL wall time (`Africa/Casablanca`), never UTC.**

Derived from the repository's own written contract (`shared/money_time.to_business`), which six of
the eight sites already implemented — not chosen by me. Now expressed **once**, in
`shared/money_time.to_utc()`, and called by every Python normalisation site. Kotlin implements the
identical rule in `FleetStatus.parseUtcMillis` and is pinned to the same instants by test.

Corollary enforced in `backend/app/services/fleet_status.py`: **SQL selects candidate rows by
status; every `start <= now < end` comparison happens in Python.** This is the only way to make
PostgreSQL, SQLite, the desktop mirror and the normative reference produce identical buckets.
Cost: the scan is bounded by the status filter (open business rows), not by history.

---

## 5. AUTHORITY MODEL (explicit, static per metric — never per response)

| Domain | Raw authority | Business-rule authority | Online source | Offline source | UI source |
| --- | --- | --- | --- | --- | --- |
| Vehicle / reservation / maintenance rows | PostgreSQL | `shared/fleet_status_reference.py` | server → local mirror | SQLite / Room | `DomainStore.snapshot` / `FleetRepository` flows |
| **Fleet counts** (`AVAILABLE/RENTED/RESERVED/MAINTENANCE`) | derived, never stored | shared spec | **local canonical — always** | local canonical | snapshot / flow |
| **Revenue & bookings** | PostgreSQL | `shared/revenue_reference.py` | **server**, unless that period's boundary has been crossed since the response | local pro-rata engine | dashboard panel |
| Period bounds / "now" | — | `shared/money_time.py` | `now_business()` | `now_business()` | — |
| UI state | — | — | — | — | one atomic snapshot per revision |

Desktop already behaved this way (`DomainStore` unconditionally reconciles the server overview's
fleet keys onto local canonical counts). **R4 made Mobile match it.** Pre-bootstrap (`Room` holds
no vehicles) the server object passes through whole, because there is no local truth yet and the
Vehicles screen is in its own empty state — no two populated screens can disagree.

---

## 6. R1–R5 — EXACT FILES AND FUNCTIONS MODIFIED

| # | File | Change |
| --- | --- | --- |
| R1 | `shared/fleet_status_cases.json` | **+12 vectors** (14 → 26): naive, explicit `+01:00` offset, exact start boundary, exact end boundary, before/during/after, reservation, ACTIVE rental, maintenance, maintenance-vs-reservation precedence, mixed aware+naive rows. Includes 3 **control** vectors where both readings agree, proving the fix is not a blanket flip. No existing vector removed or edited. |
| R2 | `mobile/.../data/fleet/FleetStatus.kt` | `parseUtcMillis` — offset-less patterns now resolve in `CASABLANCA`, not UTC; policy docstring corrected. Single choke point: `RevenueEngine` takes pre-parsed millis, so this fixes fleet **and** revenue. |
| R2 | `mobile/.../data/repository/FleetRepository.kt` | `formatIsoDate` — second, divergent parser removed; now routes through `FleetStatus.parseUtcMillis` and renders in business time instead of **device** time (reservation/maintenance dates could read an hour off Desktop, or shift when the phone travelled). |
| R3 | `shared/money_time.py` | **+ `to_utc()`** — THE one coercion helper. |
| R3 | `backend/app/services/fleet_status.py` | **+ `_coerce()`**; `_maintenance_effective_end()` now a Python function; interval predicate moved out of SQL for reservations **and** maintenance, start **and** end. |
| R3 | `backend/app/services/sync_service.py` | local `_as_utc` (naive==UTC) → `shared.money_time.to_utc`; `_maintenance_active_now` COALESCE order corrected. |
| R3 | `backend/app/api/v1/maintenance.py` | same helper replacement; COALESCE order corrected at both call sites (`:228`, `:615`). |
| R4 | `mobile/.../data/repository/FleetRepository.kt` | `performanceMetricsFlow` — `fleetFromLocal` conditional **deleted**; fleet counts unconditionally local-authoritative; pool disagreement now **logged**, not silently normalised; authority matrix documented in place. |
| R5 | `backend/tests/test_naive_datetime_policy.py` | **new** — 9-site policy agreement; SQL-vs-Python boundary parity (reservation + maintenance × naive + aware rows); actual_end-wins. |
| R5 | `desktop/tests/test_naive_datetime_policy.py` | **new** — desktop-side sites; naive-row boundary parity vs the reference; Dashboard `fleet_counts` == Vehicles-page tally; bucket disjointness. |
| R5 | `mobile/.../NaiveDatetimePolicyTest.kt` | **new** — same literals/instants as the Python guard; reservation + maintenance boundaries; W1 regression pinned. |
| R5 | `mobile/.../DashboardVehiclesParityTest.kt` | **new** — Dashboard cards == Vehicles screen tally while the server reports a different fleet; `RENTED != AVAILABLE`; buckets partition the pool. |

**Test fixtures corrected** (they encoded the *old* policy, not the behaviour under test):
`backend/tests/test_forensic_6a_timezone_and_raw_status.py` (its window is now written in
business-local so it denotes the same instants under SQLite **and** the CI's PostgreSQL run — it
previously passed only because the derivation guessed `naive == UTC`, matching SQLite's flattening
by luck); five mobile test files whose ISO builders now emit an explicit offset, so fixtures no
longer depend on the naive policy at all.

**Deliberately NOT built:** `CanonicalDashboardState`, a runtime integrity-checker layer, a metric
registry, extra generation counters. `DomainSnapshot` already satisfies the required guarantees;
duplicating it would add a second place for a number to be wrong.

---

## 7. VERIFICATION

### 7.1 The guards actually fail — proven, not assumed

Reintroducing W1 in `FleetStatus.kt` (`CASABLANCA` → `UTC`) and re-running the mobile suite:

```
CrossClientConvergenceTest > mobile converges with backend and desktop on every shared vector FAILED
FleetStatusParityTest      > mobile fleet status matches the shared normative vectors          FAILED
NaiveDatetimePolicyTest    > a naive literal is business-local wall time, not UTC              FAILED
NaiveDatetimePolicyTest    > every offset-less accepted form resolves to the same instant      FAILED
NaiveDatetimePolicyTest    > reservation half-open boundaries on a naive row                   FAILED
NaiveDatetimePolicyTest    > maintenance half-open boundaries on a naive row                   FAILED
NaiveDatetimePolicyTest    > W1 regression - naive window covering now is RENTED               FAILED
79 tests completed, 7 failed
```

**Before this work, that same defect produced a fully green build.** Reverted; suite green again.

Reintroducing `naive == UTC` in `sync_service._as_utc` fails the Python guard with the offending
site named:

```
AssertionError: NAIVE-DATETIME POLICY DIVERGENCE — these sites do not read '2026-08-30T13:00:00'
as business-local (2026-08-30T12:00:00+00:00):
backend.services.sync_service._as_utc -> 2026-08-30T13:00:00+00:00
```

### 7.2 R1 vectors went red exactly where the defects were

| Runtime | On adding the 12 vectors, before fixes |
| --- | --- |
| Desktop | **26/26 pass** — desktop was already correct |
| Backend | **4 FAILED** — revealed W4 was 4× wider than static review found |
| Mobile | **7 FAILED** across 3 suites — W1 |

### 7.3 Cross-runtime proof — same data, same instant, same rule

```
PROOF 1 — 26 shared vectors: Backend == Desktop == normative reference
  ... 26/26 vectors agree  (12 of them naive/offset)
PROOF 2 — RENTED and AVAILABLE are DISTINCT metrics
  effective: {'a': 'RENTED', 'b': 'AVAILABLE'};  rented=1 available=1; disjoint=True
  => same count, DIFFERENT vehicles, DIFFERENT metrics. Not merged.
PROOF 3 — LIVE PRODUCTION (read-only)
  available=2 rented=0 reserved=0 maintenance=1 total=3;  invariant 3 == 3 -> True
  /vehicles/stats == /dashboard/stats for all four buckets
```

Mobile runs the **identical** 26-vector file green via `FleetStatusParityTest` and
`CrossClientConvergenceTest`, closing the third runtime.

### 7.4 Full regression — actual command output

```
Backend  248 passed,  7 warnings in 14.40s     (baseline 229 -> +12 vectors +7 guards)
Desktop  352 passed             in 709.89s     (baseline 324 -> +24 vectors/params +4 guards)
Mobile    79 tests, 0 failed, 0 skipped        (baseline  71 -> +8 guards)   [--rerun-tasks]
```

| Requested category | Result |
| --- | --- |
| Backend full suite | **248/248** |
| Desktop full suite | **352/352** |
| Mobile unit tests | **79/79** |
| Shared parity (per runtime) | **26/26 × 3** |
| New datetime-consistency guards | **20/20** (7 backend + 4 desktop + 8 mobile + 1 parity) |
| Dashboard/reversion | included in desktop 352 (`test_dashboard_cache_reversion`) |
| Cross-window parity | **pass** (desktop `test_cross_window_convergence` + new naive-row guard; mobile `DashboardVehiclesParityTest`) |
| Orphan integrity (P0 from `53dfed3`) | **INTACT** — all three guard layers unchanged and green |
| Lifecycle / reconnect | included in desktop 352 (`test_sync_*`, `test_refresh_integrity`) + mobile offline/sparse-cache tests |
| Out-of-order protection | included (`DomainStore` generation drop; `test_dashboard_cache_reversion`) |

---

## 8. ARTIFACTS

Source changed, so **all three artifacts were rebuilt from scratch at `de6b493`**. The `53dfed3`
artifacts are superseded and must not be presented as containing this fix.

| Artifact | SHA256 | Size | Built (local) |
| --- | --- | --- | --- |
| `ATELIER_BERLIN_LOCATION_CAR_de6b493.apk` | `507d9a7e40e63b8980a8759e3a0a532d2902bf41f175aed34c02460f6fbb1801` | 23 375 146 | 2026-09-04 22:46:33 |
| `ATELIER_BERLIN_LOCATION_CAR_de6b493.exe` | `2390d868151f9beb94e5e07a70d2a1ccdc7dc90110029dfbd2677a92b13e5707` | 9 170 956 | 2026-09-04 22:46:33 |
| `ATELIER_BERLIN_LOCATION_CAR_WINDOWS_de6b493.zip` | `e80c3032ec1cf94ade2e93a291705efe26a39b0234d04f0e92503919b0e8d626` | 61 985 574 | 2026-09-04 22:46:39 |

**Superseded (`53dfed3`, 20:09–20:11):**
`…_53dfed3.apk` = `9b90c078be2e7ed21eec88fa076468b01555ff855254439290a4b6ef71c8700c`,
`…_WINDOWS_53dfed3.zip` = `5aa2e3d75d1b37f8915b848bd8e0aa19d304e621a8b8efaa154c2d47d9b7d2a6`.
All hashes distinct; new timestamps ~2h37m later.

**Build commands** (identical to the documented release procedure):
`./gradlew assembleDebug --rerun-tasks --offline` (39/39 tasks executed) and
`wine venv_wine/Scripts/pyinstaller.exe --noconfirm --clean ATELIER_BERLIN_LOCATION_CAR.spec`
after `rm -rf build dist`.

**Provenance verified, not assumed:**
* Windows: the bundled `_internal/shared/money_time.py` contains the new `to_utc` — the build
  really came from `de6b493`.
* APK: `classes3.dex` contains the `Africa/Casablanca` policy string.

**Note on scope:** the desktop *application* source was not modified by R1–R5 (only its tests), so
the EXE/ZIP differ from `53dfed3` in the bundled `shared/` package. The **APK** carries genuine
functional change (W1 + W3).

---

## 9. PRODUCTION SAFETY

* Production access was **READ-ONLY**: one `POST /auth/login` for a token, every other call a `GET`.
* **No** row created, updated or deleted. **No** purge SQL run. **No** Fly.io deploy. **No** git push.
* `SYNC_7613` **not deleted** — documented below, awaiting your authorisation.
* Committed to a **branch**, not `main`.

### Data-contamination issue (separate from W1–W4) — REQUIRES YOUR DECISION

| Marker | Where | Effect |
| --- | --- | --- |
| `SYNC_7613` | live production vehicle `41f1ff38-43c8-47c2-8fe8-7cc0e665e16e`, `MAINTENANCE` | inflates `total_vehicles` → 3 and `maintenance` → 1 **right now** |
| `koo`, `pppppppppppppp` | live production vehicles | non-business registrations; your call whether real |
| `ForensicBrand`, `ProofModel`, `CRT-`, `REV-` | not present in the live vehicle list | — |

`scripts/purge_forensic_probes.sql` exists. **It has not been run and will not be without a direct
instruction.** Nothing in the schema distinguishes probe rows from real rows, so no automated check
can exclude them — this is a data problem, not a code problem.

---

## 10. REMAINING RISKS

| # | Risk | Severity | Status |
| --- | --- | --- | --- |
| 1 | **SQLite still discards tz offsets on write.** The policy now makes every runtime *agree* on what a naive value means, but a value written to SQLite as UTC-aware still returns as naive UTC digits and is read as business-local — a 1 h shift. Bounded in practice: the backend uses SQLite only in tests, and desktop stores ISO strings with explicit offsets in `String(50)` columns. A truly lossless fix needs a `TypeDecorator` across every timestamp column — too invasive for a release branch. | P2 | Documented; not fixed |
| 2 | **Deployed backend is still `53dfed3`.** W4 was PostgreSQL-inert (TIMESTAMPTZ is always aware), so production results are correct today — but production does not yet contain this fix. | P2 | Not deployed (per instruction) |
| 3 | **Devices still running the `53dfed3` APK retain W1.** The fix ships only with the new APK. | P2 | New APK built |
| 4 | `SYNC_7613` production contamination | P1 (operational) | Awaiting authorisation |
| 5 | **Adjacent-metric label collisions**: `today_rentals` (started today) vs `today_revenue` (pro-rata accrual); `maintenance` (occupied now) vs `active_maintenance_tickets` (all open, incl. future). Both pairs are correct and differently defined, and both read as contradictions on screen — the same class as the original `0 vs 2`. | P2 | Not changed (label/UX work, out of R1–R5 scope) |
| 6 | Kotlin uses `SimpleDateFormat`, which is lenient about some malformed inputs where Python's `fromisoformat` raises. No divergence in any tested vector. | P3 | Monitored by the parity vectors |

---

## 11. FINAL VERIFICATION STATEMENT

> **THE SAME BUSINESS EVENT + THE SAME STORED DATA + THE SAME INSTANT + THE SAME BUSINESS RULE
> ⇒ THE SAME OPERATIONAL METRIC ACROSS BACKEND + DESKTOP + MOBILE.**

Proven by: 26/26 shared vectors agreeing across Backend, Desktop and the normative reference under
direct execution; the same 26 vectors green on Kotlin via `FleetStatusParityTest` and
`CrossClientConvergenceTest`; nine Python coercion sites plus the Kotlin parser asserted to the same
instant; and half-open boundary parity for reservations and maintenance, on naive **and** aware rows,
at every edge (before / at start / during / just before end / at end / after).

> **`RENTED != AVAILABLE`** — asserted in `backend`, `desktop` and `mobile` suites, as **bucket
> disjointness** (never numeric inequality: equal counts are legitimate). The two metrics were not
> merged, and the guards forbid merging them.

> **Same metric across equivalent UI representations ⇒ same value** — Desktop by construction (the
> Dashboard cards and the Vehicles page render from one `DomainSnapshot`), Mobile now likewise, with
> `DashboardVehiclesParityTest` proving it holds even while the server reports a different fleet.

---

## FINAL VERDICT

> # `GO — CROSS-RUNTIME DATA CONSISTENCY VERIFIED`

Justification against the stated bar — *"do not declare GO if any backend/desktop/mobile metric can
still diverge for the same business state"*:

* The one input class that could diverge (offset-less datetimes) now resolves identically in all
  three runtimes, is pinned by shared vectors, and is guarded by tests **proven to fail** when the
  defect is reintroduced.
* The one metric that had two publishers (mobile fleet counts) now has exactly one, chosen
  statically rather than at runtime.
* The backend no longer disagrees with itself between SQLite and PostgreSQL.
* Full suites green: **Backend 248/248, Desktop 352/352, Mobile 79/79.**
* P0 orphan protection from `53dfed3` intact.
* Artifacts rebuilt from `de6b493`, provenance verified, SHA256 recorded.

The residual risks in §10 are **documented, bounded, and none of them can make two runtimes report
different values for the same business state** — items 1–3 are deployment/legacy-storage exposure,
items 4–5 are data and labelling matters outside R1–R5.

**Two decisions remain yours:** whether to push/deploy `de6b493`, and what to do about `SYNC_7613`.
Neither was performed.
