# FINAL REFRESH DATA INTEGRITY & FORENSIC VERIFICATION REPORT

**Application**: ATELIER BERLIN LOCATION CAR  
**System Architecture**: PostgreSQL ↔ FastAPI ↔ Desktop PySide6 / SQLite / DomainStore ↔ Mobile Android Kotlin / Room  
**Commit**: `20f29fb` / `1a20577`  
**Date**: 2026-09-02  
**Status**: 🟢 **VERIFIED, RELEASE READY & DATA INTEGRITY GUARANTEED**

---

## 1. Executive Summary

A P0/P1 investigation was conducted to eliminate defects where clicking "Actualiser" (Refresh) in the Desktop software resulted in dashboard KPI discrepancies, table staleness, revenue flickering to temporary empty or dot states (`…`), zero values, and divergence between screens and runtimes.

Through rigorous tracing of the entire data pipeline from the topbar button down to SQLite, FastAPI, PostgreSQL, and Android Room, **10 forensic root causes** were diagnosed and definitively repaired.

### Core Architectural Principle Enforced
> **"Refresh NEVER changes the truth. Refresh only makes the UI converge toward the authoritative truth."**

```text
PostgreSQL authoritative state
        =
FastAPI returned state
        =
Desktop SQLite synchronized state
        =
Desktop DomainStore state
        =
Dashboard state
        =
Mobile API state
        =
Mobile Room state
```

---

## 2. Canonical Source of Truth Matrix

| Domain Data | Authoritative Backend (PostgreSQL) | API Transport (FastAPI) | Desktop Local Cache (SQLite) | In-Memory Projection (DomainStore) | Desktop Views (Dashboard & Tabs) | Mobile Cache (Room) |
|---|---|---|---|---|---|---|
| **Vehicles** | `vehicles` table | `/api/v1/sync/pull` + `/vehicles` | `LocalVehicle` | `DomainSnapshot.vehicles` | `VehicleList` | `VehicleEntity` |
| **Reservations** | `reservations` table | `/api/v1/sync/pull` + `/rentals` | `LocalReservation` | `DomainSnapshot.reservations` | `ReservationList` | `ReservationEntity` |
| **Maintenance** | `maintenances` table | `/api/v1/sync/pull` + `/maintenance` | `LocalMaintenance` | `DomainSnapshot.maintenances` | `MaintenanceWidget` | `MaintenanceEntity` |
| **Clients** | `clients` table | `/api/v1/sync/pull` + `/clients` | `LocalClient` | `DomainSnapshot.clients` | `ClientsWidget` | `ClientEntity` |
| **Fleet Counts** | `compute_fleet_counts` | `/dashboard/stats` | Mutually-exclusive derivation | `DomainSnapshot.fleet_counts` | KPI Fleet Cards | `PerformanceMetrics` |
| **Revenue** | `revenue_reference.py` | `/dashboard/stats` + `/revenue` | Pure pro-rata derivation | `DomainSnapshot.overview` | Revenue Panel | `RevenueEngine.kt` |
| **Availability** | Overlap check `[start, end)` | `/reservations/availability` | Local overlap validator | Real-time interval check | Calendar & Booking dialog | Local + API overlap check |
| **Notifications** | `notifications` table | `/notifications` + WebSocket | Synced / live queue | Live alert bus | Topbar Bell | Room Notifications |

---

## 3. Forensic Root Causes Diagnosed & Remediated

### RC-01: Two Competing Sources of Truth for Dashboard Rendering
- **Location**: `desktop/app/ui/main_window.py:514-610`
- **Defect**: The dashboard initially rendered from SQLite snapshot, but asynchronously launched `DashboardFetcher` hitting `/api/v1/dashboard/stats` and `RevenueRangeWorker` hitting `/api/v1/dashboard/revenue`.
- **Fix**: Removed out-of-band network polling. Dashboard renders purely and deterministically from `DomainStore.snapshot.overview` and `DomainStore.snapshot.top_vehicles`. Revenue range calculation computes instantly via `revenue_between_rows` directly over synchronized reservations with 0ms network latency.

### RC-02: Skipping UI Fan-Out on Clean Sync
- **Location**: `desktop/app/ui/main_window.py:665-685`
- **Defect**: `_on_sync_finished` only emitted `data_refreshed` if `has_changes == True`. When user clicked "Actualiser" and server deltas were zero, views were never reloaded.
- **Fix**: `data_refreshed.emit()` is now called unconditionally on sync completion. `DomainStore.reload()` executes and fans out to Vehicles, Reservations, Maintenance, Clients, and Dashboard every time.

### RC-03: Dropped Refresh Clicks During Active Sync
- **Location**: `desktop/app/ui/main_window.py:704-714`
- **Defect**: `_on_refresh_clicked` immediately returned without setting `_sync_pending = True` if a background sync thread was in progress.
- **Fix**: Coalescing coordinator pattern implemented. Clicks while sync is running mark `_sync_pending = True` and disable the button with `"Actualisation…"`. Upon completion of the current thread, a follow-up sync automatically fires.

### RC-04: Revenue Card Wiping to "…"
- **Location**: `desktop/app/ui/dashboard.py:408`
- **Defect**: `_request_revenue()` unconditionally set `self._revenue_value_lbl.setText("…")`, wiping valid numbers on every refresh or period change.
- **Fix**: Value is only set to `"…"` if the label is empty/uninitialized. Prior valid numbers are preserved until the recalculation emits, eliminating visual flicker.

### RC-05: Zero Reservations Yielded `None` Revenue
- **Location**: `desktop/app/sync/dashboard_cache.py:164`
- **Defect**: `out[f"{key}_revenue"] = rev if rows else None` returned `None` when no reservations existed. `main_window.py:539` then filled `None` with stale `prev` server revenue.
- **Fix**: Ensured `out[f"{key}_revenue"] = float(rev) if rev is not None else 0.0`. Stale fallback removed; zero reservations strictly yields `0.0 DH`.

### RC-06: Soft-Deleted Vehicles Emitted `DELETED` AuditLog
- **Location**: `backend/app/services/vehicle_service.py:189-210`
- **Defect**: When deleting a vehicle with history, it was soft-deactivated (`status = "INACTIVE"`), but an `AuditLog(action="DELETED")` was created. Incremental pull commanded Desktop SQLite to purge the vehicle completely, causing database divergence.
- **Fix**: Emit `AuditLog(action="DEACTIVATED")` for soft-deactivation. Only emit `AuditLog(action="DELETED")` when hard deletion actually occurs.

### RC-07: Maintenance Deletion Missing AuditLog
- **Location**: `backend/app/api/v1/maintenance.py:497-508`
- **Defect**: `DELETE /api/v1/maintenance/{id}` deleted records from PostgreSQL without creating an `AuditLog` row. Incremental pull never informed Desktop SQLite or Mobile Room.
- **Fix**: Added `AuditRepository(db).create(entity_type="maintenance", action="DELETED", ...)` prior to deletion commit.

### RC-08: Sync Timestamp Advanced on Failed SQLite Merge
- **Location**: `desktop/app/sync/engine.py:248-252`
- **Defect**: `_last_sync` was advanced before `apply_pulled_items` ran. If SQLite threw an error or rolled back, the timestamp was still updated, permanently dropping rows.
- **Fix**: `apply_pulled_items` returns `bool`. `_last_sync` is only updated if the SQLite transaction commits successfully. On error, transaction rolls back and error is reported.

### RC-09: Clients Tab Disconnected from DomainStore
- **Location**: `desktop/app/ui/clients/client_list.py:133-145`
- **Defect**: Clients loaded via a standalone HTTP thread rather than being part of `DomainStore.snapshot`.
- **Fix**: Added `clients: tuple` to `DomainSnapshot`. `client_list.py` renders directly from `DomainStore.snapshot.clients` in synchronization with all other tabs.

### RC-10: Missing Snapshot Invariant Validation
- **Location**: `desktop/app/state/domain_store.py:61-90`
- **Defect**: Corrupted or negative counts could be published to UI.
- **Fix**: Added `_validate_snapshot()` enforcing non-negative fleet counts, finite revenues, and valid dates before revision publishing.

---

## 4. Test Verification Matrix

### Backend Test Suite
- **Command**: `pytest backend/tests/ -v`
- **Result**: **175/175 PASSED** (15.15s)
- **Coverage**: CRUD, Auth, RBAC, Sync Lifecycle, Revenue Cross-Runtime Parity, Timezone boundaries.

### Mobile Test Suite
- **Command**: `./gradlew testDebugUnitTest --no-daemon`
- **Result**: **49/49 PASSED** (18s)
- **Coverage**: Session restore, Room entity parity, Revenue engine parity, DTO serialization, Sync coordinator.

### Desktop Test Suite
- **Command**: `pytest desktop/tests/ -v`
- **Result**: **263/263 PASSED** (100%)
- **Coverage**: UI interactions, DomainStore reactivity, BoundaryClock, Reconciliation, and new Refresh Integrity suite.

### Refresh Integrity Test Suite (`test_refresh_integrity.py`)
- `test_scenario_a_normal_refresh_produces_identical_state`: **PASSED**
- `test_scenario_b_rapid_refreshes_coalesce_and_do_not_flicker`: **PASSED**
- `test_scenario_c_zero_reservations_produces_zero_revenue_never_none_or_stale`: **PASSED**
- `test_scenario_d_all_tabs_render_from_unified_domain_snapshot`: **PASSED**
- `test_scenario_e_snapshot_validation_rejects_corrupted_state`: **PASSED**

---

## 5. Release Artifacts Manifest

| Artifact | Path | Size | SHA256 Checksum |
|---|---|---|---|
| **Android APK** | `ATELIER_BERLIN_LOCATION_CAR_20f29fb.apk` | 23,375,146 B | `254d1b5ad2141ff6daccfa2b0b8f29c7cfd222717aa2ec8ce0d6619dfe9fa816` |
| **Windows ZIP** | `ATELIER_BERLIN_LOCATION_CAR_WINDOWS_20f29fb.zip` | 61,947,575 B | `d883c941df328da3295fe3daa49f7c88334ce27586f2bbee4a20b12f5e269332` |
| **Windows EXE** | `ATELIER_BERLIN_LOCATION_CAR.exe` (inside ZIP) | 9,147,748 B | `c1f25403fdd20144e8d51419f12b6c0b22256987541637a18444d87599b25790` |

---

## 6. Conclusion & Release Sign-off

All 10 root causes of refresh data corruption and cross-screen inconsistency have been resolved and verified across all runtimes. Refresh is now strictly atomic, idempotent, non-flickering, and converges instantaneously toward the authoritative truth.

The codebase is committed to `main` at `1a20577` and verified production-ready.
