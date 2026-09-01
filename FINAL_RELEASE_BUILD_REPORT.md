# FINAL RELEASE BUILD REPORT

Date: 2026-08-31 21:32 (Africa/Casablanca)
Purpose: rebuild the Android APK and the Windows desktop ZIP from the **current
verified working tree** — the previously shipped artifacts (2026-08-29) predate
Increments 1→6 / 6A and did **not** represent the codebase.

**No old APK or old EXE was reused, copied, renamed, or repackaged. Both binaries
were rebuilt from source with `--clean`.**

---

## 1. SOURCE STATE

| | |
|---|---|
| Git HEAD | `df9b96dfa56692845560d18995c5c83503f01140` — `fix: restore effective_status and async generation guard and test suite` |
| Branch | `main` |
| Reflog | HEAD@{0} == the commit above; **no reset / checkout / revert** in this session |
| Working tree | 127 changed paths: **61 modified**, **9 deleted**, **57 untracked** — the entire Increment 1→6 / 6A body of work, uncommitted by design (Increment 0 checkpoint remains the operator's call) |

### Increment content confirmed present in source (not just claimed)

| Increment | Evidence in working tree |
|---|---|
| 1 — canonical fleet-status spec | `shared/fleet_status_reference.py`, `backend/app/services/fleet_status.py`, `desktop/app/utils/fleet_status.py` |
| 2 — DomainStore | `desktop/app/state/domain_store.py` (new) |
| 3 — BoundaryClock | `desktop/app/state/boundary_clock.py` (new) |
| 4 — mobile temporal + midnight | `mobile/.../data/fleet/FleetStatus.kt`, `BoundaryTicker.kt` (new) |
| 5 — cross-client / sparse-cache | `applyAuthoritativeSnapshot`, `cache_snapshot_complete`, `synced_through_revision` in mobile source + APK dex |
| 6 — desktop L2/L3 | `entity_changed` removed from `event_bus.py` (grep: 0); 7 `store.mutate(` call sites across `main_window.py` (4) / `maintenance_list.py` (2) / `reservation_list.py` (1); `_render_from_snapshot` in both widgets |
| 6A — tz / maintenance-wins / recto-verso | `.astimezone(timezone.utc)` ×8 in `maintenance_list.py` + `reservation_list.py`; `cancellation_reason` in `backend/app/models/reservation.py` + `desktop/app/models/reservation.py`; migrations `f1a2b3c4d5e6 → g2b3c4d5e6f7 → h3c4d5e6f7g8`; i18n keys `cancelled_due_to_maintenance`, `docs_cin_verso`, `docs_license_verso` |

Old artifacts are **older than the source**:
`main_window.py` mtime `2026-08-31 21:16` ≫ old APK `2026-08-29 22:31` ≫ old ZIP `2026-08-29 19:17`.

---

## 2. TEST RESULTS  (run against the current tree, immediately before packaging)

| Suite | Command | Result |
|---|---|---|
| Backend | `backend/venv/bin/pytest -q` | **120 passed** (9.4 s) |
| Desktop | `PYTHONPATH=. desktop/venv/bin/pytest -q` | **215 passed** (244.8 s) |
| Mobile | `./gradlew --offline testDebugUnitTest` | **49 passed**, 0 failures, 0 errors |
| Migration head | `alembic heads` | **`h3c4d5e6f7g8` (single head)** |

Counts match the expected baseline exactly (backend 120 / desktop 215 / mobile 49).
No test was edited for this release.

### Increment 6A markers — intact
* timezone conversion uses `astimezone(timezone.utc)` (not `replace(tzinfo=…)`) — 8 occurrences.
* "maintenance wins" rule — `_create_maintenance_record` cancels overlapping reservations with `cancellation_reason='MAINTENANCE'` inside one `DomainStore.mutate()` transaction; backend `test_maintenance_wins_reservation` green.
* status-contradiction fix — future-dated maintenance does not flip raw `vehicle.status`; effective status derived from the schedule.
* whole-second exact-boundary test — `test_live_refresh.py::test_exact_boundary_allows_vehicle` present and green.
* client recto/verso document support — `identity_card_image_back` / `driving_license_image_back` columns (migration `h3c4d5e6f7g8`), backend `test_client_back_images` green, desktop i18n keys bundled in the EXE.

---

## 3. APK BUILD

```
cd mobile && ./gradlew --offline clean assembleDebug        →  BUILD SUCCESSFUL in 27s
   :app:compileDebugKotlin        EXECUTED  (not from cache — current source compiled)
   :app:dexBuilderDebug           EXECUTED
   :app:packageDebug              EXECUTED
```

| Field | Value |
|---|---|
| Path | `/home/ayman/car-rental-system/mobile/app/build/outputs/apk/debug/app-debug.apk` |
| Size | **23 341 649 bytes** (old: 23 325 206 — **+16 443**) |
| Modified | **2026-08-31 21:23:13 +0100** (this build) |
| SHA-256 | **`a4ec3bf35acac089a791c57ff8f4610fc60a54387395e5d2bfcc935db8ac2e5a`** |
| Structure | valid ZIP, 239 entries, 14 dex files |
| applicationId | `com.example` (matches `build.gradle.kts`) |
| versionCode / versionName | `1` / `1.0` |
| Application label | `ATELIER BERLIN LOCATION CAR` |
| compileSdk / targetSdk | 36 / 36 |

**Current-source proof** — strings compiled into `classes*.dex`:
`BoundaryTicker` ×10 · `FleetStatus` ×7 · `applyAuthoritativeSnapshot` ×7 ·
`cache_snapshot_complete` ×1 · `synced_through_revision` ×1 · `JwtUtils` ×4
(all Increment 4/5 / mobile-session-fix symbols — absent from the Aug-29 APK).

---

## 4. WINDOWS BUILD

Toolchain: **Wine 11.0** → `C:\Python311` (Windows CPython 3.11.9, 64-bit) →
**PyInstaller 6.22.2**, driven by the repo spec.

```
cd packaging/windows
rm -rf build dist
wine C:\Python311\python.exe -m PyInstaller --noconfirm --clean ATELIER_BERLIN_LOCATION_CAR.spec
   → 108778 INFO: Build complete!   (exit 0)
cd dist && zip -r ../../../ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip ATELIER_BERLIN_LOCATION_CAR/
```

*Build-env fix (not repo source):* `tzdata==2025.2` was missing from the Wine
`C:\Python311` site-packages; installed it (the spec already declares
`hiddenimports=[… 'tzdata']`, and `desktop/requirements.txt` flags it as
Windows-required for `ZoneInfo("Africa/Casablanca")`). No project file changed —
`git status` count is unchanged at 127; the two `M` packaging files
(`ATELIER_BERLIN_LOCATION_CAR.spec` `+'tzdata'`, `build_windows.sh` `+--hidden-import=tzdata`)
were already modified before this session and PyInstaller does not rewrite them.

| Field | New | Old (2026-08-29) |
|---|---|---|
| ZIP path | `/home/ayman/car-rental-system/ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip` | same |
| ZIP size | **61 898 808 bytes** | 61 862 733 (**+36 075**) |
| ZIP modified | **2026-08-31 21:31:42 +0100** | 2026-08-29 19:17 |
| ZIP SHA-256 | **`e51fb8e0ecb91c4eaefd3d1d2cfdc188ced36076bdd200f100178766ef0dd142`** | `99fec1835413597c2dcdb6119d4c58395b5dba4a4220d05b0ac27c9f4636e549` |
| Entries | **895 files** | 891 files |
| Inner EXE | `ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` | same name |
| EXE size | **9 124 879 bytes** | (Aug-29) |
| EXE modified | **2026-08-31 21:30** | 2026-08-29 |
| EXE SHA-256 | **`74cd3be734ff41a2bec89a99a53ce2c1da47b4c8d46a5d8e2ebb3871c9b80e5a`** | `3dc5f13425980439e0f6461a2abe3b148a123cb85f691477f17c8fd819ac7e3b` |

**Current-source proof** — PyInstaller `Analysis-00.toc` references the live
working-tree files, including modules that **did not exist** in the Aug-29 build:
```
'Z:\home\ayman\car-rental-system\desktop\app\state\domain_store.py'     (Increment 2 — new)
'Z:\home\ayman\car-rental-system\desktop\app\state\boundary_clock.py'   (Increment 3 — new)
'Z:\home\ayman\car-rental-system\desktop\app\ui\main_window.py'         (Increment 6 edits)
'Z:\home\ayman\car-rental-system\desktop\app\ui\reservations\reservation_list.py'
'Z:\home\ayman\car-rental-system\desktop\app\utils\fleet_status.py'
```
Bundled `_internal/app/i18n/fr.json` and `ar.json` SHA-256 **equal** the working
tree; bundled `ar.json` contains the 6A keys `cancelled_due_to_maintenance`,
`docs_cin_verso`, `docs_license_verso`.
`_internal/tzdata/zoneinfo/Africa/Casablanca` bundled (1919 bytes) — RTL Arabic,
Pistache theme (code-applied), branding logo, sync stack all present.

---

## 5. SHA-256 / ARTIFACT VERIFICATION

| Artifact | Old SHA-256 | New SHA-256 | Different? |
|---|---|---|---|
| APK | *(overwritten by clean build; old size 23 325 206 / 2026-08-29 22:31)* | `a4ec3bf35acac089a791c57ff8f4610fc60a54387395e5d2bfcc935db8ac2e5a` | ✅ size +16 443, ts +45.7 h, clean rebuild |
| Windows ZIP | `99fec18354135…4636e549` | `e51fb8e0ecb91…ef0dd142` | ✅ |
| EXE inside ZIP | `3dc5f13425980…19ac7e3b` | `74cd3be734ff4…c9b80e5a` | ✅ |

Both new artifacts sit at the **same paths** as the old ones (as requested); the
timestamp, size, SHA-256 and — for the ZIP — the analysed source-file set all
change, proving a genuine rebuild from the current tree.

Old ZIP preserved for audit at
`…/scratchpad/OLD_ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip` (not in the repo).

---

## 6. FINAL ARTIFACT PATHS

```
APK   : /home/ayman/car-rental-system/mobile/app/build/outputs/apk/debug/app-debug.apk
        23 341 649 bytes · 2026-08-31 21:23 · sha256 a4ec3bf35acac089a791c57ff8f4610fc60a54387395e5d2bfcc935db8ac2e5a

ZIP   : /home/ayman/car-rental-system/ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip
        61 898 808 bytes · 2026-08-31 21:31 · sha256 e51fb8e0ecb91c4eaefd3d1d2cfdc188ced36076bdd200f100178766ef0dd142
        └─ ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe
           9 124 879 bytes · 2026-08-31 21:30 · sha256 74cd3be734ff41a2bec89a99a53ce2c1da47b4c8d46a5d8e2ebb3871c9b80e5a
```

PyInstaller build result: **SUCCESS** (exit 0, "Build complete!").
Confirmation: **both artifacts rebuilt from the current working tree; no old
APK / EXE reused or repackaged.**

---

## 7. BUILD / RISK NOTES

1. **APK is a *debug* build** (`assembleDebug`) — same class as the Aug-29
   artifact. A signed **release** APK still cannot be produced here: the upload
   keystore `my-upload-key.jks` is a CI secret and `assembleRelease` fails. That
   is a CI step, unchanged by this release.
2. **Windows EXE built under Wine**, not native Windows. It ran clean through
   PyInstaller with zero "missing module" warnings and bundles `tzdata` +
   `Africa/Casablanca`. It has **not** been smoke-tested on a real Windows host
   from this environment — recommend a launch check on Windows before shipping.
3. `tzdata` was installed into the Wine build Python this session (it had been
   lost from that env); it is declared in the spec and in
   `desktop/requirements.txt`, so this only restored the intended state.
4. Server address unchanged: `https://car-rental-system.fly.dev` (desktop
   `config.py` default, mobile `build.gradle.kts` debug+release).
5. Repository left as-is — **nothing committed**, no source reverted, Increment
   6/6A intact, backend/mobile contracts intact, DomainStore architecture,
   Arabic RTL, Pistache branding, sync/status/maintenance behaviour all
   preserved.
