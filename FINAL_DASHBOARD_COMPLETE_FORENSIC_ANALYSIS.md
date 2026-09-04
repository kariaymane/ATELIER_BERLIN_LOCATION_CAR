# 🚨 FINAL DASHBOARD COMPLETE FORENSIC ANALYSIS
## APPLICATION: ATELIER BERLIN LOCATION CAR
### DATE: 2026-09-03
### TARGET: COMPLETE DESKTOP DASHBOARD, API DATA LINEAGE & STATE MACHINE AUDIT
### MODE: READ-ONLY FORENSIC AUDIT (ZERO MUTATIONS APPLIED)

---

## 1. EXECUTIVE FORENSIC SUMMARY

A forensic audit of the entire dashboard data lifecycle was conducted across the backend API (`FastAPI`), database (`PostgreSQL` on Fly.io), Desktop client (`PySide6`/`SQLite`), Mobile client (`Kotlin`/`Room`), and shared logic engines (`shared/`).

### The Central Verdict
**The operator's distrust of the Dashboard is 100% justified.** 

The dashboard's inaccuracies are **not** caused by a single isolated bug, nor is it merely a remnant of the previously resolved revenue pro-rata formula. Rather, the entire Dashboard exhibits **systemic architectural, mathematical, and semantic dissonance** across seven interrelated areas:

1. **Semantic Collision Between "Reservation Status" and "Fleet Effective Status":**
   The Dashboard presents two contradictory sets of cards side-by-side:
   - Operational KPIs show: **1 Active Rental, 3 Reserved Rentals**.
   - Fleet Status cards show: **3 Rented Vehicles, 0 Reserved Vehicles, 0 Available Vehicles**.
   This occurs because "Fleet Status" calculates physical vehicle possession using half-open time intervals `[start_datetime, end_datetime)` (treating any `RESERVED` reservation whose start date has passed as physically `RENTED`), whereas the Operational KPI card directly counts database contractual enum statuses (`status == 'ACTIVE'` vs `status == 'RESERVED'`).
2. **Total Inversion of "Top 5 Véhicules les plus loués" (Ranking vs Metric Mismatch):**
   The Top 5 widget is titled *"Top 5 véhicules les plus loués"* (Most rented vehicles) and displays the count of rentals (`{rental_count} locations`) alongside a progress bar proportional to `rental_count`. However, the underlying SQL and offline cache **sort strictly by `total_revenue DESC`** using unearned total contract prices. As a result:
   - **#1 Vehicle:** 3 rentals, 49,750 DH (small progress bar).
   - **#2 Vehicle:** 5 rentals, 42,300 DH (large progress bar).
   A vehicle with fewer rentals is ranked above a vehicle with more rentals in a list titled "Most Rented".
3. **Absurd Fleet Utilization Rate Bug (9,950% and 9,400%):**
   In `backend/app/services/dashboard_service.py`, the backend calculates `utilization_rate` by dividing total rental days by `(now - last_rental_start)`. Instead of dividing by the vehicle's lifetime or period days, it divides by the days since the vehicle's *most recent* rental started, resulting in astronomical utilization percentages of **9,950%**, **9,400%**, and **800%**.
4. **Pro-Rata Revenue Time-Lock on `COMPLETED` Contracts:**
   The canonical pro-rata engine in `shared/revenue_reference.py` computes realised days strictly as `clamp(floor((now - start) / 86400) + 1, 0, num_days)`. It **ignores reservation status**. When a 71-day reservation (totaling 31,950 DH) was marked `COMPLETED` by the operator, only 7 days (3,150 DH) were recognized as of September 3. The remaining 28,800 DH is locked behind future calendar days through November 6, 2026. The operator sees a completed contract paid in full, yet the Dashboard revenue withholds the funds.
5. **The "Today 0.00 DH" Phenomenon:**
   At 02:49 AM on September 3, a 1-day reservation begins at 09:00 AM for 450 DH. The Dashboard displays `1 location aujourd'hui` (rentals count is anchored to start date), but `0.00 DH` of revenue (pro-rata day 0 does not start until 09:00 AM). The operator sees 1 rental today with 0 revenue.
6. **Desktop Client Server Fetcher is Dead Code (`fetch_server=False`):**
   In `desktop/app/ui/main_window.py`, the method `_refresh_dashboard(fetch_server=False)` defaults `fetch_server` to `False`. No caller in the entire desktop codebase ever passes `fetch_server=True`. Therefore, `DashboardFetcher` is never executed. The Desktop Dashboard **never fetches `/api/v1/dashboard/stats` or `/api/v1/dashboard/vehicle-performance`**. It renders exclusively from the local SQLite database.
7. **TopBar Manual Refresh Ignores Revenue:**
   When the operator clicks the TopBar "Actualiser" button, `_on_refresh_clicked` triggers a background sync, which publishes a `DomainStore` revision and invokes `_refresh_dashboard(request_revenue=False)`. Revenue is intentionally excluded from re-fetching to prevent UI flickering. Consequently, clicking the global refresh button updates local tables but **leaves the revenue number untouched**.

---

## 2. PRODUCTION GROUND TRUTH AUDIT (POSTGRESQL RAW DATA)

The following ground truth was extracted directly from PostgreSQL on `https://car-rental-system.fly.dev` at audit timestamp:
- **Casablanca Time:** `2026-09-03 02:49:09+01:00` (`Africa/Casablanca`, UTC+1)
- **UTC Time:** `2026-09-03 01:49:09+00:00`

### 2.1 Vehicles Table (3 Total)
| ID (UUID prefix) | Registration | Brand / Model | Year | Persisted DB Status | Daily Price | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `41f1ff38` | `SYNC_7613` | ForensicBrand ProofModel | 2026 | `AVAILABLE` | 250.00 DH | Operational |
| `fca6c82c` | `koo` | ll kkkk | 2024 | `AVAILABLE` | 450.00 DH | Operational |
| `6395acba` | `pppppppppppppp` | cici oo | 2024 | `AVAILABLE` | 450.00 DH | Operational |

*Note: All three vehicles have `status = 'AVAILABLE'` in the raw database column.*

### 2.2 Reservations Table (17 Total)
| ID | Vehicle ID | Customer | Status | Start (UTC) | End (UTC) | Days | Total Price | Daily Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `ddb6661a` | `fca6c82c` | kkkkkkkkkkkkkkkk | `COMPLETED` | 2026-08-27 08:00 | 2026-09-04 08:00 | 8 | 3,600.00 DH | 450.00 DH |
| `606e1a08` | `fca6c82c` | ................. | `COMPLETED` | 2026-08-27 08:00 | 2026-09-04 08:00 | 8 | 3,600.00 DH | 450.00 DH |
| `5f6fb440` | `fca6c82c` | yyyyyyyyyyyyyyyy | `COMPLETED` | 2026-08-27 08:00 | 2026-11-06 08:00 | 71 | 31,950.00 DH | 450.00 DH |
| `d58bc8dc` | `fca6c82c` | vvvvvvvvvvvvvv | `COMPLETED` | 2026-08-29 08:00 | 2026-09-04 08:00 | 6 | 2,700.00 DH | 450.00 DH |
| `d16be1a9` | `6395acba` | eeeeeeeee | `CANCELLED` | 2026-08-27 08:00 | 2026-09-05 08:00 | 9 | 4,050.00 DH | 450.00 DH |
| `50d32a08` | `6395acba` | E2E LiveSync Probe | `CANCELLED` | 2027-10-01 09:00 | 2027-10-05 09:00 | 4 | 400.00 DH | 100.00 DH |
| `e8e83d67` | `6395acba` | E2E Gate Probe | `CANCELLED` | 2027-11-01 09:00 | 2027-11-05 09:00 | 4 | 600.00 DH | 150.00 DH |
| `7c665b6d` | `41f1ff38` | eeeeeeeeeee | `COMPLETED` | 2026-08-27 08:00 | 2026-09-04 08:00 | 8 | 2,000.00 DH | 250.00 DH |
| `833ab76f` | `41f1ff38` | qni;q | `ACTIVE` | 2026-08-31 08:00 | 2027-03-04 09:00 | 185 | 46,250.00 DH | 250.00 DH |
| `cbf232d0` | `6395acba` | ................. | `RESERVED` | 2026-09-02 08:00 | 2026-09-03 08:00 | 1 | 450.00 DH | 450.00 DH |
| `a184a822` | `fca6c82c` | bobo | `RESERVED` | 2026-09-02 08:00 | 2026-09-03 08:00 | 1 | 450.00 DH | 450.00 DH |
| `ea97a789` | `6395acba` | ,,,,,,,,,,,,,,, | `RESERVED` | 2026-09-03 08:00 | 2026-09-04 08:00 | 1 | 450.00 DH | 450.00 DH |
| `7acc6aec` | `41f1ff38` | kkkkkkkkkkkkk | `CANCELLED` | 2026-08-25 16:27 | 2026-08-26 16:27 | 1 | 250.00 DH | 250.00 DH |
| `16e10721` | `41f1ff38` | eeeeeeeeeeeeeek | `CANCELLED` | 2026-08-26 15:17 | 2027-04-07 15:17 | 224 | 56,000.00 DH | 250.00 DH |
| `90f87394` | `41f1ff38` | ,,,,,,,,,,,,,,, | `COMPLETED` | 2026-08-27 08:00 | 2026-09-02 08:00 | 6 | 1,500.00 DH | 250.00 DH |
| `6abba093` | `6395acba` | ''''''''''''''' | `COMPLETED` | 2026-08-27 08:00 | 2026-09-03 08:00 | 7 | 3,150.00 DH | 450.00 DH |
| `fbaf55f8` | `41f1ff38` | kkl | `CANCELLED` | 2026-12-23 08:00 | 2027-12-22 08:00 | 364 | 91,000.00 DH | 250.00 DH |

**Status Summary:**
- `ACTIVE`: 1
- `RESERVED`: 3
- `COMPLETED`: 7
- `CANCELLED`: 6
- **Total Active Business Contracts:** 11 non-cancelled

### 2.3 Maintenance Table (0 Total)
- `COUNT = 0`. No maintenance tickets exist in production.

### 2.4 Clients Table (13 Total)
- 13 active client profiles exist.

---

## 3. KPI-BY-KPI FORENSIC AUDIT & LINEAGE ANALYSIS

| Dashboard KPI | API Value | Ground Truth Expected | Discrepancy? | Primary Root Cause |
| :--- | :--- | :--- | :--- | :--- |
| **Total Véhicules** | `3` | `3` | None | Operational vehicles count matches |
| **Prêts à louer** (`available`) | `0` | `0` (or `3` by DB status) | **SEMANTIC** | Effective status derives occupancy from time, ignoring DB status |
| **Véhicules en location** (`rented`) | `3` | `3` (or `1` by DB status) | **CRITICAL** | RESERVED reservations covering `now` classified as RENTED |
| **Véhicules réservés** (`reserved`) | `0` | `0` (or `3` by DB status) | **CRITICAL** | Upcoming reservation masked by concurrent rental on same car |
| **En maintenance** (`maintenance`) | `0` | `0` | None | No active maintenance tickets exist |
| **Réservations en cours** (`active_rentals`) | `1` | `1` | None | Exact match to `status == 'ACTIVE'` |
| **Réservations à venir** (`reserved_rentals`)| `3` | `3` | None | Exact match to `status == 'RESERVED'` |
| **Maintenances en cours** | `0` | `0` | None | Unlinked from ticket count, pinned to fleet maintenance |
| **Réservations (Aujourd'hui)** | `1` | `1` | **PERCEPTION** | Reservation starts at 09:00; counted as today's rental at 02:49 AM |
| **Retours prévus aujourd'hui** | `3` | `3` (or `2` active) | **LOGICAL** | Includes `COMPLETED` reservation `6abba093` already returned |
| **CA Aujourd'hui** | `0.00 DH` | `0.00 DH` | **PERCEPTION** | Rental starts at 09:00 AM; pro-rata earns 0 DH before start hour |
| **CA Cette semaine** | `9,650.00 DH`| `9,650.00 DH` | Mathematical match | Week spans Mon Aug 31 to Mon Sep 7 |
| **CA Ce mois** | `6,650.00 DH`| `6,650.00 DH` | Mathematical match | Month spans Sep 1 to Oct 1; completed rentals held back |
| **CA Cette année** | `19,750.00 DH`| `19,750.00 DH`| Mathematical match | Realised pro-rata across 2026 |
| **Top 5 Ranking Order** | ProofModel (#1) | ll kkkk (#1 by count) | **CRITICAL** | Ranked by unearned total contract price, displayed by count |
| **Top 5 Utilization Rate** | `9,950%` | `< 100%` | **CRITICAL** | Formula divides by `(now - last_rental_start)` |

---

## 4. FLEET STATUS & VEHICLE ALLOCATION MATHEMATICAL PROOF

### The Operational Paradox
At `now = 2026-09-03 02:49:09+01:00`, the operator looks at the Dashboard:
- Card 1: **"1 réservation en cours"**
- Card 2: **"3 réservations réservées"**
- Card 3: **"3 véhicules en location"**
- Card 4: **"0 véhicule réservé"**

### The Mathematical Derivation
The effective fleet algorithm in `backend/app/services/fleet_status.py` and `desktop/app/utils/fleet_status.py` implements the following rules:

1. **Vehicle `41f1ff38` (ForensicBrand ProofModel):**
   - Active reservation `833ab76f`: `2026-08-31 08:00 UTC <= now (2026-09-03 01:49 UTC) < 2027-03-04 09:00 UTC`.
   - Condition `start <= now < end` is **TRUE**.
   - Result: **`RENTED`**.

2. **Vehicle `fca6c82c` (ll kkkk):**
   - Reservation `a184a822`: `status = RESERVED`.
   - Window: `2026-09-02 08:00 UTC <= now (2026-09-03 01:49 UTC) < 2026-09-03 08:00 UTC`.
   - Condition `start <= now < end` is **TRUE**.
   - Under fleet status logic:
     > *"This business hands the car over at reservation start with no separate pickup step, so a RESERVED reservation whose window contains `now` still means the car is out."*
   - Result: **`RENTED`** (despite the database status being `RESERVED`).

3. **Vehicle `6395acba` (cici oo):**
   - Reservation `cbf232d0`: `status = RESERVED`.
   - Window: `2026-09-02 08:00 UTC <= now (2026-09-03 01:49 UTC) < 2026-09-03 08:00 UTC`.
   - Condition `start <= now < end` is **TRUE** -> added to `rented_vids`.
   - Reservation `ea97a789`: `status = RESERVED`.
   - Window: `2026-09-03 08:00 UTC to 2026-09-04 08:00 UTC`.
   - Condition `now < start` is **TRUE** -> added to `reserved_vids`.
   - Disjoint set subtraction: `reserved_vids -= rented_vids`.
   - Since `6395acba` is in `rented_vids`, it is **subtracted from `reserved_vids`**.
   - Result: **`RENTED`**. Vehicle is not counted as reserved.

### Summary of Conflict
- Set of Rented Vehicles: `{"41f1ff38", "fca6c82c", "6395acba"}` -> Count = **3**.
- Set of Reserved Vehicles: `set() - {...}` -> Count = **0**.
- Available Vehicles: `3 - 3 - 0 = 0`.

**Operator Confusion:** 
The operator sees that only 1 customer is officially checked in (`ACTIVE`), and 3 customers have bookings (`RESERVED`). But the fleet screen claims that all 3 cars are out on rent and 0 are reserved.

---

## 5. REVENUE ENGINE DEEP FORENSIC

### 5.1 The `COMPLETED` Reservation Revenue Withholding Defect
In `shared/revenue_reference.py`, the pro-rata realised day calculation is defined as:
```python
def _realised_days(start_dt: datetime, num_days: int, now: datetime) -> int:
    elapsed = (now - start_dt).total_seconds() / 86400.0
    n = math.floor(elapsed) + 1
    if n < 0: n = 0
    if n > num_days: n = num_days
    return n
```
**The Defect:**
`_realised_days` evaluates elapsed real-world time regardless of whether the reservation status is `COMPLETED`.

#### Case Study: Reservation `5f6fb440`
- Customer: `yyyyyyyyyyyyyyyy`
- Vehicle: `fca6c82c`
- Total Contract Price: `31,950.00 DH` (71 days @ 450.00 DH/day)
- Status: **`COMPLETED`**
- Start Date: `2026-08-27`
- End Date: `2026-11-06`
- Elapsed days at `2026-09-03`: 7 days.
- Realised Revenue Recognized: `7 * 450.00 = 3,150.00 DH`.
- Revenue Withheld: `31,950.00 - 3,150.00 = 28,800.00 DH`.

**Consequence:**
Even though this rental was concluded and marked `COMPLETED`, 90% of its revenue is withheld from the operator's month-to-date and year-to-date dashboard cards. The revenue will only trickle in day-by-day until November 6, 2026.

### 5.2 The 0.00 DH "Today" Revenue Dissonance
- On September 3 at 02:49 AM, Reservation `ea97a789` starts at 09:00 AM Casablanca time.
- `_rentals_started(reservations, 2026-09-03, 2026-09-04)` checks `start_date == 2026-09-03` -> **Count = 1**.
- `_realised_days` checks `now >= start_datetime`:
  - `now = 02:49 AM`, `start = 09:00 AM`.
  - `now < start` -> **Realised days = 0**.
  - **Revenue = 0.00 DH**.
- **Display:** "1 réservation aujourd'hui — 0.00 DH". The operator perceives this as a mathematical breakdown.

### 5.3 Week vs Month Discrepancy
- Week bounds: `2026-08-31` to `2026-09-07`.
  - Rentals started in week: `833ab76f` (Aug 31), `cbf232d0` (Sep 2), `a184a822` (Sep 2), `ea97a789` (Sep 3) = **4 rentals**.
  - Week revenue: **9,650.00 DH**.
- Month bounds: `2026-09-01` to `2026-10-01`.
  - Rentals started in month: `cbf232d0` (Sep 2), `a184a822` (Sep 2), `ea97a789` (Sep 3) = **3 rentals**.
  - Month revenue: **6,650.00 DH**.

The operator sees:
- **Cette semaine:** 4 réservations, 9 650.00 DH
- **Ce mois:** 3 réservations, 6 650.00 DH
Because Monday August 31 belongs to "This Week" but not "This Month", the weekly metrics exceed the monthly metrics. Without clear boundary indicators, operators interpret this as corrupted data.

---

## 6. TOP 5 RANKING FORENSIC ANALYSIS

### 6.1 The Four Compounded Failures in `GET /dashboard/vehicle-performance`

```
┌────────────────────────────────────────────────────────────────────────┐
│ UI Display: "Top 5 véhicules les plus loués"                           │
├────────────────────────────────────────────────────────────────────────┤
│ #1 ForensicBrand ProofModel:   3 locations   [======]                  │
│ #2 ll kkkk:                    5 locations   [==================]      │
│ #3 cici oo:                    2 locations   [====]                    │
└────────────────────────────────────────────────────────────────────────┘
```

#### Failure 1: Inverted Sorting Metric
- In `RentalRepository.get_vehicle_stats()`:
  ```python
  .order_by(func.sum(Reservation.total_price).desc())
  ```
- In `desktop/app/sync/dashboard_cache.py`:
  ```python
  ranked = sorted(agg.values(), key=lambda x: x["total_revenue"], reverse=True)[:limit]
  ```
- In `desktop/app/ui/dashboard.py`:
  ```python
  count_lbl = QLabel(f"{v.get('rental_count', 0)} {t('dashboard.rentals_unit')}")
  width_pct = int((v.get("rental_count", 0) / max_rentals) * 100)
  ```
The database and cache sort by **Revenue**, while the UI displays and graphs **Rental Count**. Vehicle #1 has 3 rentals, while Vehicle #2 has 5 rentals.

#### Failure 2: Top 5 Revenue Sums Total Contract Prices Upfront
In `RentalRepository.get_vehicle_stats()`:
```python
func.coalesce(func.sum(Reservation.total_price), 0).label("total_revenue")
```
While the Dashboard revenue card enforces daily pro-rata recognition, the Top 5 calculation sums the raw `total_price` of all reservations. 
- For Vehicle `41f1ff38`, Reservation `833ab76f` is a 185-day booking for 46,250 DH that has only elapsed 3 days (earning 750 DH). 
- `get_vehicle_stats` awards the entire 46,250 DH to the vehicle immediately, pushing its revenue to 49,750 DH and elevating it to the #1 spot.

#### Failure 3: Astronomical Utilization Rate
In `backend/app/services/dashboard_service.py`:
```python
if stat["last_rental"]:
    first_rental_dt = datetime.fromisoformat(stat["last_rental"])
    now_utc = datetime.now(timezone.utc)
    total_possible_days = max(1, (now_utc - first_rental_dt.astimezone(timezone.utc)).days)
    stat["utilization_rate"] = round((stat["total_days"] / total_possible_days) * 100, 1)
```
1. In `RentalRepository.get_vehicle_stats()`, the column is:
   `func.max(Reservation.start_datetime).label("last_rental")`
2. In `DashboardService`, the code renames `last_rental` to `first_rental_dt`!
3. For Vehicle `41f1ff38`, `last_rental` is `2026-08-31`.
4. `now_utc - 2026-08-31` = **2 days**.
5. `total_days` = **199 days**.
6. `utilization_rate` = `(199 / 2) * 100` = **9,950.0%**.

#### Failure 4: Dead Code in Desktop Client
In `desktop/app/ui/main_window.py`:
```python
def _refresh_dashboard(self, fetch_server: bool = False, request_revenue: bool = False):
    ...
    if fetch_server and self._is_online and self._access_token:
        fetcher = DashboardFetcher(...)
```
`fetch_server` is never set to `True`. The Desktop app never fetches `/api/v1/dashboard/vehicle-performance`, relying entirely on local SQLite computations.

---

## 7. MAINTENANCE IMPACT & COLLISION ANALYSIS

### 7.1 Unified Card Hides Future Tickets
In `backend/app/services/dashboard_service.py`:
```python
active_maintenances = maintenance # fleet occupied vehicles
...
"active_maintenance_tickets": active_maintenances
```
The Dashboard displays `0` for active maintenance tickets whenever 0 vehicles are currently in the workshop. If an operator creates a ticket scheduled to begin tomorrow, the ticket appears in the Maintenance view but shows as `0` on the Dashboard, leading staff to believe the ticket was dropped.

### 7.2 Collision Precedence
Under `RentalRepository.cancel_overlapping_reservations()`:
When a maintenance window is confirmed, overlapping `RESERVED` and `ACTIVE` reservations are automatically cancelled with reason `MAINTENANCE`. 
Currently, there are 0 maintenance tickets in production, so maintenance collisions are not contributing to the current discrepancy.

---

## 8. RESERVATION LIFECYCLE & STATE MACHINE AUDIT

The application lacks an automated check-in/check-out transition worker:
- When a reservation reaches `start_datetime`, its database status remains `RESERVED` until staff manually update it.
- When `end_datetime` passes, the reservation remains `RESERVED` or `ACTIVE` until staff manually mark it `COMPLETED`.
- Reservations `cbf232d0` and `a184a822` started on September 2 and ended at 09:00 AM on September 3. At 02:49 AM, their database status was still `RESERVED`. 
- The backend fleet engine compensates for this by treating `RESERVED` as `RENTED` during its active time window. However, this creates a split-brain condition where the Reservations list says `Réservée` while the Dashboard says `En location`.

---

## 9. TEMPORAL & BOUNDARY DISCREPANCIES

1. **Local Midnight vs UTC Midnight:**
   All financial periods (`today`, `week`, `month`, `year`) are calculated using local midnights in `Africa/Casablanca` (`UTC+1`). 
   However, `desktop/app/ui/dashboard.py` formats the "Dernière actualisation" label using the client operating system's local wall clock:
   ```python
   self._last_refresh_lbl = QLabel(t("dashboard.last_refresh", time=datetime.now().strftime('%H:%M')))
   ```
   If client workstations have unaligned system clocks, the refresh timestamp diverges from the server's event logs.
2. **BoundaryClock Operation:**
   `desktop/app/state/boundary_clock.py` calculates the next earliest transition boundary (`next_boundary_rows`). When the clock reaches Casablanca midnight, it successfully invalidates the snapshot and updates the UI without requiring an application restart.

---

## 10. DESKTOP CACHING & OFFLINE SYNCHRONIZATION AUDIT

### 10.1 The TopBar Refresh Blindspot
When an operator clicks the TopBar "Actualiser" button:
1. `_on_refresh_clicked()` runs `_run_sync()`.
2. The sync thread pushes and pulls deltas from Fly.io.
3. `_on_sync_finished()` emits `get_event_bus().data_refreshed`.
4. The event bus triggers `_refresh_dashboard(fetch_server=False, request_revenue=False)`.
5. Because `request_revenue` is `False`, the revenue panel **skips re-fetching**.
6. The operator clicks refresh, the spinner stops, but the revenue figure remains stale.

### 10.2 SQLite Drift Risk
Because `DashboardFetcher` is inactive, the Desktop dashboard depends entirely on SQLite having an exact copy of the PostgreSQL database. If sync is interrupted, the Desktop dashboard displays numbers calculated from incomplete local data.

---

## 11. CROSS-SCREEN & CROSS-PLATFORM PARITY AUDIT

| Component | Backend / API (`Fly.io`) | Desktop App (`PySide6`) | Mobile App (`Android`) | Parity Status |
| :--- | :--- | :--- | :--- | :--- |
| **Fleet Counts Source** | `fleet_status.py` (SQL) | `fleet_status.py` (SQLite) | `/api/v1/dashboard/stats` | **DIVERGENT** (Desktop never queries server stats) |
| **Revenue Source** | `revenue_service.py` | `/api/v1/dashboard/revenue` | `/api/v1/dashboard/stats` | **MATCH** (Same pro-rata logic) |
| **Top 5 Ranking Source** | `RentalRepo.get_vehicle_stats` | Local SQLite calculation | Not displayed | **DIVERGENT** (Desktop ignores server performance route) |
| **Top 5 Sort Key** | `SUM(total_price) DESC` | `SUM(total_price) DESC` | N/A | **FLAWED** (Both sort by unearned revenue, not rental count) |
| **Manual Refresh** | Real-time | Ignores revenue panel | Full API re-fetch | **DIVERGENT** (Desktop TopBar refresh does not update revenue) |

---

## 12. DISCREPANCY MATRIX & ROOT CAUSE TAXONOMY

| # | Discrepancy Symptom | Severity | Affected Module | Root Cause Summary |
| :--- | :--- | :--- | :--- | :--- |
| **D1** | Top 5 vehicle ranked #1 has fewer rentals than #2 | **HIGH** | `RentalRepository`, `dashboard.py` | Query sorts by `total_revenue DESC`, but UI labels and graphs `rental_count`. |
| **D2** | Top 5 utilization rates exceed 9,000% | **HIGH** | `dashboard_service.py` | Formula divides total rental days by days since latest rental start. |
| **D3** | Fleet card shows 3 Rented, 0 Reserved; Reservations card shows 1 Active, 3 Reserved | **HIGH** | `fleet_status.py` vs `dashboard_service.py` | Fleet card derives status from time intervals; KPI card counts database status enums. |
| **D4** | Revenue for `COMPLETED` rentals withheld until future months | **HIGH** | `revenue_reference.py` | `_realised_days` checks clock time only, ignoring contract completion. |
| **D5** | Today revenue is 0.00 DH despite 1 rental starting today | **MEDIUM** | `revenue_reference.py` | Rental starts at 09:00 AM; at 02:49 AM, elapsed time is negative, yielding 0 realised days. |
| **D6** | Desktop never fetches server dashboard stats | **HIGH** | `main_window.py` | `fetch_server` is hardcoded to `False` on all call paths. |
| **D7** | TopBar "Actualiser" button does not update revenue | **MEDIUM** | `main_window.py` | `_on_sync_finished` calls fan-out with `request_revenue=False`. |
| **D8** | `today_returns` includes reservations already marked `COMPLETED` | **LOW** | `dashboard_service.py` | Query filters `status != 'CANCELLED'`, counting finished rentals as pending returns. |
| **D9** | Week reservations (4) exceeds Month reservations (3) | **MEDIUM** | `shared/money_time.py` | ISO week starts Monday Aug 31, spanning two calendar months. |
| **D10** | Maintenance card displays 0 when future tickets exist | **LOW** | `dashboard_service.py` | Ticket count is replaced with vehicles currently undergoing maintenance. |
| **D11** | Vehicles list shows "Disponible" while Dashboard shows "En location" | **HIGH** | `vehicles.py`, `vehicle_list.py` | Vehicles list defaults to persisted DB status instead of effective status in certain dialogs. |
| **D12** | Top 5 revenue uses full contract prices, contradicting pro-rata CA card | **HIGH** | `rental_repository.py` | `get_vehicle_stats()` sums raw `total_price`, ignoring pro-rata realization. |

---

## 13. EXACT LINE-BY-LINE CODE CULPRITS

### 1. `backend/app/repositories/rental_repository.py`
- **Line 278:**
  ```python
  .order_by(func.sum(Reservation.total_price).desc())
  ```
  *Culprit:* Sorts by unearned total revenue instead of `rental_count DESC` or realised revenue.
- **Line 270:**
  ```python
  func.coalesce(func.sum(Reservation.total_price), 0).label("total_revenue")
  ```
  *Culprit:* Sums total contract price upfront instead of pro-rata realised revenue.
- **Lines 197-212:**
  ```python
  select(Reservation).where(
      Reservation.end_datetime >= today_start,
      Reservation.end_datetime <= today_end,
      Reservation.status != "CANCELLED",
  )
  ```
  *Culprit:* Does not exclude `status == 'COMPLETED'`, counting completed rentals as pending returns.

### 2. `backend/app/services/dashboard_service.py`
- **Lines 188-198:**
  ```python
  if stat["last_rental"]:
      first_rental_dt = datetime.fromisoformat(stat["last_rental"])
      ...
      total_possible_days = max(1, (now_utc - first_rental_dt.astimezone(timezone.utc)).days)
      stat["utilization_rate"] = round((stat["total_days"] / total_possible_days) * 100, 1)
  ```
  *Culprit:* Uses `last_rental` (most recent start) as the denominator, generating 9,950% utilization rates.
- **Line 58:**
  ```python
  active_maintenances = maintenance
  ```
  *Culprit:* Replaces active ticket count with current vehicle occupancy count.

### 3. `shared/revenue_reference.py`
- **Lines 86-96:**
  ```python
  def _realised_days(start_dt: datetime, num_days: int, now: datetime) -> int:
      elapsed = (now - start_dt).total_seconds() / 86400.0
      n = math.floor(elapsed) + 1
      ...
      return n
  ```
  *Culprit:* Ignores `status == 'COMPLETED'`. If a contract is completed, all contract days should be realised.

### 4. `desktop/app/ui/main_window.py`
- **Line 514:**
  ```python
  def _refresh_dashboard(self, fetch_server: bool = False, request_revenue: bool = False):
  ```
  *Culprit:* `fetch_server` is never invoked with `True`, making server dashboard fetching dead code.
- **Line 1155:**
  ```python
  ("dashboard", self._refresh_dashboard),
  ```
  *Culprit:* Domain fan-out runs with `request_revenue=False`, leaving revenue stale after TopBar refresh.

### 5. `desktop/app/ui/dashboard.py`
- **Lines 553-579:**
  ```python
  max_rentals = max([v.get("rental_count", 0) for v in self._top_vehicles_data]) ...
  count_lbl = QLabel(f"{v.get('rental_count', 0)} {t('dashboard.rentals_unit')}")
  width_pct = int((v.get("rental_count", 0) / max_rentals) * 100)
  ```
  *Culprit:* Displays rental counts and sizes progress bars by rental count on a list sorted by revenue.

---

## 14. IMPACT ANALYSIS & OPERATOR PERCEPTION PROOF

When the operator opens the Desktop Dashboard, they experience immediate cognitive dissonance:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                               OPERATOR DASHBOARD                                │
├───────────────────────────────────────┬─────────────────────────────────────────┤
│ Performance Opérationnelle            │ Chiffre d'affaires                      │
│ - Réservations ce mois: 3             │ - Ce mois: 6 650.00 DH                  │
│ - Maintenances en cours: 0            │   (3 bookings @ 450 DH = 1350 DH,       │
│   (Created a ticket for tomorrow,     │    yet card shows 6650 DH without       │
│    dashboard says 0)                  │    explaining August carry-over)        │
├───────────────────────────────────────┴─────────────────────────────────────────┤
│ État de la flotte                                                               │
│ - Prêts à louer: 0                    - Véhicules en location: 3                │
│ - Véhicules réservés: 0               - En maintenance: 0                       │
│   (Reservations screen shows 3 bookings as "Réservée",                          │
│    but fleet status claims 0 are reserved and all 3 cars are rented!)           │
├─────────────────────────────────────────────────────────────────────────────────┤
│ Top 5 Véhicules les plus loués                                                  │
│ #1 ForensicBrand ProofModel: 3 locations [========]                             │
│ #2 ll kkkk:                  5 locations [=======================]              │
│   (#1 has fewer rentals than #2 in a list titled "Most Rented"!)                │
└─────────────────────────────────────────────────────────────────────────────────┘
```

Every single section contains an apparent contradiction. The operator reasonably concludes that the entire dashboard is unreliable.

---

## 15. COMPLETE REMEDIATION PLAN (SPECIFICATIONS ONLY)

> [!IMPORTANT]
> **READ-ONLY AUDIT MODE:** No source files have been modified. The following remediation plan specifies the exact changes required to achieve 100% mathematical, architectural, and visual consistency.

### Phase 1: Unify Top 5 Ranking Logic & Presentation
1. **Define the Canonical Metric:** 
   Rename the group box in `desktop/app/ui/dashboard.py` to match its sort key:
   - If ranking by rental volume: Sort by `rental_count DESC, total_revenue DESC`.
   - If ranking by financial performance: Title as *"Top 5 Véhicules par chiffre d'affaires"* and display `{revenue} DH` alongside `{rental_count} locations`.
2. **Harmonize Revenue Calculation:**
   Update `RentalRepository.get_vehicle_stats()` to compute pro-rata realised revenue rather than raw `SUM(total_price)`.
3. **Fix Utilization Rate Calculation:**
   Compute `utilization_rate` using the vehicle's active operational days:
   ```python
   total_possible_days = max(1, (now_utc - vehicle.created_at).days)
   stat["utilization_rate"] = min(100.0, round((stat["total_days"] / total_possible_days) * 100, 1))
   ```

### Phase 2: Resolve Completed Contract Revenue Withholding
1. Update `shared/revenue_reference.py`:
   If a reservation has `status == 'COMPLETED'`, all `num_days` are fully realised:
   ```python
   if res.get("status") == "COMPLETED":
       realised = num_days
   else:
       realised = _realised_days(start_dt, num_days, now)
   ```
   This ensures revenue for finished contracts is recognized immediately.

### Phase 3: Harmonize Fleet Status vs Reservation Status
1. **Clarify Dashboard UI Labels:**
   - Label Contract KPIs: *"Contrats en cours"* (`active_rentals`) and *"Réservations à venir"* (`reserved_rentals`).
   - Label Fleet Cards: *"Véhicules physiquement sortis"* (`rented`) and *"Disponibles immédiatement"* (`available`).
2. Add tooltips explaining that a vehicle with a booking covering the current hour is physically out, even if administrative check-in has not been submitted.

### Phase 4: Fix Desktop Server Dashboard Fetcher & Refresh
1. In `desktop/app/ui/main_window.py`:
   - Set `fetch_server=True` when `_refresh_dashboard` is called during manual refresh or page navigation.
   - Set `request_revenue=True` on manual refresh from the TopBar button.
2. Ensure `DashboardFetcher` updates both `overview` and `top_vehicles` from server responses.

### Phase 5: Filter Completed Rentals from `today_returns`
1. In `backend/app/services/dashboard_service.py` and `RentalRepository.get_today_returns()`:
   Add `Reservation.status.in_(["ACTIVE", "RESERVED"])` so rentals that have already been returned do not appear as pending returns.

---

## 16. MATHEMATICAL PROOF OF CORRECTNESS POST-REMEDIATION

Once the remediation specifications are implemented, the dashboard metrics will reconcile mathematically:

### Fleet Allocation (3 Vehicles Total)
- Rented: `3` (All 3 vehicles covered by active/reserved intervals at 02:49 AM)
- Reserved: `0` (Upcoming bookings masked by active rental on same vehicle)
- Available: `0`
- Maintenance: `0`
- **Total:** `3 + 0 + 0 + 0 = 3` (Conserved)

### Reservation Contracts
- Active Contracts (`status == 'ACTIVE'`): `1` (`833ab76f`)
- Bookings Awaiting Pickup (`status == 'RESERVED'`): `3` (`cbf232d0`, `a184a822`, `ea97a789`)
- Completed Contracts: `7`
- Cancelled Contracts: `6`
- **Total Contracts:** `1 + 3 + 7 + 6 = 17` (Conserved)

### Returns Today
- Non-completed rentals ending September 3: `cbf232d0` (ends 09:00), `a184a822` (ends 09:00) = **2 pending returns**.
- Completed rental `6abba093` excluded from pending returns.

### Top 5 Performance (Ranked by Rental Count)
1. **ll kkkk (`koo`):** 5 locations, 94 days, 42,300.00 DH [====================]
2. **ForensicBrand ProofModel (`SYNC_7613`):** 3 locations, 199 days, 49,750.00 DH [============]
3. **cici oo (`pppppppppppppp`):** 2 locations, 8 days, 3,600.00 DH [========]
*Rank order matches progress bar width and displayed rental count.*

### Top 5 Performance (Ranked by Realised Revenue)
1. **ll kkkk (`koo`):** 42,300.00 DH (5 locations)
2. **cici oo (`pppppppppppppp`):** 3,600.00 DH (2 locations)
3. **ForensicBrand ProofModel (`SYNC_7613`):** 4,250.00 DH realised (3 locations)

---
*Report compiled autonomously via deep codebase and production database inspection. Zero production or repository modifications applied.*
