# FINAL DASHBOARD / CHIFFRE D'AFFAIRES — FORENSIC DIAGNOSIS

**Scope:** read-only forensic investigation. No source changed, no commit, no build, no deploy.
**Date:** 2026-09-03
**Investigator role:** Forensic Software Architect / Business-Logic Auditor / Data-Integrity Investigator
**Live evidence:** captured from the running production system (`https://car-rental-system.fly.dev`) and the local repo working tree at `fcc2a5f` (branch `main`).

---

## 1. Executive Finding

**The Dashboard "Chiffre d'affaires" is wrong because two different, mutually
incompatible revenue business rules are live in production at the same time.**

* The **deployed backend** (Fly release v24, branch `fix/dashboard-live-sync-forensic`)
  computes revenue as **recognition-at-start**:
  `revenue(period) = Σ total_price of every non-cancelled reservation whose
  start_datetime falls inside the period` — the *entire* rental price is booked
  the instant the rental starts.
* The **shipped desktop and mobile clients** (artifacts `…_20f29fb`, built from
  `main` which contains the `7aec46e` "one pro-rata revenue engine" merge)
  compute revenue as **pro-rata by day**: each rental's `total_price` is spread
  over its `num_days`, and a day only counts once it has elapsed.

These two rules do not merely round differently — they disagree by **4–50×** on
real production data and even disagree on the **sign** of the month-over-month
change. Because the desktop revenue panel silently falls back to the client-side
pro-rata engine whenever the backend endpoint it wants (`/dashboard/revenue`) is
absent — which it always is on the deployed backend (HTTP 404) — the operator is
shown the pro-rata number while every server-side artifact (the backend's own
`/dashboard/stats`, any report, the database) shows the recognition-at-start
number.

"Actualiser" is **not** the cause. Refresh faithfully re-renders whichever of the
two engines the code path selects; it is only the moment at which the operator
notices the number is inconsistent with what they saw before the client was
updated, or with the server.

---

## 2. Exact Root Cause

A **revenue business-rule change was merged to `main` and shipped in the desktop
and mobile clients, but the corresponding backend was never deployed.** The
product now runs a *split brain*:

| Component | Source of truth | Revenue rule | Proof |
|---|---|---|---|
| Deployed backend `/dashboard/*` | branch `fix/dashboard-live-sync-forensic` (release v24) | **recognition-at-start** — `RentalRepository.get_revenue_between()` = `SUM(total_price) WHERE status != 'CANCELLED' AND start_datetime <= now AND period_start <= start_datetime < period_end` | live `/dashboard/yearly` = 95 650 DH = exact Σ of all non-cancelled `total_price`; live `/dashboard/monthly` = 900 DH = the 2 reservations that started in September; `days_rented` = 301 = exact Σ of `num_days` |
| Repo `main` backend (NOT deployed) | `shared/revenue_reference.py` + `backend/app/services/revenue_service.py` (merge `7aec46e`, feat `ca77fb0`) | **pro-rata by day** | `shared/revenue_reference.py` docstring line 17: "PRO-RATA BY DAY (chosen 2026-09-02, replaces recognition-at-start)"; `_realised_days()` caps at elapsed days |
| Shipped desktop client `…_20f29fb` | `desktop/app/sync/dashboard_cache.py::revenue_between_rows` (pro-rata port) | **pro-rata by day** | code; and live divergence below |
| Shipped mobile client `…_20f29fb.apk` | `mobile/.../data/fleet/RevenueEngine.kt` (pro-rata port) | **pro-rata by day** | code; `FleetRepository.performanceMetricsFlow` = `local ?: api` (local pro-rata preferred) |

The cross-runtime **parity tests are all green and are irrelevant to this bug**:
they assert *backend code == desktop code == mobile code == `shared/revenue_reference.py`*
on the fixtures in `shared/revenue_cases.json`. They do **not** assert
*shipped client == deployed backend*. All three code bases were migrated to
pro-rata together, so they agree with each other and with the spec — while the
server the clients actually talk to was left on the old rule.

---

## 3. First Point of Divergence

**Layer 3 (backend business logic) vs. Layer 8 (client dashboard aggregation),
for the identical reservation row.**

* **File / function that is authoritative in production:**
  `backend/app/repositories/rental_repository.py :: get_revenue_between()`
  (as deployed from branch `fix/dashboard-live-sync-forensic`, lines 222–245) —
  recognition-at-start.
* **File / function that the shipped desktop actually renders from:**
  `desktop/app/sync/dashboard_cache.py :: revenue_between_rows()` (lines 105–128)
  → `_reservation_revenue()` (lines 47–65) → `_realised_days()` (lines 42–44) —
  pro-rata.
* **The specific line that makes them diverge:**
  `desktop/app/sync/dashboard_cache.py:53` `realised = _realised_days(start_dt, num_days, now)`
  and `:63` `hi = min(sd + timedelta(days=realised), to_d)` — the realised-day cap.
  The deployed backend has **no such cap**; it adds the whole `total_price` as
  soon as `start_datetime <= now`.

There is **no single file to "fix"** — the divergence is a deployment/versioning
fact. The first *code* location where the two live implementations of the same
concept disagree is the realised-day cap listed above.

---

## 4. Evidence — One Reservation, End to End

**Reservation `833ab76f…` (real production row):**

```
status         = ACTIVE
start_datetime = 2026-08-31T08:00:00+00:00   (= 2026-08-31 09:00 Africa/Casablanca)
end_datetime   = 2027-03-04T09:00:00+00:00
num_days       = 185
daily_price    = 250.00
total_price    = 46250.00
```

Business instant of the investigation: `now_business()` = `2026-09-03T01:19+01:00`
(server UTC now = `2026-09-03T00:16Z`). Realised days = `floor((now − start)/1d) + 1`
= `floor(2.68) + 1` = **3** (calendar dates Aug 31, Sep 1, Sep 2).
Per-day rate = `46250 / 185` = **250.00**.

| Stage | File / function | Input | Transformation | Output (this reservation's contribution) | Matches deployed truth? |
|---|---|---|---|---|---|
| 1. PostgreSQL | `reservations` row | — | stored `TIMESTAMP(timezone=True)` | start 2026-08-31 08:00+00, total 46250.00 | authoritative |
| 2. Backend SQL (deployed) | `get_revenue_between()` (branch v24) | row | `SUM(total_price) WHERE start_datetime<=now AND start_datetime IN [p_start,p_end)` | **year: 46 250** · month (Sep): **0** · week: **46 250** | ✅ (this IS the deployed rule) |
| 3. Backend service (deployed) | `DashboardService.get_overview()` (branch v24) | step 2 | passthrough | `year_revenue` includes 46 250 | ✅ |
| 4. API DTO | `GET /api/v1/dashboard/stats` | step 3 | JSON | contributes to `year_revenue: 95650.0` (live-verified) | ✅ |
| 5. Sync payload | `sync_service.py:686` | row | `r.start_datetime.isoformat()`, `float(r.total_price)` | `"2026-08-31T08:00:00+00:00"`, `46250.0`, `num_days 185` | lossless |
| 6. Desktop SQLite | `LocalReservation` (`String(50)` / `Float`) | step 5 | store as strings/floats | same values | lossless |
| 7. DomainStore | `domain_store.py::_res_dict` (289–303) | step 6 | dict copy | same values | lossless |
| 8. Dashboard aggregation | `dashboard_cache.revenue_between_rows` (pro-rata) | step 7 rows, `now` | `per_day × realised-days-in-window` | **year: 750** · month (Sep): **500** · week: **750** | ❌ **FIRST DIVERGENCE** (750 vs 46 250) |
| 9. Displayed value (revenue panel) | `main_window._revenue_provider` → `dashboard.py::_on_revenue_done` | step 8 | `/dashboard/revenue` tried first → **HTTP 404** → local pro-rata used | operator sees this reservation as **750** of a **19 750 DH** year total, label "actualisé localement" | ❌ |

**Whole-dashboard divergence on the full live dataset (16 reservations, 10
non-cancelled), computed with the repo's own `shared/revenue_reference.py`
against the live rows and cross-checked against the live API:**

| Period (business-local) | Shipped client (pro-rata) | Deployed backend (recognition-at-start) | Δ |
|---|---:|---:|---:|
| today `[09-03 .. 09-04)` | 0 DH | 0 DH | 0 |
| week `[08-31 .. 09-07)` | **9 650 DH** | **47 150 DH** | −37 500 |
| month `[09-01 .. 10-01)` | **6 650 DH** | **900 DH** | **+5 750 (opposite sign)** |
| year `[01-01 .. 01-01)` | **19 750 DH** | **95 650 DH** | −75 900 |
| `days_rented` (year) | 51 | 301 | — |

The month row is the smoking gun: the client shows **6 650 DH** (August's long
rentals bleeding realised days into September), the backend shows **900 DH** (only
the two reservations that literally started in September). No refresh, cache, or
timezone effect can explain a number that is simultaneously 7× too high on one
card and 5× too low on another — only two different formulas can.

---

## 5. Revenue Logic Audit

### 5.1 What "Chiffre d'affaires" means in each live implementation

**Deployed backend — recognition-at-start** (`get_revenue_between`, branch v24):

```
revenue(from, to) = Σ  r.total_price
                    for r in reservations
                    where r.status != 'CANCELLED'
                      and r.start_datetime <= now
                      and from <= business_date(r.start_datetime) < to
```

* price source: `reservations.total_price` (`NUMERIC(12,2)`, set at creation as
  `round(daily_price * num_days, 2)`).
* duration: not used for revenue (only for the count/`days_rented`).
* proration: **none**. A 185-day rental booked today adds its full 46 250 DH to
  *today's* month/week/year the instant it starts.
* date semantics: half-open `[from, to)`, business-local (`Africa/Casablanca`)
  midnight bounds, `to` exclusive.
* status filter: `!= 'CANCELLED'` (RESERVED, ACTIVE, COMPLETED all count).
* cancellation: excluded entirely, retroactively.
* Decimal/float: `NUMERIC` summed in SQL, returned as `float()` — safe here.

**Shipped clients — pro-rata by day** (`shared/revenue_reference.py`,
`dashboard_cache.py`, `RevenueEngine.kt`):

```
per_day(r)      = r.total_price / r.num_days
realised_days(r)= clamp(floor((now - start)/1day) + 1, 0, r.num_days)
revenue(from,to)= Σ  per_day(r) * | { calendar dates of r's realised days } ∩ [from, to) |
```

* proration: `total_price` spread evenly across `num_days`; day *i* accrues only
  after `now >= start + i days`.
* summing one rental over all-time (once fully elapsed) == `total_price` exactly
  (division kept symbolic, `Decimal`, quantised only at the end).
* same date/status/cancellation semantics as above.

Both rules are internally coherent and individually defensible. **Neither is a
bug in isolation. The bug is that both are in production simultaneously.**

### 5.2 Semantic problems found regardless of which rule wins

1. **`num_days` is a ceiling of hours/24, not calendar days**
   (`rental_service.calculate_days`: `max(1, ceil(total_hours/24))`).
   A rental `2026-08-27T08:00Z → 2026-09-04T08:00Z` is `num_days = 8` but touches
   **9** calendar dates. Under pro-rata the last partial calendar day is never
   billed (the realised-day set has only 8 entries); under recognition-at-start
   this is irrelevant. Not wrong, but the "day" the operator sees in the UI and
   the "day" used for money are different units.

2. **`daily_price` fallback path is dead in pro-rata** — `_realised_day_dates`
   uses `daily_price` only when `total_price is None`, which never happens for
   persisted rows (`NOT NULL`). Harmless but misleading.

3. **Client-timezone contamination at data entry** —
   `desktop/app/ui/reservations/reservation_list.py:371`
   `start.toPython().astimezone(timezone.utc).isoformat()` interprets the
   `QDateTimeEdit` wall-clock in the **desktop machine's OS timezone**, not the
   business timezone. On a PC not set to `Africa/Casablanca`, "01 Sep 00:00"
   typed by the operator is persisted as a different instant, shifting the
   business date of the rental and therefore its whole revenue period. This
   corrupts the input to *both* revenue rules equally, so it is not the cause of
   the client/server split, but it is a latent P2 data-integrity defect.

4. **Naive-datetime interpretation is inconsistent across the codebase**
   (see §9.1).

---

## 6. Dashboard KPI Audit

Live values from `GET /api/v1/dashboard/stats` (deployed), annotated with source
and correctness against the deployed rule:

| KPI (widget) | Live value | Backend source (deployed) | Client source (shipped) | Verdict |
|---|---:|---|---|---|
| `total_vehicles` | 3 | `compute_fleet_counts` | `utils/fleet_status.compute_fleet_counts` | consistent rule |
| `available` | 0 | fleet counts | local fleet counts | consistent rule |
| `rented` | 3 | time-derived (`start<=now<end`, RESERVED∪ACTIVE) | same | consistent rule |
| `reserved` | 0 | time-derived (`now<start`) | same | consistent rule |
| `maintenance` | 0 | time-derived | same | consistent rule |
| `active_rentals` | 1 | `rental_counts['ACTIVE']` (**stored status**) | not shown on desktop dashboard | ⚠️ different definition from `rented=3`; known/intentional |
| `today_returns` | 3 | `end_datetime ∈ [today)` , `!= CANCELLED` | n/a | ok (3 reservations end 2026-09-03) |
| **`today_revenue`** | 0.0 | recognition-at-start | pro-rata | agree only because value is 0 |
| **`week_revenue`** | **47 150** | recognition-at-start | pro-rata → **9 650** | ❌ **P0** |
| **`month_revenue`** | **900** | recognition-at-start | pro-rata → **6 650** | ❌ **P0** |
| **`year_revenue`** | **95 650** | recognition-at-start | pro-rata → **19 750** | ❌ **P0** |
| `week/month/year_rentals` (count) | 3 / 2 / 10 | `count … start_datetime ∈ period` | `_rentals_started` (identical rule) | ✅ counts agree |
| Top-5 «les plus loués» | by `total_revenue` desc | `get_vehicle_stats` (all started, `!= CANCELLED`, full `total_price`) | `compute_top_vehicles_rows` (**also full `total_price`, not pro-rata**) | ✅ agree — Top-5 uses all-time full price on both sides |

Note the Top-5 panel deliberately sums **full `total_price`** on both runtimes, so
it is *not* affected by the pro-rata split — another proof that the split is
localised to the period-revenue engine only.

The desktop dashboard widget (`desktop/app/ui/dashboard.py`) renders revenue **only**
in `_revenue_value_lbl` (the panel). The `today/week/month/year_revenue` keys
carried in the `overview` dict are no longer displayed on any card, so the sole
revenue number the operator sees on the desktop is the pro-rata panel value.

---

## 7. Refresh ("Actualiser") Analysis

**Refresh is a symptom surface, not the cause.** Trace of the topbar button
(`desktop/app/ui/main_window.py`):

```
_on_refresh_clicked ─▶ _run_sync (SyncThread: /sync/pull → apply_pulled_items → SQLite)
                     └▶ _on_sync_finished ─▶ get_event_bus().data_refreshed.emit()   [unconditional, RC-02 fix]
                          └▶ _on_global_data_refreshed ─▶ DomainStore.reload()
                               └▶ _on_domain_changed ─▶ _refresh_dashboard()          [fetch_server defaults False]
                                    ├▶ overview  ← DomainStore.snapshot.overview       (LOCAL pro-rata)
                                    └▶ dashboard.refresh_data(request_revenue=False)   (panel keeps last value)
```

Findings:

1. **`_refresh_dashboard(fetch_server=True)` is never called anywhere in the code
   base** (verified by grep). `DashboardFetcher` (which hits `/dashboard/stats`)
   is **dead code**. Consequence: after the `20f29fb` change set, the desktop
   dashboard is now **100 % committed to the un-deployed pro-rata rule** and no
   longer ever displays the backend's own `/dashboard/stats` numbers. The
   "RC-01" remediation ("dashboard renders purely from DomainStore") *locked in*
   the divergence.

2. The revenue panel value comes from `_revenue_provider`
   (`main_window.py:559`): it calls `api_client.get_revenue_range()` →
   `GET /api/v1/dashboard/revenue?from=…&to=…` → **404 on the deployed backend**
   (route does not exist; verified against live `/openapi.json`) →
   `get_revenue_range` returns `None` → silent fallback to
   `dashboard_cache.revenue_between_rows` (pro-rata). The operator has no signal
   that the server was not consulted, only a subtle "actualisé localement" label.

3. Genuine refresh-mechanics defects **do** exist and *were* correctly fixed in
   `20f29fb` (flicker to "…", `None`→stale, dropped clicks, conditional fan-out,
   audit-log gaps). They make the wrong number *stable and non-flickering* — they
   do not make it *correct*.

**Causal classification (the checklist from the brief):**

```
[ ] Refresh lifecycle              — NOT causal (mechanics already hardened)
[ ] Synchronization                — NOT causal (payload is lossless & correct)
[ ] SQLite cache                   — NOT causal (stores exactly what the API sent)
[ ] DomainStore                    — NOT causal (faithful dict copy)
[x] Dashboard aggregation          — CARRIES the wrong rule (pro-rata) …
[x] Revenue calculation            — … which is the CORE issue: two rules live at once
[ ] Date/time handling             — secondary latent bug only (§9.1)
[x] SQL query                      — deployed get_revenue_between is the *other* rule
[x] API DTO / endpoint contract    — /dashboard/revenue & /dashboard/period MISSING on deployed
[x] Backend business rule          — deployed rule ≠ shipped-client rule  ← ROOT
[ ] UI rendering                   — NOT causal
[x] Multiple competing sources     — deployed backend vs shipped client engine
[ ] Other
```

---

## 8. Cross-Runtime Differences

| Concern | Deployed backend | Shipped desktop | Shipped mobile |
|---|---|---|---|
| Revenue rule | recognition-at-start | **pro-rata** | **pro-rata** |
| Revenue source at runtime | authoritative | `/dashboard/revenue` (404) → local pro-rata always | `local ?: api` → local pro-rata once cache warm; server (recognition) while cache cold |
| `/dashboard/stats` consumed? | — | **no** (`DashboardFetcher` dead) | yes, but only as fallback |
| Period bounds | `shared/money_time.period_bounds`, Casablanca, Mon-start | Python port (`_named_period_date_bounds`) — identical | Kotlin port (`RevenueEngine.namedPeriodBounds`) — identical |
| Rental count per period | `start_datetime ∈ period`, `!= CANCELLED` | identical | identical |
| Naive datetime → | `to_business`: naive = **business-local** | `parse_datetime_utc`: naive = **UTC** | `startMillis` from parsed ISO (aware in practice) |
| Effective fleet status | time-derived, shared spec | shared spec port | shared spec port |

**Consistent across runtimes:** fleet status, period boundaries, rental counts,
Top-5 (full-price), cancellation handling.
**Divergent:** the period revenue rule (backend alone vs the two clients), and —
on mobile only — a **cache-warmth flip** between recognition-at-start (cold, from
`/dashboard/stats`) and pro-rata (warm, from `FleetStatus.dashboardOverview`),
which presents as "the revenue changed after the app finished loading / after I
pulled to refresh".

---

## 9. Hidden / Secondary Root Causes

### 9.1 Inconsistent naive-datetime interpretation (P2, latent)

* `shared/money_time.to_business()` and `shared/revenue_reference._as_datetime()`:
  a naive datetime is **business-local** (`Africa/Casablanca`).
* `desktop/app/utils/datetime_utils.parse_datetime_utc()` (used by
  `dashboard_cache._parse_dt`, `utils/fleet_status`): a naive datetime is **UTC**.

Today this is dormant because the sync payload serialises
`r.start_datetime.isoformat()` from a `TIMESTAMP(timezone=True)` column, i.e. an
**aware** string (`…+00:00`), which both parsers handle identically. It becomes
active for: (a) any legacy/naive row that lost its offset on a SQLite round-trip;
(b) `LocalReservation` rows written by the optimistic local-create path before the
server round-trip. In those cases the desktop offline revenue would shift a
rental's realised-day count and possibly its business date by up to one Casablanca
offset (currently +1 h), moving revenue across a day/period boundary.

### 9.2 `api_client.get_revenue_range()` masks a version mismatch as "offline" (P1)

A `404` (route absent → client newer than server) is indistinguishable, to
`_revenue_provider`, from a network failure. The client should detect "this
server does not implement the revenue contract I was built against" and surface a
loud diagnostic instead of silently computing a different rule.

### 9.3 `DashboardFetcher` dead code (P3)

`desktop/app/ui/main_window.py:48-90` plus the `fetch_server` branch at
`514-557` are unreachable. Either delete, or re-wire so the desktop shows the
server's authoritative numbers once the rule is unified.

### 9.4 Prior forensic fixes addressed the wrong layer (audit of `6ba055c`, `fcc2a5f`, `20f29fb`)

* **`20f29fb`** ("resolve refresh data corruption and cross-screen inconsistency",
  RC-01…RC-10): genuinely fixed **refresh mechanics** — revenue-card flicker
  (RC-04), `None`/stale revenue (RC-05), dropped refresh clicks (RC-03),
  conditional fan-out (RC-02), and three backend audit-log propagation gaps
  (RC-06/07/08). **None of these detected or addressed the client/server revenue
  rule split.** RC-01 ("dashboard renders purely from DomainStore snapshot")
  actively removed the last code path that could have shown the operator the
  backend's own number, converting an *intermittent* divergence into a
  *permanent* one. The report `FINAL_REFRESH_DATA_INTEGRITY_FORENSIC_REPORT.md`
  claims "PostgreSQL = FastAPI = SQLite = DomainStore = Dashboard = Mobile"; this
  is **false in production** — the equality was verified between code bases, not
  against the deployed backend.
* **`fcc2a5f`**: documentation only.
* **`6ba055c`**: sync/auth/WebSocket hardening (`customer_id` in DTOs, maintenance
  delete audit log, cleartext-traffic disable, FIFO WS queue). Unrelated to
  revenue; no regression introduced here.

The surviving defect is therefore explained: **the wrong layer was fixed
repeatedly.** Every past investigation stopped at "the desktop offline number and
the desktop panel number now agree" without checking either against the running
server.

---

## 10. Exact Recommended Changes

> Implementation is deliberately **not** performed. The following is the plan for
> the separate implementation phase. **Step 0 is a business decision and blocks
> everything else.**

### CHANGE 0 — Pick ONE revenue rule (business owner sign-off required)

* **Option A — recognition-at-start** (what the deployed backend and every
  historical operator screen already show; simplest; "CA du mois = ce qu'on a
  signé ce mois" — the common SME mental model).
* **Option B — pro-rata by day** (accrual accounting; what `main` and the shipped
  clients already implement; "CA = prestation effectivement consommée").

Whichever is chosen, **all four implementations and the deployment must match**.
Do not ship clients from a commit whose backend is not simultaneously deployed.

### CHANGE 1 — If Option A (recognition-at-start) is chosen

| | |
|---|---|
| **FILE** | `shared/revenue_reference.py` |
| **FUNCTION** | `reservation_period_revenue`, `_realised_day_dates`, `revenue_between` |
| **CURRENT LOGIC** | pro-rata: `per_day × realised-days-in-window` |
| **PROBLEM** | disagrees with the deployed & historically-shown rule |
| **RECOMMENDED LOGIC** | revert to: a reservation contributes its full `total_price` to the single period containing `business_date(start_datetime)` iff `start_datetime <= now` and `!= CANCELLED`; 0 otherwise |
| **WHY** | restores a single rule; matches production; matches operator expectation |
| **RISK** | `shared/revenue_cases.json` must be regenerated; `44b4a2a` desktop "8-preset revenue widget" and `/dashboard/revenue` range endpoint stay, they just call the start-anchored engine |

Mirror the same revert in `backend/app/services/revenue_service.py`,
`desktop/app/sync/dashboard_cache.py` (`revenue_between_rows`,
`compute_overview_rows`), `mobile/.../data/fleet/RevenueEngine.kt`. Then
**deploy `main`** (so `/dashboard/stats` and the new routes are served) **and**
rebuild both clients from that same SHA.

### CHANGE 1′ — If Option B (pro-rata) is chosen

| | |
|---|---|
| **FILE** | deployment, not code |
| **CURRENT STATE** | backend running branch `fix/dashboard-live-sync-forensic` (recognition-at-start), missing `/dashboard/revenue` and `/dashboard/period/{name}` |
| **PROBLEM** | clients already pro-rata; server is not |
| **RECOMMENDED ACTION** | deploy `main` (`fcc2a5f` or later) to Fly; run `alembic upgrade head`; verify `/dashboard/revenue` returns 200 |
| **WHY** | makes the server match the already-shipped clients |
| **RISK** | **HIGH — communicate first.** On the current data the headline yearly CA drops **95 650 → 19 750 DH** overnight with no business change. Stakeholders must be told this is a definition change, not a loss. Historical dashboards/screenshots will not reconcile. |

### CHANGE 2 — Fail loudly on endpoint/contract mismatch

| | |
|---|---|
| **FILE** | `desktop/app/services/api_client.py` |
| **FUNCTION** | `get_revenue_range`, `get_period_revenue` |
| **CURRENT LOGIC** | `return r.json() if r and r.status_code == 200 else None` — 404 == None == "offline" |
| **PROBLEM** | a client newer than the server silently computes a different rule |
| **RECOMMENDED LOGIC** | distinguish `404`/`405` (contract mismatch) from transport failure; propagate a typed `ServerContractMismatch` to `_revenue_provider`, which then shows an explicit banner ("Le serveur n'est pas à jour — chiffres calculés localement, peuvent différer") instead of a silent "local" label |
| **WHY** | turns a silent data-integrity failure into a visible operational alert |
| **RISK** | low; UI-string + control-flow only |

### CHANGE 3 — Re-wire or remove `DashboardFetcher`

| | |
|---|---|
| **FILE** | `desktop/app/ui/main_window.py` |
| **FUNCTION** | `DashboardFetcher`, `_refresh_dashboard(fetch_server=…)` |
| **CURRENT LOGIC** | `fetch_server=True` never passed → dead code |
| **PROBLEM** | dead code; and the desktop never cross-checks the server |
| **RECOMMENDED LOGIC** | after CHANGE 0/1, either delete, or call `_refresh_dashboard(fetch_server=True)` on manual refresh and assert `abs(server_overview[k] - local_overview[k]) < 0.01` for each revenue key, logging a divergence at ERROR |
| **WHY** | a permanent runtime guard against this class of split ever recurring |
| **RISK** | low |

### CHANGE 4 — Unify naive-datetime semantics

| | |
|---|---|
| **FILE** | `desktop/app/utils/datetime_utils.py` |
| **FUNCTION** | `parse_datetime_utc` |
| **CURRENT LOGIC** | naive → UTC |
| **PROBLEM** | contradicts `shared/money_time.to_business` (naive → business-local) used by the canonical spec |
| **RECOMMENDED LOGIC** | make the revenue/fleet code paths use one helper that treats naive as business-local (matching `shared`), **or** guarantee every persisted datetime string is aware end-to-end and assert it on write |
| **WHY** | removes the §9.1 latent boundary bug |
| **RISK** | medium — touches fleet-status derivation too; must re-run the 14 shared fleet-status vectors |

### CHANGE 5 — Business-timezone data entry

| | |
|---|---|
| **FILE** | `desktop/app/ui/reservations/reservation_list.py:371-372` |
| **FUNCTION** | reservation-create payload build |
| **CURRENT LOGIC** | `start.toPython().astimezone(timezone.utc)` — uses OS timezone |
| **PROBLEM** | operator's typed wall-clock is interpreted in the PC's timezone, not `Africa/Casablanca` |
| **RECOMMENDED LOGIC** | attach `ZoneInfo("Africa/Casablanca")` to the naive `QDateTimeEdit` value before converting |
| **WHY** | the rental's business date (hence its revenue period) must not depend on operator PC settings |
| **RISK** | low; affects new rentals only |

---

## 11. Regression Tests Required

1. **Deployed-contract test (new, CI gate before every release):**
   stand up the backend from the exact SHA being released, assert
   `GET /api/v1/dashboard/revenue?from=&to=` and `/dashboard/period/{name}`
   return `200`, and that `/dashboard/stats` keys match the client's expected
   schema. *Fails today* — the deployed backend 404s both routes.

2. **Single-dataset three-runtime equality test (new):**
   one fixture of ~12 reservations (include: fully-past, ongoing, future,
   month-spanning, cancelled, `num_days` != calendar days). Assert
   `backend revenue_between(...)` == `dashboard_cache.revenue_between_rows(...)`
   == `RevenueEngine.revenueBetween(...)` == **a hand-computed expected value for
   the chosen rule**, for today/week/month/year. Not "== the spec" — "== each
   other AND == the agreed number". *Would have caught this class immediately.*

3. **Production-golden test:** pin the current 16 live reservations; assert
   `year_revenue`, `month_revenue`, `week_revenue` equal the values the chosen
   rule prescribes (Option A: 95 650 / 900 / 47 150; Option B: 19 750 / 6 650 / 9 650).

4. **`revenue_cases.json` — add naive-datetime vectors:** at least two cases whose
   `start_datetime` has no offset, one at `23:30` local, asserting the business
   date and realised-day count. Covers §9.1.

5. **Desktop panel-vs-cards engine test:** assert the revenue shown in
   `DashboardWidget._revenue_value_lbl` for period *P* equals
   `compute_overview_rows(...)[f"{P}_revenue"]` (same engine, same number).

6. **`api_client` contract-mismatch test:** mock a `404` from `/dashboard/revenue`
   and assert `_revenue_provider` raises/flags `ServerContractMismatch` rather
   than returning `(local_value, "local")` silently.

7. **Client-timezone data-entry test:** with `TZ=Europe/Paris`, create a rental
   for "01/09/2026 00:00" via the desktop payload builder; assert the persisted
   `start_datetime` has business date `2026-09-01`.

---

## 12. Final Priority

| Priority | Finding | Action |
|---|---|---|
| **P0 — data/business correctness** | Deployed backend (recognition-at-start) and shipped desktop+mobile clients (pro-rata) compute different Chiffre d'affaires; on live data the year differs 95 650 vs 19 750 DH, the month differs in sign. Operator sees the client (pro-rata) number; every server artifact shows the other. | CHANGE 0 (decide rule) → CHANGE 1 or 1′ (align all four implementations + deploy the matching backend + rebuild clients from that SHA). Nothing else matters until this is done. |
| **P1 — synchronization / contract consistency** | `/dashboard/revenue` + `/dashboard/period/{name}` missing on deployed backend; `api_client.get_revenue_range` maps the resulting 404 to a silent local fallback; `DashboardFetcher` dead so desktop never cross-checks server; mobile flips rule on cache warmth. | CHANGE 2, CHANGE 3; ensure deploy includes the new routes. |
| **P2 — latent correctness** | Naive-datetime interpretation differs between `shared` (business-local) and `datetime_utils` (UTC); reservation-create uses OS timezone. Dormant with current all-aware data. | CHANGE 4, CHANGE 5. |
| **P3 — cleanup / process** | `DashboardFetcher` dead code; `FINAL_REFRESH_DATA_INTEGRITY_FORENSIC_REPORT.md` overstates "PostgreSQL = … = Mobile" (verified code-to-code, never against the deployed backend); parity suite gives false confidence because it never asserts shipped-client == deployed-server. | Remove dead code; add the deploy-gate test (#1) so "green parity" can never again mean "shipped == deployed" without it being true. |

---

### Answer to the success criterion

> *Which exact piece of logic causes the Dashboard / Chiffre d'affaires to be
> wrong, at which exact point does the first divergence occur, why, and what
> exact change permanently corrects it?*

**Which logic:** the period-revenue engine. The deployed backend runs
`RentalRepository.get_revenue_between()` = `SUM(total_price)` recognised in full
at `start_datetime` (branch `fix/dashboard-live-sync-forensic`, release v24). The
shipped desktop (`dashboard_cache.revenue_between_rows`) and mobile
(`RevenueEngine.revenueBetween`) run the pro-rata engine from
`shared/revenue_reference.py` (merged to `main` at `7aec46e`, never deployed).

**First divergence:** for any reservation, between backend Layer 3
(`get_revenue_between`, no realised-day cap) and client Layer 8
(`_reservation_revenue` → `_realised_days` cap at
`desktop/app/sync/dashboard_cache.py:53,63`). Concretely on live row
`833ab76f…`: backend books 46 250 DH into the year, client books 750 DH.

**Why:** a business-rule migration (recognition-at-start → pro-rata) was committed
and shipped in the clients, but the backend running it was never deployed, and
the endpoint the client uses to get the server's number (`/dashboard/revenue`)
does not exist on the deployed backend, so the client silently substitutes its
own, different rule.

**Exact permanent fix:** choose one rule (business decision), make
`shared/revenue_reference.py`, `backend/app/services/revenue_service.py` +
`repositories/rental_repository.py`, `desktop/app/sync/dashboard_cache.py`, and
`mobile/.../RevenueEngine.kt` all implement it, **deploy the backend and rebuild
both clients from the same commit**, and add the deploy-contract + three-runtime
golden-dataset regression tests (§11 #1–#3) to CI so a shipped-client-vs-deployed-server
rule split fails the build instead of reaching an operator.

---

*End of forensic diagnosis. No repository changes were made.*
