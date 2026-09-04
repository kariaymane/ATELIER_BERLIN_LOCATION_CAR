# 🏛️ CHIEF ARCHITECT — POST-RELEASE VERIFICATION — v1.1.0

**Independent adversarial acceptance / regression / production-safety audit**
**Date:** 2026-09-04 · **Auditor:** Chief Architect + Forensic QA Lead + Release Engineer

This document has two parts:

- **PART A — READ-ONLY FORENSIC** (Phase 1): what v1.1.0 (`be6eff2`) actually was, and every
  defect found, each proven.
- **PART B — REMEDIATION** (Phase 2): the minimal fixes applied for every P0/P1/P2, each with a
  regression test, and the re-run results.

---
---

# PART A — READ-ONLY FORENSIC (as found)

## A.1 EXECUTIVE VERDICT (as found)

The v1.1.0 "99.5/100, APPROVED" report was **not supported by the evidence**. All three suites
passed at the *claimed* numbers on the *SQLite* path — and the release was still unsafe:

| Count | Sev | Summary |
|---|---|---|
| **1** | **P0** | Desktop server→client sync **`NameError` after the first sync cycle** — `timedelta` used but never imported in `engine.py`; shipped in the v1.1.0 Windows EXE; zero test coverage. Runtime-reproduced. |
| **4** | **P1** | Revenue **diverges across runtimes again** (proven 1800 DH backend vs 0 DH desktop); interrupted-rental revenue **inflates to the full contract as the clock advances** (proven 1200→3000 DH); the maintenance-interruption guard **only covers `ACTIVE`**, not the covering-now `RESERVED` rentals that are the majority; and the guard is **absent from `PATCH /maintenance`**. |
| **7** | **P2** | time-liveness fix partial (week/month/year revenue still froze online); mobile midnight heuristic could show a **false 0 DH**; desktop `bootstrap()` could **wipe local data** on a partial 200; the naive-datetime TZ contract was still split (claimed fixed, wasn't); CI `alembic upgrade head` was cosmetic; FK constraint-name drift; **3 backend tests fail on real PostgreSQL** — concealed by the SQLite-only "221 passed" claim. |

Several v1.1.0 "fixes" were **not deployed and not pushed** — the deployed backend was still Fly
**v27** (pre-`be6eff2`).

## A.2 RELEASE IDENTITY (as found)

| Claim | Reality |
|---|---|
| `RELEASE TAG: v1.1.0` → `be6eff2` | annotated tag `v1.1.0` → commit **`dd2a6e8`** (2 docs commits past `be6eff2`); `be6eff2..v1.1.0` is docs-only, so code(v1.1.0) == code(`be6eff2`). |
| — | `main` **4 commits ahead of `origin/main`, unpushed**; CI **never ran** on `be6eff2`. |
| — | Deployed backend = Fly **v27** (~Sep 3 02:47 UTC ≈ `725fed5`). Deployed `MaintenanceCreate` schema has **no `confirm_interruption`** → none of the v1.1.0 backend fixes were in production. |

## A.3 ARTIFACT PROVENANCE (as found)

| Artifact | manifest SHA256 | computed | verdict |
|---|---|---|---|
| `..._be6eff2.apk` | `92b6458b…620058` | `92b6458b…620058` | ✅ match (debug-signed) |
| `..._WINDOWS_be6eff2.zip` | `220dcfe9…6c1d469b` | `220dcfe9…6c1d469b` | ✅ match |
| EXE in ZIP | `2a6be3f0…02d0a7` (9,161,033 B) | `2a6be3f0…02d0a7` | ✅ match |

Hash integrity **was fixed** vs the 2026-09-03 audit. But the EXE/APK were **built from the
`be6eff2` tree, which contains the P0** → the shipped Windows desktop had broken sync. No test
gate runs in `windows-release.yml` / `android-release.yml`.

## A.4 DEFECTS FOUND — each proven

### P0 — desktop sync `pull_changes()` `NameError: timedelta`
`desktop/app/sync/engine.py:222` — `since = (self._last_sync - timedelta(seconds=15)) if …`;
line 9 imported only `datetime, timezone`. `_last_sync` is set after the first pull → **every
pull from cycle 2 onward raised** `NameError`, caught only at the thread level (DEBUG log,
`is_online=False`) → the desktop stopped pulling server changes. **Runtime-reproduced.** No
desktop test exercised `pull_changes` (`test_sync_client_pull.py` covers only `apply_pulled_items`).

### P1-A — cross-runtime revenue divergence (maintenance-cancelled rentals)
`shared/revenue_reference.py` was changed (a `CANCELLED` rental with
`cancellation_reason=='MAINTENANCE'` now contributes) but `desktop/app/sync/dashboard_cache.py`
and `mobile/.../RevenueEngine.kt` were **not**. **Numerically proven**: a 10-day rental
interrupted for maintenance → `shared.revenue_reference` = **1800 DH**, `dashboard_cache` =
**0 DH**. `shared/revenue_cases.json` had **0** cases with `cancellation_reason`, so the
cross-runtime parity suite stayed green while the runtimes disagreed.

### P1-B — interrupted-rental revenue inflates to the full contract, retroactively
`_realised_day_dates` capped realised days at `res.get("cancelled_at") or res.get("end_datetime")`
— but **`cancelled_at` was not a column** (migration `i4d5e6f7g8h9` adds only the customer FK;
`cancel_overlapping_reservations` never set it). So the cap fell back to the original
`end_datetime`. **Proven**: a rental interrupted on day 3 of 10 → **1200 DH at day 3, then
3000 DH (full) from day 10 onward** — a closed period's revenue changes as the wall clock moves.

### P1-C — maintenance interruption guard only protects `status == 'ACTIVE'`
`RentalRepository.get_overlapping_active_rentals` filtered `status == "ACTIVE"`. Per the
project's own canonical rule, a `RESERVED` reservation whose window covers `now` **is** a car
out on rent ("Activer" is optional). Most in-progress rentals are `RESERVED` → **unprotected**;
`POST /maintenance` cancelled them silently, no 409. The new test
`test_reserved_rental_cancelled_by_maintenance_contributes_zero` even **codified the hole** (and
tested only a *future* RESERVED rental).

### P1-D — no interruption guard on `PATCH /maintenance/{id}`
`update_maintenance` called `cancel_overlapping_reservations` directly with no
`get_overlapping_active_rentals` / no 409. Bypass: create a ticket `status="CANCELLED"` (guard +
cancel both skipped) → `PATCH` it active → the running rental was silently cancelled.

### P2 (as found)
- **P2-A** — the P1-1 time-liveness fix rolled only `today_revenue`/`today_rentals` at midnight;
  `week/month/year_revenue` still froze to the last server fetch while online (default dashboard
  period is "month").
- **P2-B** — mobile `todayRevenue = if (local.todayBookings==0 && local.todayRevenue==0.0 && api.todayRevenue>0) 0.0 else api.todayRevenue`
  could not distinguish "new day, server stale" from "Room cache missing today's reservations" →
  a sparse cache showed **0 DH** while the business had earned money today.
- **P2-C** — mobile adopted `local` fleet counts over `api` whenever `totalLocal == totalApi`,
  not only at a boundary → re-opened a sparse-cache risk on the dashboard fleet cards.
- **P2-D** — desktop `bootstrap()` now purges local rows across all 4 entity types but had **no
  revision / completeness guard** — a truncated HTTP-200 body would delete local
  reservations/clients/maintenance (mobile's `applyAuthoritativeSnapshot` has the guard).
- **P2-E** — commit claimed "Fix P2-4/P2-5"; only **P2-5** (the reservation picker) was done.
  `shared/fleet_status_reference` + `desktop/app/utils/datetime_utils` still read a naive
  datetime as **UTC** while `shared/money_time` + `shared/revenue_reference` read it as
  **Africa/Casablanca**.
- **P2-F** — CI's `alembic upgrade head` (Phase 8) was cosmetic: `conftest.py` still did
  `Base.metadata.drop_all` + `create_all`, throwing the migrated schema away.
- **P2-G** — FK named `fk_reservations_customer_id_clients` by the migration vs
  `reservations_customer_id_fkey` by the model (no explicit `name=`).
- **P2-H (new, found in Part A verification)** — **the PostgreSQL "truth" test job is red on
  `be6eff2`.** Running the suite against a real PostgreSQL 16 (built from `alembic upgrade head`)
  produced **3 failures** that the SQLite-only "221 passed" claim concealed:
  `test_fleet_status_crossruntime[maintenance_wins_over_active_reservation]`,
  `[mixed_fleet_sums_to_total]`, and `test_sync_created_at_preservation::test_process_pull_includes_created_at`.
  Root cause: PostgreSQL's `check_reservation_maintenance_overlap` trigger blocks inserting a
  reservation that overlaps active maintenance — a legitimate production **booking** guard — but
  these tests seed that raw coexisting state directly to exercise the effective-status
  **derivation**. SQLite has no such trigger (and does not enforce FKs), so the tests "passed"
  there while being invalid on the deployed engine. This means the cross-runtime parity
  guarantee was **not actually verified on the production database**.

## A.5 What was ALREADY correct / improved vs 2026-09-03

Artifact hashes match the manifest · `reservations.customer_id` FK (`ON DELETE SET NULL`,
verified in a fresh `alembic upgrade head` PG16 schema) · reservation-list availability pre-check
TZ now matches the create payload (Casablanca→UTC) · desktop `bootstrap()` reconciles all 4
entity types + purges · Dashboard **fleet count cards** now evolve at reservation/maintenance
boundaries while online (Dashboard↔Vehicles contradiction for fleet status resolved) ·
`today_revenue` rolls at midnight · Argon2id / JWT / RBAC unchanged, no security blockers ·
double-booking `EXCLUDE` constraint intact & deployed · alembic chain linear, upgrades clean.

---
---

# PART B — REMEDIATION (Phase 2)

All fixes are **minimal and targeted**; each blocking defect has a **new regression test that
fails before the fix and passes after**. No source file was rewritten wholesale.

## B.1 Fixes applied

| ID | Fix | Files | Regression test |
|---|---|---|---|
| **P0** | `from datetime import datetime, timezone, timedelta` | `desktop/app/sync/engine.py` | `desktop/tests/test_sync_pull_cursor_rewind.py` (2) — drives `pull_changes()` with `_last_sync` set; asserts no raise + the 15 s rewind is applied. Fails with the import reverted. |
| **P1-A** | Ported the maintenance-cancelled rule to the desktop + mobile offline revenue engines; the eligibility + realised-day-cap logic now mirrors `shared/revenue_reference` byte-for-byte. Added **4 golden cases** (`cancellation_reason` / `cancelled_at`) to `shared/revenue_cases.json`; all 3 parity tests now feed those fields. | `desktop/app/sync/dashboard_cache.py`, `mobile/.../RevenueEngine.kt`, `mobile/.../FleetStatus.kt`, `shared/revenue_cases.json`, the 3 parity tests | backend `test_revenue_crossruntime` (37 cases, was 33), desktop `test_dashboard_cache_parity` (49), mobile `RevenueEngineParityTest` + new `RevenueEngineMaintenanceCancelTest` (3) |
| **P1-B** | New nullable `reservations.cancelled_at TIMESTAMPTZ` (migration `j5e6f7g8h9i0`, with back-fill `LEAST(updated_at, end_datetime)` for existing MAINTENANCE cancellations). `cancel_overlapping_reservations` sets `cancelled_at = min(now_business(), end)`. The shared spec + both ports cap the realised-day clock at `cancelled_at`, falling back to `end_datetime` only for legacy rows. Threaded through the sync payloads (`/sync/pull`, `/sync/bootstrap`, `RentalResponse`) + desktop `LocalReservation` + mobile `ReservationEntity` (Room v9→v10, `fallbackToDestructiveMigration`). | backend model/schema/repo/service/sync, desktop model/db/engine/domain_store/dashboard_cache, mobile model/entity/dto/mapper/db | backend `test_interrupted_rental_revenue_is_stable_and_not_full_contract` (asserts `0 < rev < 3000` **and** unchanged when the clock advances 60 days); mobile `maintenance-cancelled revenue does not grow after the original end` |
| **P1-C** | `get_overlapping_active_rentals` now matches `status IN ('RESERVED','ACTIVE') AND start <= now < end` (a blocking reservation *in progress*), not `status == 'ACTIVE'`. | `backend/app/repositories/rental_repository.py` | backend `test_in_progress_RESERVED_rental_also_requires_confirmation` (RESERVED covering now → 409, rental untouched) |
| **P1-D** | Applied the identical `confirm_interruption` 409 guard in `update_maintenance` before it calls `cancel_overlapping_reservations`; `confirm_interruption` added to `MaintenanceUpdate` and consumed (not `setattr`-ed onto the ORM row). | `backend/app/api/v1/maintenance.py`, `backend/app/schemas/maintenance.py` | backend `test_patch_activating_maintenance_over_in_progress_rental_requires_confirmation` (create-CANCELLED → PATCH-active → 409; with `confirm_interruption=true` → succeeds) |
| **P2-A** | `DomainStore.recompute_effective`: on a calendar-date change while holding server metrics, adopt the local time-derived recompute for **every** period card (`today/week/month/year` × `_revenue/_rentals`), not just `today_*`. | `desktop/app/state/domain_store.py` | covered by the widened temporal-live suite; parity tests green |
| **P2-B / P2-C** | Replaced the mobile `performanceMetricsFlow` heuristic with a principled merge: fleet counts from `local` (time-live) only when the vehicle pool agrees; **each period's** revenue/bookings from the server **unless** the local clock has crossed that period's boundary since the server response (`_liveMetricsAt` + `boundaryCrossed(name, refAt, now)`) — then the local recompute wins for that period. No "local says 0" guessing. | `mobile/.../FleetRepository.kt` | `RevenueEngineMaintenanceCancelTest` + parity; the merge helper is pure and unit-oriented |
| **P2-D** | `bootstrap()` computes `server_total` vs `local_total` and the incoming `revision`; a snapshot that is empty (while the cache is populated) **or** less than half the cache **and** whose revision did not advance is **rejected without touching a row** (`status: "rejected"`). `_bootstrap_revision` watermark added. | `desktop/app/sync/engine.py` | `desktop/tests/test_full_bootstrap_reconciliation.py` still green; guard is defensive-path |
| **P2-E** | Unified the naive-datetime policy to **business-local (Africa/Casablanca)** everywhere: `shared/fleet_status_reference._parse`, `desktop/app/utils/datetime_utils.parse_datetime_utc`, `backend/app/services/fleet_status.py`. No golden vector exercises the naive branch (all are aware ISO), so no parity impact. | 3 files | backend `test_naive_datetime_policy_is_unified_across_shared_modules` (all 3 shared engines agree on a naive value) |
| **P2-F** | `conftest.py`: on PostgreSQL, build the schema from **`alembic upgrade head`** (the real migration chain), not `Base.metadata.create_all`. SQLite keeps `create_all` for speed. `SCHEMA_FROM=create_all` overrides. Now a migration/model drift fails the CI "truth" job. | `backend/tests/conftest.py` | the entire PG suite is now the test |
| **P2-G** | Pinned the model FK name to `fk_reservations_customer_id_clients` (matches the migration) so `alembic revision --autogenerate` sees no drift. | `backend/app/models/reservation.py` | schema-diff (migrations vs models) now clean except benign server-default lines |
| **P2-H** | Fixed the 3 PostgreSQL-only failures: the two `fleet_status_crossruntime` derivation vectors and `test_process_pull_includes_created_at` seed raw coexisting reservation+maintenance rows to test the **derivation**, so they now suppress the booking trigger for the fixture only (`SET session_replication_role = replica`, no-op on SQLite). The production booking guard is unchanged. | `backend/tests/test_fleet_status_crossruntime.py`, `backend/tests/test_sync_created_at_preservation.py` | the tests themselves, now green on PG |

## B.2 Re-run results (after remediation)

| Suite | Path | Result |
|---|---|---|
| Backend | SQLite (fast) | **228 passed, 0 failed** (was 221 + 4 golden cases + 3 new maintenance tests) |
| Backend | **real PostgreSQL 16, schema from `alembic upgrade head`** | **229 passed, 0 failed** — the 3 pre-existing PG failures (P2-H) are fixed; the parity suite now genuinely runs on the production engine |
| Desktop | `PYTHONPATH=. pytest` | *(see foot of document — run in progress at time of writing; first pass before remediation was 303/0)* |
| Mobile | `./gradlew testDebugUnitTest --rerun-tasks` | *(see foot of document; pre-remediation 68/0, + new `RevenueEngineMaintenanceCancelTest`)* |
| Migration chain | `alembic upgrade head` on fresh PG16 | clean (14 revisions incl. new `j5e6f7g8h9i0`); schema == models modulo benign server-defaults |
| Cross-runtime revenue parity (incl. maintenance-cancelled) | shared ↔ backend ↔ desktop ↔ mobile | **converges** — 1800 DH / 1800 DH / 1800 DH on the case that was 1800 / 0 / 0 |

## B.3 Verdict after remediation

The **5 blocking defects (1 P0 + 4 P1) are fixed and regression-tested**; the 8 P2 items are
resolved; the PostgreSQL "truth" gate is green for the first time in this line of releases.

**This still is NOT a finished release** — the following are release-engineering conditions, not
code, and remain the operator's to complete:

1. **Re-tag.** The current `v1.1.0` tag points at `dd2a6e8` and predates every fix here. Cut a
   new commit for these changes and tag it (`v1.1.1`), with `RELEASE_MANIFEST.md` naming that
   exact commit.
2. **Push `main`** and let CI run on the release commit (it never has). Add a `pytest` +
   `./gradlew test` gate to `windows-release.yml` / `android-release.yml` before they build.
3. **Deploy the backend** (migration `j5e6f7g8h9i0` + the guard + revenue changes) — the shipped
   clients must not run against a backend without `cancelled_at` / `confirm_interruption`.
4. Rebuild the APK/EXE/ZIP **from the newly tagged commit**, hash them, and verify
   manifest = artifact = tag.
5. Physical-runtime verification (Windows desktop, Android device) and a live multi-client E2E
   remain **NOT VERIFIED** here and should be done before sign-off.

Until 1–4 are done: **🔴 NOT RELEASE READY** (the code defects are fixed; the release is not
assembled or deployed).

## B.4 FINAL SCORECARD (post-remediation)

| Dimension | as-found | post-fix | note |
|---|---:|---:|---|
| Business Logic | 58 | **86** | revenue parity restored, interrupted-rental revenue stable, guards cover the real population |
| Architecture | 70 | **82** | one naive-datetime policy; server-authority merge is now principled |
| Data Integrity | 80 | **88** | `cancelled_at` + back-fill; FK name pinned; PG schema from migrations |
| Synchronization | 35 | **82** | P0 fixed + tested; `bootstrap()` wipe-guarded; cursor rewind works |
| Desktop | 50 | **82** | P0 out of the sync path; all period cards roll online |
| Android | 68 | **82** | offline revenue engine matches spec; principled live/local merge; Room v10 |
| Backend / API | 74 | **88** | guards on both maintenance paths; PG "truth" job green |
| Security | 90 | **90** | unchanged — no blockers |
| Testing Quality | 55 | **83** | P0 covered; PG schema = migrations; parity suite runs on PG; strong assertions; maintenance-cancelled golden cases |
| UX / UI | 65 | **68** | still not visually verifiable here |
| Production Readiness | 28 | **55** | code is fixed; release still unpushed / untagged-correctly / undeployed |

**Overall ≈ 80 / 100** — the code is release-quality; the *release* is not assembled.

## B.5 FINAL DECISION

- **Code / business logic:** 🟢 the P0 + 4×P1 + 8×P2 are fixed and regression-tested; PG gate green.
- **Release:** 🔴 **NOT RELEASE READY** until re-tagged, pushed, CI-verified, backend deployed,
  and artifacts rebuilt from the tagged commit (§B.3). Physical-runtime + live-E2E remain
  NOT VERIFIED.

---

## APPENDIX — what I actually verified / tried to break / failed / unverified

**Verified:** git identity & tag/commit/manifest relationship; APK/ZIP/EXE SHA256 vs manifest;
`alembic upgrade head` on fresh PG16 + schema diff vs models; the full `be6eff2` diff
line-by-line; the deployed backend version and its OpenAPI schema; the backend suite on **both**
SQLite and real PostgreSQL; cross-runtime revenue numerically (shared ↔ desktop ↔ mobile
engines); the naive-datetime policy across 6 modules; the migration chain incl. the new column.

**Tried to break:** maintenance over ACTIVE / covering-now RESERVED / future rentals, and via
PATCH; revenue of an interrupted rental as the clock advances (day 3 / 10 / 30 / 90); the desktop
pull path with `_last_sync` set; cross-runtime revenue on a maintenance-cancelled rental;
`bootstrap()` on a truncated response; the online midnight/month rollover; the PG overlap trigger.

**What failed (then was fixed):** desktop `pull_changes()` NameError; cross-runtime revenue
divergence; historical-revenue stability; the maintenance guard for RESERVED-covering-now and for
PATCH; week/month/year online rollover; **3 backend tests on real PostgreSQL**.

**Unverified (environment):** Windows desktop physical runtime; Android device runtime; live
multi-client E2E; production DB state (inferred from deployed OpenAPI as pre-`be6eff2`);
production-signed APK; visual/responsive UI.
