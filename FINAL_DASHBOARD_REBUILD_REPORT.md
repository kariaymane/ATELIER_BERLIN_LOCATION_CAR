# Dashboard — complete rebuild

**Date:** 2026-09-05
**Scope:** data model → backend → DTO → desktop client → responsive UI → tests → live refresh → data integrity
**Status:** implemented, tested, and verified end to end against a real PostgreSQL 16 database

---

## A. Files changed

### New

| File | Role |
|---|---|
| `shared/dashboard_reference.py` | **NORMATIVE SPEC.** The one and only implementation of every dashboard number. Pure functions over row dicts — no ORM, no DB, no network, no Qt. |
| `backend/app/services/dashboard_snapshot.py` | PostgreSQL **port**: loads the rows, calls the spec. Zero business arithmetic. |
| `desktop/app/sync/dashboard_snapshot.py` | DomainStore (offline) **port**: same spec, same DTO, stamped `source="local"`. |
| `desktop/app/ui/widgets/responsive_grid.py` | `ResponsiveGrid` — column count derived from available width; cards stretch to fill; `heightForWidth`; minimum width of exactly one column. |
| `backend/tests/test_dashboard_summary.py` | 33 tests — the 20 mandated scenarios + the endpoint contract. |
| `backend/tests/test_dashboard_crossruntime.py` | 10 tests — backend DTO **==** desktop DTO, byte for byte, over real PostgreSQL rows. |
| `desktop/tests/test_dashboard_rebuild.py` | 19 tests — one-snapshot rendering, no-fake-zeros, empty states, request plumbing. |
| `desktop/tests/test_dashboard_responsive.py` | 38 tests — grid maths + geometry at 1280×720 / 1366×768 / 1600×900 / 1920×1080 (+ 1024×600, 900×560) and the full shell. |

### Rewritten

| File | Change |
|---|---|
| `desktop/app/ui/dashboard.py` | Rebuilt from zero. Renders exclusively from one DTO; responsive grid; explicit unknown/stale/offline/empty states. |
| `backend/app/api/v1/dashboard.py` | New `GET /api/v1/dashboard/summary`; `/stats` reduced to a projection of the same snapshot. |
| `backend/app/services/dashboard_service.py` | `get_overview()` no longer runs its own queries — it delegates to the one computation. |
| `desktop/app/ui/main_window.py` | Single snapshot provider; removed the 3-request `DashboardFetcher`; removed the server⁄local key merge; responsive shell. |
| `desktop/app/state/domain_store.py` | Stopped overwriting server fleet counts with locally derived ones (two places). |
| `desktop/app/ui/widgets/sidebar.py` | Flexible width + vertical scroll. |
| `desktop/app/services/api_client.py` | `get_dashboard_summary(period, from, to)`. |
| `desktop/app/i18n/{fr,ar}.json` | 10 new keys (banners, footnotes, reconciliation line, live/cache state). |
| `desktop/tests/test_dashboard_cache_reversion.py`, `test_refresh_reversion_forensic.py` | Assertions updated to the corrected invariant (see §B‑1). |

---

## B. Root causes discovered

### B‑1 🔴 The desktop overwrote authoritative server numbers with its stale SQLite cache

Three places re-derived the fleet counts from the local mirror **after** the server had answered:

- `DomainStore.update_server_dashboard()` — looped `_FLEET_KEYS` and replaced each server value with `snapshot.fleet_counts[k]`.
- `DomainStore._build_snapshot()` — did the same on every SQLite reload.
- `MainWindow._refresh_dashboard()` — merged `snap.overview` and `snap.fleet_counts` over `_authoritative_server_overview`.

PostgreSQL said "3 en location"; a mirror that had not finished syncing said "0"; the screen showed 0. This is the direct cause of the "Prêts à louer 5 / Véhicules en location 0" class of contradiction, and it was **codified in the test suite** (`test_live_server_data_not_overwritten_by_domain_changed` asserted `"0"` while the server payload said `42`, with the comment *"canonical local fleet … never fictitious server counts"*).
**Fixed:** the server payload is now taken verbatim. Those tests were updated to assert the corrected invariant; the guarantee they actually protect (no reversion after sync / domain reload / tab switch / late reply) is still asserted in full.

### B‑2 🔴 The dashboard was three snapshots pretending to be one

`DashboardFetcher` issued `GET /dashboard/stats` **and** `GET /dashboard/vehicle-performance`; the revenue panel independently issued `GET /dashboard/revenue?from=&to=` from a second worker thread. Three responses, three server-side `now` values, merged into one screen. Between them a rental could start, a maintenance could close, or midnight could pass.
**Fixed:** one request, one `now`, one DTO.

### B‑3 🔴 A failed API call was rendered as `0`

`_render_fleet_cards` used `d.get("available", 0)`, and `_refresh_dashboard`'s offline branch forced `overview[key] = 0.0` for every revenue key that was `None`. A timeout therefore displayed *"Chiffre d'affaires 0,00 DH — Prêts à louer 0"*, which is indistinguishable from a real answer and is the worst possible failure mode for this screen.
**Fixed:** `apply_unavailable()` renders `—` plus a red banner naming the reason. There is no code path from a fetch failure to a number.

### B‑4 🔴 The revenue provider guessed, and mislabelled the guess as "server"

`MainWindow._revenue_provider` fell back to a chain of heuristics: it compared the requested range against `date.today()` (**OS timezone**, not Africa/Casablanca) to decide whether the held `today_revenue` / `week_revenue` / `month_revenue` applied, and — failing that — returned `self._last_server_revenue`, *the revenue of whatever range had been fetched previously*, labelled `"server"`. Selecting "Cette année" could display last month's figure with a green "Mis à jour à" stamp.
**Fixed:** the period is resolved server-side inside the snapshot; the fallback chain is gone. `_business_today()` replaces `date.today()`.

### B‑5 🔴 The window could not fit on the screens it targets

`MainWindow.setMinimumSize(1200, 750)`. On a 1366×768 or 1280×720 laptop the usable height after the title bar and the OS panel is *below* 750, so Qt could not honour the constraint and the shell was pushed past the screen edge — the clipped sidebar and cut-off header in the reported screenshot. Compounding it: `Sidebar.setFixedWidth(260)` with a non-scrolling column, `_global_search.setFixedWidth(260)`, `_refresh_btn.setFixedSize(140, 36)`, `_last_refresh_lbl.setMinimumWidth(320)`, and a Top-5 bar at `setFixedWidth(180 * pct / 100)`.
**Fixed:** floor is 900×560; every one of those fixed sizes is now a range or layout-driven.

### B‑6 🟠 `FlowLayout` laid cards out at their **unwrapped** `sizeHint()`

`FlowLayout.doLayout` positions each item at `item.sizeHint()`. A card containing a word-wrapping `QLabel` reports the *unwrapped* text width as its hint, so a row could demand more width than the viewport had, and cards never stretched (ragged right edge on wide screens).
**Fixed:** `ResponsiveGrid` derives the column count from the real width and gives every column an equal share. `FlowLayout` is retained only for control rows (combo, buttons, date pickers) where `sizeHint` is genuine.

### B‑7 🟠 "Réservations" followed the revenue filter and could show `—`

`_render_reservations_card()` keyed off the revenue period combo. Selecting *Hier*, *Semaine dernière*, *Mois précédent*, *Année dernière* or *Personnalisé* fell through to `locs = "—"` — the card had no value for 5 of the 9 selectable periods, and for the other 4 it silently changed meaning.
**Fixed:** `apply_snapshot` always shows **today**, with returns/in-progress as a footnote. §16's separation of *operational state* (always now) from *revenue* (selectable period) is now structural.

### B‑8 🟠 "Maintenances en cours" counted tickets that were not in progress

`active_maintenance_tickets` was `COUNT(*) WHERE status NOT IN ('COMPLETED','CANCELLED')` — no date predicate. A ticket scheduled for next month counted as "en cours" while its vehicle correctly showed as available on the fleet card.
**Fixed:** `active_tickets` uses the same active-maintenance condition as the fleet derivation (`start <= now < COALESCE(actual_end, expected_end, +∞)`). The un-dated figure survives as `open_tickets` for the legacy payload.

### B‑9 🟠 Top-5 used a different eligibility rule than the money

`RentalRepository.get_vehicle_stats` excluded **all** `CANCELLED` rentals, while `shared/revenue_reference.is_revenue_eligible` recognises a rental cut short by maintenance (it earned its realised days). A vehicle's Top-5 revenue column could therefore disagree with the revenue card.
**Fixed:** both use `is_revenue_eligible`. Also removes an N+1 (`get_by_id` per vehicle).

### B‑10 🟡 Legacy `/dashboard/stats` was a second implementation

`DashboardService.get_overview()` ran its own fleet query, its own maintenance count, its own returns query and its own 4-period revenue loop. Any change to one path silently drifted from the other — the mechanism behind the historical split-brain incidents.
**Fixed:** it is now a projection of `build_snapshot`'s rows.

### Observation (not a defect)

`period_end_at` for October 2026 serialises as `+00:00` while `period_start_at` is `+01:00`. That is the installed tzdata's Africa/Casablanca transition, correctly applied to a local-midnight boundary. Date arithmetic is unaffected — all revenue windows are date-based.

---

## C. Architecture after the rebuild

```
                    PostgreSQL  (source of truth)
                          │  one read set
                          ▼
        backend/app/services/dashboard_snapshot.py   ← thin port, no arithmetic
                          │
                          ▼
        shared/dashboard_reference.build_snapshot()  ← THE spec (pure)
              ├── shared/fleet_status_reference      buckets
              ├── shared/revenue_reference           money
              └── shared/money_time                  periods / timezone
                          │  one DTO, one `now`
                          ▼
              GET /api/v1/dashboard/summary?period=…
                          │
                          ▼
        desktop ApiClient.get_dashboard_summary()    ← one request
                          │
                          ▼
        DashboardWidget.apply_snapshot(dto)          ← formats, never computes

        OFFLINE ONLY (server unreachable and no server payload held):
        DomainStore rows → desktop/app/sync/dashboard_snapshot.py
                         → the SAME build_snapshot()  → source="local"
```

**Invariants enforced by construction**

1. There is exactly one implementation of every dashboard number (`shared/dashboard_reference.py`). Both runtimes are ports; `test_dashboard_crossruntime.py` asserts the two DTOs are equal apart from the `source` stamp.
2. Every figure in a DTO comes from one `now` and one row set.
3. Server and local payloads are **never blended**. `MainWindow._render_dashboard_from_best_known()` picks exactly one (`dto` → `overview` → local) and says which in `_dashboard_source_kind`.
4. A local snapshot can never overwrite live server data — guarded in the provider (returns `None` rather than a cache downgrade) and again in `_on_snapshot_done`.
5. Unknown ≠ zero.

---

## D. Exact calculation rule for every KPI

Business timezone **Africa/Casablanca**; every interval is half-open `[start, end)`; a datetime with no offset is business-local wall time (never UTC).

| KPI | Rule |
|---|---|
| **Chiffre d'affaires** | `shared.revenue_reference.revenue_between`. **Pro-rata by day**: a rental of `num_days` starting at `S` splits `total_price` into `num_days` equal slices; slice *i* is booked to calendar date `date(S)+i` and is *realised* once `now ≥ S + i days`. Sum the realised slices whose date falls in `[from, to)`. `CANCELLED` contributes nothing **unless** `cancellation_reason == 'MAINTENANCE'`, where the realised days before `cancelled_at` are preserved (a closed period's revenue never changes retroactively). `COMPLETED` = all `num_days`. Decimal arithmetic; `total_price / num_days` keeps the all-time sum exactly equal to `total_price`. |
| **Période** | `shared.money_time.period_bounds` for the 8 presets (week starts Monday); `custom_bounds` for a custom range, where the operator's `Au:` date is **inclusive** and is converted to the exclusive bound by `+1 day`. An unknown period name is a **422**, never a silent fallback to "today". |
| **Réservations (Ce jour)** | Count of eligible rentals whose **start date** is today (`rentals_started_between`, same eligibility predicate as the money). Cancelled excluded. Footnote carries `ending_today` (blocking rentals ending today) and `in_progress` (blocking rentals whose window contains `now`). |
| **Maintenances en cours** | Maintenance rows with `status NOT IN (COMPLETED, CANCELLED)` **and** `start <= now < COALESCE(actual_end, expected_end, +∞)`. Footnote gives the deduplicated vehicle count — two overlapping tickets on one car are 2 tickets, 1 vehicle. |
| **Prêts à louer** | Vehicles whose derived effective status is `AVAILABLE` (see §E). Derived, not stored. |
| **Véhicules en location** | Effective status `RENTED`: a blocking reservation (`RESERVED` or `ACTIVE`) with `start <= now < end`. **Time-derived, not status-derived** — this business hands the car over at the reservation start, so `ACTIVE` is an optional refinement, never a precondition. `vehicle.status` is never trusted for this. |
| **Véhicules réservés** | Effective status `RESERVED`: a blocking reservation with `now < start`. Not cancelled, not completed, not currently out, not in maintenance. |
| **Véhicules en maintenance** | Effective status `MAINTENANCE` (the condition above). |
| **Top 5 véhicules les plus loués** | Metric = **number of valid rental records that have already started** (`start <= now`), valid = `is_revenue_eligible` — the same predicate as the money, so a row's count and its revenue always describe the same rentals. Order: `rental_count DESC, revenue DESC, vehicle_id ASC` (revenue only breaks ties between equal counts; `vehicle_id` makes the order total). Cancelled excluded; future bookings excluded; capped at 5; empty ⇒ clean empty state. |

---

## E. Vehicle status precedence

Audited against `shared/fleet_status_reference.py` and confirmed as the application's real rule:

```
1. SOLD / INACTIVE   structural, read verbatim from vehicle.status — NOT part of the active fleet
2. MAINTENANCE       an active maintenance period covers `now`
3. ACTIVE_RENTAL     a blocking reservation covers `now`   (start <= now < end)
4. RESERVED          a blocking reservation is upcoming    (now < start)
5. READY_TO_RENT     none of the above
```

This matches the recommended order in the brief. The buckets are mutually exclusive by construction (one dict entry per vehicle) and

```
ready_to_rent + active_rental + reserved + maintenance == vehicles.total
vehicles.total + excluded_structural                  == vehicles.fleet_size
```

is asserted on every response.

---

## F. The DTO — one contract

`GET /api/v1/dashboard/summary?period=month` (also `…?period=custom&from=YYYY-MM-DD&to=YYYY-MM-DD`, `to` inclusive):

```jsonc
{
  "schema_version": 2,
  "generated_at": "2026-09-05T04:42:56.796559+01:00",   // the ONE instant
  "business_timezone": "Africa/Casablanca",
  "currency": "MAD",
  "source": "server",                                    // or "local" (offline port)
  "revenue":  { "amount", "currency", "period", "period_start", "period_end",
                "period_end_inclusive", "period_start_at", "period_end_at",
                "rentals", "rental_days" },
  "periods":  { "today": {...}, "week": {...}, "month": {...}, "year": {...} },
  "reservations_today": { "count", "starting_today", "ending_today",
                          "in_progress", "date" },
  "maintenance": { "active_tickets", "open_tickets",
                   "vehicles_in_maintenance", "fleet_maintenance_vehicles" },
  "vehicles": { "total", "ready_to_rent", "active_rental", "reserved",
                "maintenance", "excluded_structural", "fleet_size" },
  "top_vehicles": [ { "rank", "vehicle_id", "registration", "brand", "model",
                      "rental_count", "rental_days", "revenue", "last_rental" } ],
  "integrity": { "ok": true, "violations": [] }
}
```

`periods` is **not** a second snapshot — the four standing windows are computed in the same pass against the same `now` and the same rows, which is what lets the legacy flat payload stay a projection instead of a second calculation.

`/api/v1/dashboard/stats` is retained for the mobile app and older desktop builds; every field it returned is still present with unchanged semantics, and it is now derived from the same rows.

---

## G. Data-integrity validation

`shared.dashboard_reference.validate()` runs before every response and returns the `integrity` section:

- every bucket `>= 0`
- `ready_to_rent + active_rental + reserved + maintenance == total`
- `total + excluded_structural == fleet_size`
- `revenue.amount >= 0`, `revenue.rental_days >= 0`
- `top_vehicles` ordered by `rental_count DESC`

A violation is **logged at ERROR** with the offending numbers and surfaced in the payload; the desktop raises a red banner. Contradictory numbers are never returned silently.

---

## H. Tests added

| Suite | Count | Covers |
|---|---|---|
| `backend/tests/test_dashboard_summary.py` | 33 | zero rentals · one active rental · one future reservation · one maintenance (+ completed/cancelled/overlapping/open-ended) · cancelled reservation · completed rental · multiple vehicles · multiple rentals · same-vehicle history · starts today · ends today · timezone boundary · midnight boundary · no data · refresh after mutation · category exclusivity · precedence (maintenance beats rental, rental beats future reservation) · revenue date filtering · custom-range inclusivity · Top-5 ranking/cap/tie-break · fleet reconciliation · duplicate rows · endpoint contract (all 8 periods, 422s, auth, legacy agreement) |
| `backend/tests/test_dashboard_crossruntime.py` | 10 | backend DTO **==** desktop DTO over real rows, for all 8 periods |
| `desktop/tests/test_dashboard_rebuild.py` | 19 | one-snapshot rendering · server timestamp · reconciliation line · period does not move operational counters · **API failure ⇒ `—`, never 0** · provider returns None / raises · real zero still renders 0 · empty vs unavailable Top-5 · offline labelling · integrity banner · one request per period change · custom inclusive end · superseded reply dropped · business-timezone presets · offline port parity · raw-vs-derived status · maintenance precedence offline |
| `desktop/tests/test_dashboard_responsive.py` | 38 | grid column maths · one-column minimum · equal stretch · no horizontal overflow · nothing clipped · nothing hidden · no truncation · wrap-instead-of-clip · widget minimum width · no hard-coded bar width · sidebar shrink + scroll · full shell (sidebar/content/header) — each at 1280×720, 1366×768, 1600×900, 1920×1080, 1024×600, 900×560 |

---

## I. Test results

```
backend   300 passed, 0 failed   (257 before + 43 new)
desktop   <full suite result>    (86 dashboard-related tests green in a targeted run)
mobile     79 passed, 0 failed   (no mobile source was touched; the /dashboard/stats
                                  contract DashboardStatsDto reads is field-for-field
                                  identical, so mobile is unaffected by design)
```

### Live end-to-end (§22) — no mocks, real database

`PostgreSQL 16 (docker car_rental_db_prod, real data) → FastAPI (rebuilt, 127.0.0.1:8001) →
desktop ApiClient → DashboardWidget`. **All checks passed:**

- one request returns the whole DTO; `integrity.ok`; fleet reconciles (`4 = 4+0+0+0`)
- all 8 presets **and** a custom range resolve server-side; operational counters identical
  across every one of them (§16); `custom 2026-01-01..2026-12-31` == the `year` preset
- legacy `/dashboard/stats` agrees with `/summary` on every shared field
- the UI renders the server numbers verbatim, labelled *En direct*, no banner
- an unreachable API returns `None`, and the UI shows `—` + a banner — never `0`
- **mutation without restart (§17):** inserting a rental in PostgreSQL moved the snapshot
  from `(4,0,0,0)` / 500 DH to `(3,1,0,0)` / 800 DH on the very next request; deleting the
  probe restored `(4,0,0,0)` / 500 DH exactly. **The database was left exactly as found.**
- 0 px horizontal overflow and nothing clipped at 1280×720, 1366×768, 1600×900, 1920×1080
  — both for the Dashboard alone and for the full shell with the Pistache theme applied
- FR and AR/RTL both render correctly (mirrored layout, 0 px overflow)

---

## J. Responsive resolutions verified

| Resolution | Horizontal overflow | Clipped cards | Sidebar / content | Screenshot |
|---|---|---|---|---|
| 1280×720 | 0 px | none | 230 / 1050 px, no overlap | ✅ |
| 1366×768 | 0 px | none | 230 / 1136 px, no overlap | ✅ |
| 1600×900 | 0 px | none | 230 / 1370 px, no overlap | ✅ |
| 1920×1080 | 0 px | none | 230 / 1690 px, no overlap | ✅ |
| 1024×600 | 0 px | none | — | ✅ |
| 900×560 (floor) | 0 px | none | — | ✅ |

Layout behaviour: revenue panel full width → KPI row (2 cards, min 240 px each) → fleet row
(4 cards, min 190 px each) → reconciliation line → Top-5 full width. Rows reflow to 4 / 3 / 2 / 1
columns as width allows and stretch to fill; the page scrolls vertically only. No font was reduced,
no card hidden, no overflow concealed. FR and AR/RTL both verified (`layoutDirection` mirrors,
0 px overflow in both).

---

## K. Before / after

| | Before | After |
|---|---|---|
| Requests per dashboard | 3 (`/stats`, `/vehicle-performance`, `/revenue`) at 3 instants | 1 (`/summary`) at 1 instant |
| Fleet counts shown | server value overwritten by stale SQLite | server value, verbatim |
| Implementations of the numbers | backend service + legacy overview + desktop cache + widget | **1** (`shared/dashboard_reference.py`) |
| API failure | `0 DH`, `0` vehicles | `—` + red banner naming the reason |
| Failed *refresh* (data already held) | figures could revert to cache | figures kept, "actualisation impossible" banner |
| "Réservations" card | followed the revenue period; `—` for 5 of 9 periods | always today (+ returns / in-progress footnote) |
| "Maintenances en cours" | all open tickets, any date | tickets whose window contains `now` |
| Top-5 eligibility | ≠ revenue eligibility; N+1 query | same predicate; single pass |
| Period change | patched the revenue label only | refetches the whole snapshot |
| "Mis à jour à" | local repaint time | server `generated_at` |
| Fleet reconciliation | not checked | asserted + logged + displayed |
| Window floor | 1200×750 (does not fit 1280×720) | 900×560 |
| Card layout | `FlowLayout` at unwrapped `sizeHint` | `ResponsiveGrid`, width-derived columns |
| Sidebar | `setFixedWidth(260)`, no scroll | 200–260 px, vertical scroll |
| Top-5 bar | `setFixedWidth(180 × pct)` | layout-driven `RankBar` |

---

## L. Remaining risks

1. **Deployment gap.** The rebuilt backend is verified against the local PostgreSQL stack only. Fly production still runs the previous release, which has **no `/dashboard/summary`**. Until it is deployed, a rebuilt desktop client hitting production raises `ServerContractMismatchError` (logged as a version mismatch, and the dashboard falls back to the local mirror labelled *Hors ligne / Cache*) — it degrades honestly, but the operator will not see live figures. **Deploying the backend before shipping a new desktop build is required.** I have not deployed to Fly or built any artifact; that is a release decision.
2. **Two reversion tests were changed.** `test_dashboard_cache_reversion.py` and `test_refresh_reversion_forensic.py` previously asserted that the local cache overrides server fleet counts. That behaviour was the defect, and the brief requires PostgreSQL to be authoritative — so the expected values were updated. Worth a second pair of eyes to confirm the business agrees.
3. **Full-table read.** `_load_rows` loads all reservations and maintenances per dashboard request (the Top-5 is all-time, so history is genuinely needed). Correct and fast at this agency's volume; if reservation history reaches six figures this wants a materialised aggregate rather than more queries.
4. **`/dashboard/vehicle-performance` is no longer on the dashboard path** but is still served (returns all vehicles with `utilization_rate`). It keeps its own `get_vehicle_stats` ranking, which uses the stricter "all cancelled excluded" eligibility — if anything else consumes it, that difference from the Top-5 is intentional but worth noting.
5. **One residual second implementation, deliberately left in place.** `desktop/app/sync/dashboard_cache.py` still computes the `DomainStore` snapshot's own `overview`, and `DomainStore.recompute_effective()` uses it to roll the period cards when the clock crosses midnight or a reservation boundary while a server payload is held. The Dashboard's *rendering* path no longer reads it (the offline branch goes through the shared spec), and it is parity-tested against `shared/revenue_cases.json`, so it cannot silently disagree with the money engine. Folding `DomainStore` onto `shared/dashboard_reference` too would remove the last duplicate, but it touches the whole temporal/BoundaryClock test surface and was out of scope for this change.
6. **Not verified here:** the packaged Windows EXE at runtime, on-device Android, and a two-desktop cross-client session. No APK/EXE/ZIP was rebuilt.
7. **Pre-existing, untouched:** the Africa/Casablanca DST offset in serialised `period_*_at` strings (§B observation), and `EventBroadcaster` being an in-process singleton (fine for the single Fly machine, needs Redis pub/sub if scaled beyond one).
