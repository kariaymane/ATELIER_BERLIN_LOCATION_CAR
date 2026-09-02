# DASHBOARD + LIVE-DATA + DESKTOP ↔ MOBILE SYNC — FORENSIC REPORT

**Date:** 2026-09-02
**Branch:** `fix/dashboard-live-sync-forensic` (off `8b308c2`)
**Production:** `https://car-rental-system.fly.dev` (release v23, PostgreSQL live, recovered this session)

The dashboard screenshot was captured **while the production PostgreSQL was
down** (crashed 2026-08-30, recovered + redeployed earlier this session). With
the DB down every `/dashboard/*` call 500'd, so the desktop fell back to its
initial empty state — that is what produced "0.00 DH", "Aucune location", and a
stale local cache. Everything below is verified against the **live, recovered**
backend.

---

## 1. ROOT CAUSE — REVENUE (`Chiffre d'affaires` = 0.00 DH)

**Not a bug — the canonical rule is working; the period genuinely had no
activity — but a missing "year" view hid the real turnover.**

Forensic trace of the live production data (11 reservations):

| what | value |
|---|---|
| `/dashboard/daily` revenue | `0.00` |
| `/dashboard/weekly` revenue | `0.00` |
| `/dashboard/monthly` revenue | `0.00` |
| **`/dashboard/yearly` revenue** | **`48 500.00` (7 rentals)** |

Every non-cancelled reservation in production **started between 25–29 August
2026**. The project's **canonical rule** (`RentalRepository.get_revenue_between`,
`dashboard_cache.compute_overview_rows`, `FleetStatus.dashboardOverview`) —
unchanged — recognises revenue **when a rental starts**:

```
Revenue(period) = SUM(total_price)
  WHERE status != 'CANCELLED'
    AND start_datetime <= now
    AND period_start <= start_datetime < period_end   [Africa/Casablanca]
```

So September's today/week/month cards are **correctly 0** — nothing started in
September. The full-year figure (`48 500 DH`) was simply never surfaced.

**Fix (canonical, no new formula):** added `year_revenue` / `year_rentals` to
`get_overview()` using the **same** `get_revenue_between` / `count_rentals_between`
over a `[Jan 1, next Jan 1)` Africa/Casablanca window; mirrored in
`dashboard_cache.compute_overview_rows` (desktop offline) and
`FleetStatus.dashboardOverview` (mobile). Desktop gets a **"Cette année"**
option in the period selector; mobile gets a 4th **"Cette année"** revenue card.

**Verified identical across runtimes** for the same dataset (`5000+1000+3000+800
= 9800`): backend `test_dashboard_year_and_top.py`, desktop
`test_dashboard_year_and_top_local.py`, mobile `DashboardYearRevenueTest.kt`.

---

## 2. ROOT CAUSE — TOP 5 ("Aucune location enregistrée")

**Two causes.**

**2a. The screenshot** — `/dashboard/vehicle-performance` 500'd while the DB was
down; the desktop showed `[]` → the empty-state label. The **live** endpoint now
returns the correct data:

```
fca6c82c (koo / ll kkkk)          rental_count=4   total_revenue=41850.0
41f1ff38 (SYNC_7613/ForensicBrand) rental_count=2   total_revenue=3500.0
6395acba (pppppppppppppp/cici oo)  rental_count=1   total_revenue=3150.0
```

**2b. A real latent crash** — `DashboardService.get_vehicle_performance` did
`datetime.now(tz) - datetime.fromisoformat(stat["last_rental"])`. When
`last_rental` serialises **naive** (SQLite, or any naive TIMESTAMP column) that
raises `TypeError: can't subtract offset-naive and offset-aware datetimes` →
**the whole endpoint 500s and the Top-5 panel blanks**. Reproduced in a test;
**fixed** by normalising both sides to aware-UTC before subtracting.

**2c. Offline resilience** — Top-5 was **server-only**. Added a canonical local
computation (`compute_top_vehicles_rows` — identical eligibility to
`RentalRepository.get_vehicle_stats`: `status != CANCELLED AND start <= now`,
ranked by revenue desc) carried on `DomainStore.snapshot.top_vehicles`. The
desktop now: prefers the server list, falls back to the local list, and an
empty `[]` from a failed `/vehicle-performance` **no longer wipes** a good
Top-5. So the panel is blank **only** when there is genuinely no started,
non-cancelled rental history.

Tests: backend `test_dashboard_year_and_top.py` (CASE C/D/F), desktop
`test_dashboard_year_and_top_local.py`.

---

## 3. ROOT CAUSE — DESKTOP / MOBILE INCONSISTENCY

The screenshot's "1/5" implied a **stale desktop SQLite cache** (5 vehicles;
production now has 3). There was no divergent formula — desktop, mobile and
backend all derive fleet status + revenue from the **shared normative spec**
(`shared/fleet_status_reference.py` ↔ `desktop/app/utils/fleet_status.py` ↔
`mobile/.../FleetStatus.kt`, proven by the cross-runtime parity suites, all
green). The desktop simply hadn't re-synced after the outage.

**Live 3-way check on the real production snapshot** (this session):

| vehicle | backend API `effective_status` | shared reference | desktop derivation |
|---|---|---|---|
| fca6c82c | AVAILABLE | AVAILABLE | AVAILABLE |
| 6395acba | AVAILABLE | AVAILABLE | AVAILABLE |
| 41f1ff38 | RENTED | RENTED | RENTED |

Dashboard counts — backend `/stats` == reference `fleet_counts` == desktop
`compute_fleet_counts`: `{total 3, available 2, reserved 0, rented 1, maintenance 0}`.
**0 mismatches.** `year_revenue` is now the same canonical window in all three.

---

## 4. VEHICLES IN RENTAL — "1/5" → "1"

`desktop/app/ui/dashboard.py`: the `ExecutiveFleetCard` for
`dashboard.rented_fleet` was built with `has_progress=True`, which rendered a
`f"{current}/{total}"` ratio label **and** a progress bar. Removed
`has_progress` for that card and dropped the `current=`/`total=` args at the
call site. The card now renders **only the count** (canonical effective status
`RENTED`) — no `/5`, no `1 sur 5`, no gauge. Mobile already showed only the
count (`FleetCountCard(count = metrics.rentedVehicles)`).

Test rewritten: `test_desktop_dashboard.py::test_vehicules_en_location_shows_only_the_count_no_denominator`
asserts the count is `"2"` and that **no** `QLabel` on the card contains `/` or
` sur `, and `_ratio_lbl` / `_prog_bar` no longer exist.

---

## 5. MOBILE CACHE RESET

`AppDatabase` version `8 → 9` (schema unchanged). `fallbackToDestructiveMigration`
is already configured, so first launch of this build **wipes the local Room
mirror** (stale vehicles/reservations/maintenance/notifications/sync-metadata),
`META_CACHE_COMPLETE` disappears, and `refreshAll()` routes to
`bootstrapAndReset()` → **one clean INITIAL sync from FastAPI/PostgreSQL**.
Room becomes a fresh mirror of authoritative backend data. **Cache only — no
PostgreSQL data is touched.**

---

## 6. STATIC / MOCK DATA REMOVED

Full search (`mock`, `fake`, `dummy`, `hardcod`, `placeholder`, `demo`,
`sampleData`, `FakeRepository`, `MockRepository`, `TestRepository`, hardcoded
revenue/count/Top-5 literals) across `desktop/app` and `mobile/app/src/main`:

**Nothing removed — nothing found.** All "placeholder" hits are legitimate
`setPlaceholderText` / Compose `placeholder =` input hints. `PerformanceMetrics`
is constructed in exactly two places, both in `FleetRepository` (local canonical
compute + `/dashboard/stats`). Dashboard cards initialise to `"0"` and are
overwritten on the first `refresh_data`; no fabricated business values anywhere.

---

## 7–8. LIVE SYNCHRONISATION ARCHITECTURE + SERVER AUTHORITY

**Unchanged — audited and proven working.**

```
Desktop/Mobile action → FastAPI mutation → PostgreSQL COMMIT
   → EventBroadcaster.broadcast_event()  (backend/app/services/event_broadcaster.py)
   → WS frame on /api/v1/events/ws  (also /api/v1/events/recent replay)
   → Mobile RealtimeSyncManager.onMessage → FleetRepository.handleRealtimeEvent
   → authoritative re-fetch of the affected entity (server is the truth)
   → Room upsert (revision/updated_at guarded) → Compose state invalidation → UI
```

Broadcast call-sites confirmed: `rentals.py` ×5 (create/activate/complete/cancel/update),
`maintenance.py` ×5, `vehicles.py` ×4 (create/update/status/delete),
`notification_service.py` ×3 (create/read/read-all).

Mobile reconnect: `RealtimeSyncManager` — exponential backoff (2s ×1.5, capped),
post-reconnect catch-up sync, 20s fallback polling if the socket stays down.
`handleRealtimeEvent` never trusts the frame's payload — it re-fetches the
authoritative record; `applyAuthoritativeSnapshot` is revision-guarded (a
stale snapshot is rejected), so no old event can overwrite newer Room data and
no duplicates are created.

**No manual-refresh dependency:** the mobile event handler runs automatically on
every frame; no app restart / Room wipe / hidden button is required.

---

## 9. DASHBOARD CONSISTENCY (Desktop == Mobile)

One canonical backend response (`/dashboard/stats`) + one shared derivation
spec. Both clients also recompute the **same** figures locally from their cache
for offline/time-live behaviour, and both are tested against the shared vectors:

| figure | source |
|---|---|
| revenue (today/week/month/**year**) | `get_revenue_between` == `compute_overview_rows` == `FleetStatus.dashboardOverview` |
| rented / available / reserved / maintenance | `compute_fleet_counts` (shared `fleet_status_reference`) |
| Top 5 | `get_vehicle_stats` == `compute_top_vehicles_rows` |
| today's reservations, returns, active rentals | `/dashboard/stats` |

Cross-runtime parity suites (all green): mobile `FleetStatusParityTest` +
`CrossClientConvergenceTest`; backend `test_fleet_status_crossruntime` +
`test_fleet_status_parity`; desktop `test_fleet_status_crossruntime` +
`test_fleet_parity_desktop`.

---

## 10. DATE/TIME + REVENUE FORENSIC

- All revenue/period math uses `ZoneInfo("Africa/Casablanca")` local midnight
  bounds (backend + desktop) / `TimeZone("Africa/Casablanca")` (mobile).
- `datetime` comparisons are all aware; the one naive/aware crash found
  (`get_vehicle_performance`, §2b) is fixed.
- Two **pre-existing test fixtures** that seeded local-wall-time but the code
  reads UTC were made hour-independent (`test_dashboard_cache_parity.py` — seed
  in UTC, `now - 30min`). Not a production bug.

---

## 11. TEST DATABASE ISOLATION

`backend/tests/conftest.py` hard-aborts if `DATABASE_URL` contains
`prod`/`fly`/`supabase`/`production`; all backend tests run on
`sqlite+aiosqlite:///:memory:`. Desktop tests use a throw-away local SQLite.
Explicit seeds for CASE A–F are in `test_dashboard_year_and_top.py` /
`test_dashboard_year_and_top_local.py`.

---

## 12. END-TO-END LIVE TEST (real production, CASE E)

```
1  WS connect  wss://…/api/v1/events/ws  (Bearer)  → "CONNECTED" frame          OK
2  POST /api/v1/rentals/  (Desktop-style create, future 2027 dates)  → HTTP 201  OK  id=50d32a08…
3  WS frame                                                                       RESERVATION_CREATED  (+ NOTIFICATION_CREATED)
        entity_type=reservation  entity_id=50d32a08…  vehicle_id=6395acba…
        message: "🚗 Nouvelle réservation … depuis Desktop."
4  POST /api/v1/rentals/50d32a08…/cancel  → HTTP 200                               OK
5  WS frame                                                                       RESERVATION_STATUS_CHANGED  (+ NOTIFICATION_CREATED)
```

The probe rental (`50d32a08…`, dated 2027, now `CANCELLED`) is inert — cancelled
+ future, excluded from revenue, Top-5 and fleet counts. It is left in place
(cancelled rows are audit history; not deleted).

`GET /api/v1/events/recent?limit=5` (authenticated) → `HTTP 200`.
`GET /health/ready` → `200 database:"connected"`, pool size 5.

---

## 13. RESPONSIVENESS

Not regressed. `DashboardWidget` keeps the `QScrollArea` (from `9822831`) and the
`FlowLayout` KPI/fleet rows that reflow horizontally. Removing the progress bar
from the rented card slightly *reduces* its height. Offscreen size sweep
(1920×1080 → 820×560): Dashboard `minWidth` unchanged, no horizontal overflow.

---

## 14. FINAL FORENSIC SEARCH — see §6. No mock/fake/hardcoded dashboard data,
no test repository in production, no duplicated revenue or status formula.

---

## 15. TESTS

| Suite | Result |
|---|---|
| **Backend** `pytest` | **145 passed** (140 + 5 new `test_dashboard_year_and_top.py`) |
| **Desktop** `pytest` | **228 passed, 1 failed** — `test_domain_store_temporal::test_forensic_state_changes_because_time_passed`, a pre-existing wall-clock flake under full-suite time pressure (passes 3/3 in isolation; `git diff` shows this branch touched neither that test nor `boundary_clock.py`) |
| **Mobile** `:app:testDebugUnitTest` | **65 passed** (64 + 1 new `DashboardYearRevenueTest`) |
| **Mobile** `:app:assembleDebug` | BUILD SUCCESSFUL |

## 16–20. see the FINAL OUTPUT block in the chat reply.
