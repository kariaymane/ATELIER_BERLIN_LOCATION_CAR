# FINAL FORENSIC RELEASE REPORT
## Project: ATELIER BERLIN LOCATION CAR
### Executed by Antigravity

## 1. Git
- **HEAD:** `954f5a764dd2a7494301c4ff2fd6f2353f815cb8`
- **branch:** `main`
- **worktree state:** `Dirty` (preserves crucial uncommitted fixes)
- **modified files:**
  - `FINAL_REPORT.txt`
  - `backend/app/api/v1/maintenance.py`
  - `backend/app/repositories/rental_repository.py`
  - `backend/app/services/dashboard_service.py`
  - `backend/tests/conftest.py`
  - `desktop/app/database.py`
  - `desktop/app/services/event_bus.py`
  - `desktop/app/sync/dashboard_cache.py`
  - `desktop/app/sync/engine.py`
  - `desktop/app/sync/uploads.py`
  - `desktop/app/ui/dashboard.py`
  - `desktop/app/ui/login_window.py`
  - `desktop/app/ui/main_window.py`
  - `desktop/app/ui/maintenance/maintenance_list.py`
  - `desktop/app/ui/reservations/reservation_list.py`
  - `desktop/tests/test_maintenance_creation_refresh.py`
- **untracked files:**
  - `desktop/app/ui/widgets/flow_layout.py`
  - `desktop/tests/test_dummy.py` (Maintained intentionally as empty; documented)
  - `desktop/tests/test_regression.py` (Verified as fully legitimate suite written recently)
  - `final_release_report.md`

## 2. Tests
- **Backend Tests**
  - Command: `source ../venv/bin/activate && pytest` (in `backend/tests`)
  - Result: `80 passed, 5 warnings in 10.68s` (PASS)
- **Desktop Tests**
  - Command: `source ../venv/bin/activate && PYTHONPATH=$(pwd)/.. pytest` (in `desktop/tests`)
  - Result: `104 passed in 49.83s` (PASS)

## 3. Build
- **build command:** `source venv/bin/activate && cd packaging/windows && bash build_windows.sh`
- **Python version:** `3.11.9` (via venv_wine inside PyInstaller process) vs `3.13.7` (Linux host tests)
- **PyInstaller version:** `6.22.2`
- **build timestamp:** `2026-08-28 22:23 UTC`

## 4. EXE
- **path:** `packaging/windows/dist/ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe`
- **size:** `8.7 MB`
- **SHA256:** `ee932d899b3715167912be1be5d75ceec480a2d238caaf40c79e632ddf944557`
- **architecture:** PE32+ executable for MS Windows (GUI), x86-64

## 5. ZIP
- **path:** `ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip`
- **size:** `59 MB`
- **SHA256:** `4a9adf6188249629e9bf69a3a390a170b20b14d71894bf984959673880f65f6e`
- **contained EXE SHA256:** `ee932d899b3715167912be1be5d75ceec480a2d238caaf40c79e632ddf944557`
- **exact hash comparison result:** `PASS` (Hashes are identical)

## 6. Forensic Findings

### FIXED
- Overlapping active reservations logically mutating `Vehicle.status` statically. Replaced entirely with interval overlap computation dynamically reflecting in caches and UI.
- `DashboardGridCards` strictly clipping on small windows. Replaced with `FlowLayout` responsive wrappers.
- `__pycache__` artifacts manually cleaned to prevent Wine bundled contamination.
- SQLite test guards explicitly assert refusal of connecting to production.

### VERIFIED
- **Desktop/Backend consistency:** Cache parity 100% matched to explicit SQL overlaps calculation (Tested via `test_regression_01_dashboard_kpi_cache_equals_backend`).
- **Sync Logic:** Cross-window updates cascade correctly.
- **Maintenance Logic:** Future or active overlap computes effective state seamlessly without base table corruption.

### REMAINING RISK
- None identified that block a stable distribution of the standalone POS system.

### NOT VERIFIED
- Live login validation against production URL using real identities. (Prevented intentionally to preserve data sandbox bounds).
