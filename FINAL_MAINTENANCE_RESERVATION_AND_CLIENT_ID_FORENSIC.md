# FINAL — Maintenance/Reservation State + Client Identity (CIN Recto/Verso) Forensic

Date: 2026-08-29
Scope: `/home/ayman/car-rental-system` — backend (FastAPI/PostgreSQL), desktop
(PySide6/SQLite offline-first), sync, dashboard, i18n, Windows package.

---

## 1. Root cause of the maintenance/reservation contradiction

The system had **two opposite rules living in two layers**:

| Layer | File / symbol | Behaviour when a maintenance overlapped a reservation |
|---|---|---|
| PostgreSQL trigger | `backend/app/models/maintenance.py` → `trg_check_overlap_maint` (`check_reservation_maintenance_overlap()`) | **Rejected** the maintenance: `RAISE EXCEPTION 'Vehicle is reserved during this maintenance period'` |
| Maintenance API | `backend/app/api/v1/maintenance.py::create_maintenance` | **Rejected** with HTTP 409 whenever the vehicle had *any* `ACTIVE`/`RESERVED` reservation (not even date-scoped) |
| Sync ingest | `backend/app/services/sync_service.py::_process_maintenance_create` | set `vehicle.status='MAINTENANCE'`, then relied on the trigger → returned `conflict` |
| **Desktop create** | `desktop/app/ui/main_window.py::_create_maintenance_record` | **No overlap check at all** — wrote `LocalMaintenance(status='ACTIVE')`, emitted `data_refreshed`; the vehicle's *derived* effective status flipped to `MAINTENANCE` (`_load_vehicles_from_local`) but the reservation row was **never touched** |

The desktop is offline-first. A user creating maintenance from the desktop got:

* local `LocalMaintenance` ACTIVE → vehicle shows `MAINTENANCE` everywhere it is *derived*;
* the `LocalReservation` stays `RESERVED`/`ACTIVE` → the Reservations page keeps showing it as a live blocking reservation;
* on the next sync the backend **rejects** the maintenance (trigger / 409), so the maintenance never reaches PostgreSQL and the two stores never converge.

Net effect: a permanent contradiction (vehicle "in maintenance" + an active
reservation on the same dates) and a latent double-booking window.

**Canonical fix chosen (owner-approved): invert the rule. Maintenance wins.**

---

## 2. Exact files / functions changed

### Backend
| File | Change |
|---|---|
| `backend/app/models/reservation.py` | `+ cancellation_reason` column (`String(50)`, nullable) |
| `backend/app/models/client.py` | `+ identity_card_image_back`, `+ driving_license_image_back` (`Text`, nullable) |
| `backend/app/models/maintenance.py` | Cross-table DDL rewritten: **dropped** `trg_check_overlap_maint`; kept `trg_check_overlap_res` (a new reservation still cannot be booked onto a vehicle in maintenance) |
| `backend/app/repositories/rental_repository.py` | `+ cancel_overlapping_reservations(vehicle_id, m_start, m_end, reason="MAINTENANCE")` — canonical helper, `SELECT … FOR UPDATE` on PostgreSQL |
| `backend/app/api/v1/maintenance.py` | `create_maintenance`: removed the 409; after `flush()` + `vehicle.status='MAINTENANCE'`, calls the helper, writes one audit row per cancellation, single `commit()`; broadcasts `cancelled_reservation_ids` + one `RESERVATION_UPDATED` per cancellation. `update_maintenance`: same cancel when the ticket transitions into an active state |
| `backend/app/services/sync_service.py` | `_process_maintenance_create` / `_process_maintenance_update`: call the helper inside the existing `begin_nested()` savepoint; return `cancelled_reservation_ids`. `_process_reservation_update`: persist `cancellation_reason`. Client create/update/pull/bootstrap: carry the two `*_back` fields. Reservation pull/bootstrap: carry `cancellation_reason` |
| `backend/app/schemas/rental.py` | `RentalResponse.cancellation_reason` |
| `backend/app/schemas/client.py` | `*_back` on `ClientCreate` / `ClientUpdate` / `ClientResponse` |
| `backend/app/services/client_service.py`, `backend/app/api/v1/clients.py` | pass the two `*_back` fields through create + `_to_response`; `upload_client_image` reused unchanged for verso uploads |
| `backend/migrations/versions/g2b3c4d5e6f7_*.py` | new: column + trigger drop + data repair |
| `backend/migrations/versions/h3c4d5e6f7g8_*.py` | new: client `*_back` columns |

### Desktop
| File | Change |
|---|---|
| `desktop/app/models/reservation.py` | `+ cancellation_reason` |
| `desktop/app/models/client.py` | `+ identity_card_image_back`, `+ driving_license_image_back` |
| `desktop/app/database.py` | auto-migration `ADD COLUMN` for the three new SQLite columns (mirrors existing pattern) |
| `desktop/app/ui/main_window.py` | `_create_maintenance_record`: in the **same session/commit** as the `LocalMaintenance` insert, cancels overlapping `RESERVED`/`ACTIVE` local reservations (`reservations_overlap` canonical helper), sets `cancellation_reason='MAINTENANCE'`, enqueues a `reservation UPDATE` each, then **one** `data_refreshed` |
| `desktop/app/sync/engine.py` | apply `cancellation_reason` (reservations) + `*_back` (clients) from pull payloads |
| `desktop/app/sync/uploads.py` | `replace_marker_in_entities`: resolve pending-upload markers in the two client `*_back` columns |
| `desktop/app/ui/reservations/reservation_list.py` | new-client form gains CIN-verso + licence-verso pickers; `saved` dict + `LocalClient` + client CREATE payload + `register_pending_upload` carry the `*_back` markers; status badge shows the localized "Annulée à cause de maintenance" (label + tooltip) when `cancellation_reason == 'MAINTENANCE'` |
| `desktop/app/ui/clients/client_details.py` | `HoverableImageLabel` rescale hardened (re-entrancy guard, first-paint scaling); new **"Identité / CIN"** section — 2×2 grid, four `HoverableImageLabel` slots, centered by the layout, in an LTR sub-container so RTL never swaps recto/verso |
| `desktop/app/i18n/fr.json`, `ar.json` | `reservations.cancelled_due_to_maintenance`, `maintenance.reservation_cancelled_toast`, `clients.identity_section`, `clients.docs_{cin,license}_{recto,verso}` |

---

## 3. Canonical business rule (single definition)

> An **active** maintenance period (`status ∉ {CANCELLED, COMPLETED}`) that
> **overlaps** a reservation for the same vehicle **wins**. Every overlapping
> reservation whose status is `RESERVED` or `ACTIVE` is moved to `CANCELLED`
> with `cancellation_reason = 'MAINTENANCE'`. `COMPLETED` and already
> `CANCELLED` reservations are never touched. The reservation row is preserved
> for history/audit — never deleted, never hidden.

Overlap predicate (project canonical, reused — not reinvented):

```
maint.start < res.end  AND  maint.end > res.start          # half-open [start, end)
maint.end = COALESCE(expected_end_datetime, actual_end_datetime, start_datetime)
```

Boundary equality (`res.end == maint.start` or `res.start == maint.end`) is
**not** an overlap. Desktop uses `app/utils/datetime_utils.reservations_overlap`;
backend uses the same expression already present in
`RentalRepository.check_availability`.

---

## 4. Transaction sequence

### Backend `create_maintenance` (one DB transaction)
```
BEGIN
  INSERT maintenance ; flush (assigns id)
  UPDATE vehicle SET status='MAINTENANCE'
  SELECT reservations … WHERE status IN ('RESERVED','ACTIVE')
        AND start < maint_end AND end > maint_start  FOR UPDATE
  UPDATE those reservations SET status='CANCELLED',
        cancellation_reason='MAINTENANCE', version=version+1
  INSERT audit_log (one per cancelled reservation)
COMMIT
  → broadcast MAINTENANCE_CREATED { cancelled_reservation_ids: [...] }
  → broadcast RESERVATION_UPDATED  (one per cancelled reservation)
```
If any step raises, the whole transaction rolls back — the maintenance is not
persisted, the vehicle is not flagged, reservations stay untouched
(verified by `test_atomicity_maintenance_not_persisted_if_cancel_fails`).

### Sync ingest — same, inside the per-item `begin_nested()` savepoint.

### Desktop `_create_maintenance_record` (one SQLite transaction)
```
session.add(LocalMaintenance ACTIVE)
enqueue maintenance CREATE
for each overlapping RESERVED/ACTIVE LocalReservation:
    status='CANCELLED'; cancellation_reason='MAINTENANCE'; version+=1
    enqueue reservation UPDATE {status, cancellation_reason}
session.commit()          # single commit
EventBus.data_refreshed.emit()   # exactly once
```

---

## 5. Cancellation reason implementation

* **Machine value** `'MAINTENANCE'` in a dedicated column
  `reservations.cancellation_reason` (PG `String(50)` + SQLite). Never a free-text
  dump into `notes`.
* **Display text** lives only in i18n:
  * FR `reservations.cancelled_due_to_maintenance` → `"Annulée à cause de maintenance"`
  * AR → `"أُلغيت بسبب الصيانة"`
* Desktop Reservations badge renders the translated text + tooltip; the row stays
  visible with the `badge_danger` style (history preserved).
* Audit: one `audit_log` row per cancellation, `action='CANCELLED'`,
  `new_values={status, cancellation_reason, cause_maintenance_id}`.

---

## 6. Availability behaviour after the fix

| Oracle | During active maintenance | After maintenance COMPLETED |
|---|---|---|
| `RentalRepository.check_availability` | `(False, "MAINTENANCE")` | `(True, None)` |
| `create_rental` / `update_rental` | blocked (`vehicle.in_maintenance`) | allowed |
| Desktop `_refresh_available_vehicles` / pre-save guard | blocked | allowed |
| Vehicle effective status (`_load_vehicles_from_local`) | `MAINTENANCE` | `AVAILABLE` (unless SOLD/INACTIVE) |
| Dashboard `get_overview` | `maintenance += 1`; the maintenance-cancelled reservation is **not** in `reserved`/`active`/`reserved_rentals`/`active_rentals` | back to normal |

A reservation cancelled by maintenance no longer blocks anything (status
`CANCELLED` is excluded everywhere). Maintenance is the sole blocking condition.
`trg_check_overlap_res` still refuses a **new** reservation over an active
maintenance (defence in depth on the reservation side).

---

## 7. Double-booking prevention / concurrency

Paths that could produce `reservation + overlapping maintenance`:

1. **Desktop maintenance create** — previously unchecked → now cancels in the same commit.
2. **Backend maintenance API** — previously 409 → now cancels atomically.
3. **Sync ingest of a maintenance** — cancels inside the savepoint.
4. **Maintenance re-activation** (`SCHEDULED/COMPLETED/CANCELLED → ACTIVE`) — handled in `update_maintenance` and `_process_maintenance_update`.
5. **New reservation over maintenance** — still rejected by `trg_check_overlap_res` (PG) and the desktop local guard.

Concurrency: `cancel_overlapping_reservations` issues `SELECT … FOR UPDATE` on
PostgreSQL, so two maintenance writers for the same vehicle serialise on the
reservation rows. The reservation↔reservation `EXCLUDE` constraint
(`excl_reservations_no_overlap`) is unchanged and still the last line of defence
against overlapping reservations. The database remains authoritative — desktop
validation is a convenience, not the source of truth.

---

## 8. EventBus / realtime propagation

```
DB commit (desktop OR pulled server change)
   → EventBus.data_refreshed.emit()          # exactly one, from the mutation site
   → MainWindow._on_global_data_refreshed()  # central dispatch, per-view isolated
        ├─ _load_vehicles_from_local   (Vehicles)
        ├─ _refresh_dashboard          (Dashboard)
        ├─ _reservations.refresh_data  (Reservations)
        ├─ _maintenance.refresh_data   (Maintenance)
        └─ _clients_page.refresh_data  (Clients)
```
No new timers, no `refresh_data()` sprinkled around, no tab-switch or sync
dependency. Server-side, `create_maintenance` emits `MAINTENANCE_CREATED`
(now carrying `cancelled_reservation_ids`) + one `RESERVATION_UPDATED` per
cancellation; the desktop realtime client turns any event into a short-debounced
sync, and `process_pull` already streams the changed reservation rows (with
`cancellation_reason`) back.

---

## 9. Client identity image — root cause

`ClientDetailsDialog` packed two `HoverableImageLabel` thumbnails into the
identity **header row** (`info_layout`, a horizontal box shared with four text
columns). With `Expanding` size policy and no dedicated space, the thumbnails
were squeezed and off-centre. `HoverableImageLabel.setPixmap` also had a fragile
`hasattr(self, '_setting_pixmap')` guard that made the *first* `setPixmap`
path inconsistent.

Fix:
* `HoverableImageLabel`: explicit `self._rescaling` re-entrancy flag set in
  `__init__`; `setPixmap` always stores the full-res pixmap and renders a
  `KeepAspectRatio` + `SmoothTransformation` scaled copy sized to the label;
  `resizeEvent` re-scales. No manual width/height maths, never stretched.
* A dedicated **"Identité / CIN"** `QFrame` below the KPI row with a 2×2
  `QGridLayout` (equal column/row stretch) → the image is centred **by the
  layout**. The grid lives in an LTR sub-container so an RTL dialog never
  mirrors the recto/verso columns.

---

## 10. CIN recto/verso architecture

```
CLIENT (desktop form)                     PostgreSQL clients
  identity_card_image        (recto) ───►  identity_card_image
  identity_card_image_back   (verso) ───►  identity_card_image_back      (NEW)
  driving_license_image      (recto) ───►  driving_license_image
  driving_license_image_back (verso) ───►  driving_license_image_back    (NEW)
        │                                        │
        ├── POST /api/v1/clients/upload-image  (generic, reused for all 4)
        │      → "/static/uploads/clients/<uuid>.<ext>"
        │
        ▼
  SQLite clients (LocalClient)  ── same 4 columns
        │
        ▼
  Sync:  client CREATE/UPDATE payload · /sync/pull · /sync/bootstrap  ── all 4 fields
  Offline: register_pending_upload(entity_type='client') for the *_back markers;
           replace_marker_in_entities resolves markers in the client row +
           the queued client CREATE payload once the server confirms the upload.
```

* Legacy columns are the **recto**. `*_back` is nullable and defaults `NULL`.
* A client with only a historical front image keeps displaying it as the recto;
  the verso slot shows "Document non disponible" until a back scan is uploaded.
* Uploading a verso never touches the recto (`test_update_back_only_keeps_front`).

---

## 11. Database migrations

| Revision | Down-revision | Upgrade | Downgrade | Backward compatible? |
|---|---|---|---|---|
| `g2b3c4d5e6f7` | `f1a2b3c4d5e6` | `+ reservations.cancellation_reason` (nullable) · `DROP TRIGGER trg_check_overlap_maint` + rewrite `check_reservation_maintenance_overlap()` to guard only the reservation side (PG only) · **data repair**: cancel every `RESERVED`/`ACTIVE` reservation overlapping an `ACTIVE` maintenance, reason `MAINTENANCE`, `version+1` | drop column · recreate the original two-sided trigger (PG only). Data repair is one-way (documented in the file). | Yes — nullable column, no default; existing rows unaffected except genuine contradictions which are resolved |
| `h3c4d5e6f7g8` | `g2b3c4d5e6f7` | `+ clients.identity_card_image_back`, `+ clients.driving_license_image_back` (nullable Text) | drop both | Yes — additive only |

Single alembic head: `h3c4d5e6f7g8` (`alembic history` linear).
Migrations verified up **and** down on a throwaway SQLite DB seeded with a
contradiction + a boundary case:
* overlapping `RESERVED` → `CANCELLED` / `MAINTENANCE` / version bumped
* `COMPLETED` reservation → untouched
* reservation starting exactly at `maint.end` → **not** cancelled
* different vehicle → untouched
* client `*_back` columns added and dropped cleanly

> The pre-existing migration chain contains PostgreSQL-only DDL (`CREATE
> EXTENSION` in `001_foundation`), so the *full* chain runs on PostgreSQL only —
> unchanged by this work. On PostgreSQL, `alembic upgrade head` applies both new
> revisions with the trigger DDL guarded by `bind.dialect.name == "postgresql"`.

Desktop SQLite: `desktop/app/database.py` adds the three `ADD COLUMN` guards
alongside the existing ones; `LocalBase.metadata.create_all` covers fresh DBs.
**Production databases were not touched.**

---

## 12. API changes

| Endpoint | Change | Compatibility |
|---|---|---|
| `POST /api/v1/maintenance/` | No longer returns **409** on an overlapping reservation; returns **201** and atomically cancels the reservation(s). Response body (`MaintenanceResponse`) unchanged. | Callers that relied on the 409 to detect a conflict now get a success + a cancelled reservation (this is the intended product behaviour). |
| `PATCH /api/v1/maintenance/{id}` | Re-activating a ticket now cancels newly-overlapping reservations. | Additive |
| `GET/POST/PUT /api/v1/clients*` | `ClientResponse` / `ClientCreate` / `ClientUpdate` gain `identity_card_image_back`, `driving_license_image_back` (optional). | Additive — omitted ⇒ `null` |
| `GET /api/v1/…` rentals & `/sync/*` | `RentalResponse` / reservation sync payloads gain `cancellation_reason` (optional). | Additive |
| `/sync/push` (maintenance) | result dict gains `cancelled_reservation_ids: [str]`. | Additive |
| `POST /api/v1/clients/upload-image` | **Unchanged** — reused for verso uploads. | — |

---

## 13. Desktop changes

* Maintenance creation is now transactionally correct and reactive (§2, §4, §8).
* Reservations page surfaces the maintenance-cancellation reason (label + tooltip),
  row stays visible.
* New-client form (only client editor in the desktop) captures CIN recto+verso
  and licence recto+verso; offline pending-upload markers resolve for all four.
* `ClientDetailsDialog` has a dedicated, layout-centred, aspect-ratio-safe,
  resize-safe, RTL-safe identity section with four document slots.
* Local SQLite auto-migrates the three new columns on startup.

---

## 14. Tests added

### Backend — `backend/tests/` (14)
`test_maintenance_wins_reservation.py` (10): RESERVED→CANCELLED; ACTIVE→CANCELLED;
`cancellation_reason == "MAINTENANCE"` (machine value); COMPLETED & CANCELLED
untouched (version unchanged); **boundary equality → no cancel**; end-less
maintenance cancels nothing; `create_maintenance` API returns 201 (not 409) and
cancels + flags vehicle; availability `(False,"MAINTENANCE")` during / `(True,None)`
after `complete`; dashboard excludes the cancelled reservation; **atomicity** —
injected failure ⇒ no maintenance persisted, reservation intact, vehicle not
stuck; **sync push** maintenance CREATE cancels + returns `cancelled_reservation_ids`.

`test_client_back_images.py` (4): both sides persist distinctly; update verso
keeps recto; legacy front-only client serialises (`*_back` = `null`); `/sync`
bootstrap + pull carry all four image fields.

### Desktop — `desktop/tests/` (11)
`test_maintenance_wins_reservation_desktop.py` (5): overlapping maintenance
cancels RESERVED **and** ACTIVE (parametrised) with `cancellation_reason` +
one `maintenance CREATE` + one `reservation UPDATE` queued + **exactly one**
`data_refreshed`; boundary equality does not cancel; dashboard `reserved-1` /
`maintenance+1` + vehicle effective `MAINTENANCE`; finishing maintenance frees
the vehicle while the reservation stays `CANCELLED`.

`test_client_details_documents.py` (5): four document slots exist; landscape +
portrait pixmaps fit inside the label with aspect ratio preserved (<2% error)
and centre alignment; resize keeps aspect ratio (grow + shrink); missing verso
shows placeholder; RTL keeps recto→front-key mapping and an LTR grid host.

`test_full_reactivity_lifecycle.py` (1): the mandated end-to-end —
`AVAILABLE → reservation (RESERVED) → overlapping maintenance ⇒ MAINTENANCE +
reservation CANCELLED/MAINTENANCE + dashboard converge + availability false →
finish maintenance ⇒ AVAILABLE, reservation still CANCELLED → new reservation ⇒
succeeds, vehicle RESERVED` — all without tab switch / manual refresh / restart /
sync.

Existing suites adjusted: none required behavioural changes — no test asserted
the old "reject maintenance" path (`test_maintenance_creation_refresh.py`,
`test_maintenance_frees_vehicle.py`, `test_availability_maintenance.py`,
`test_double_booking.py` all still pass unchanged).

---

## 15. Full test counts

| Suite | Baseline | After | New | Result |
|---|---|---|---|---|
| Backend (`backend/`, SQLite in-memory) | 84 | **98** | +14 | **98 passed** |
| Desktop (`desktop/`, `QT_QPA_PLATFORM=offscreen`) | 134 | **145** | +11 | **145 passed** (267 s) |
| **Total** | 218 | **243** | **+25** | **243 passed, 0 failed** |

Import smoke: `python -c "import app.main"` (backend) OK;
`python -c "import app.ui.main_window, app.ui.clients.client_details, app.ui.reservations.reservation_list, app.sync.engine, app.sync.uploads"` (desktop) OK.

Migration smoke: `alembic upgrade head` + `alembic downgrade f1a2b3c4d5e6` on a
throwaway SQLite DB — clean, data repair + boundary case verified.

---

## 16. Build hash

Windows package rebuilt via `packaging/windows/build_windows.sh`
(wine 11.0 + bundled `venv_wine` Python 3.11.9, PyInstaller 6.22.2, PySide6 6.8.3):

```
Build SUCCESS: dist/ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe

sha256(ATELIER_BERLIN_LOCATION_CAR.exe)                = 451825f01993f78703dbbd0ce671a8e482b8c0ccffa0e22e3a92bce3a9e08d28
sha256(ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip)        = fa8156ae62c329fd30169cf064518d68bc87b107dbb30fa5a04f539a3bf97f78
sha256(find desktop/app -name '*.py' | sort | xargs)   = 39eaec2effb2b9209a4c65f49f723f3fa181ed1d179148fc74d154d7f759860b
```
exe size 9,099,757 B · zip size 61,861,001 B · built 2026-08-29 18:21.

---

## 17. Remaining risks

1. **End-less maintenance** (`expected_end_datetime` NULL) cancels nothing — by
   design, consistent with `check_availability`'s `COALESCE(…, start)`. The
   desktop `MaintenanceFormDialog` always sets `expected_end_datetime` (start+7d
   default), so this is not reachable from the UI. A ticket created via raw API
   with no end would flag the vehicle but not cancel — acceptable, documented.
2. **`trg_check_overlap_maint` removed** — direct SQL `INSERT INTO maintenances`
   no longer has a DB backstop. Enforcement is now the application layer
   (maintenance API + sync service), which is the correct altitude and the only
   path real clients use. `trg_check_overlap_res` still guards the reservation
   side.
3. **Full alembic chain is PostgreSQL-only** (pre-existing — `001_foundation`
   uses `CREATE EXTENSION`). The two new revisions are dialect-guarded and were
   verified on SQLite in isolation; on production PostgreSQL they must be run
   with `alembic upgrade head` during a maintenance window (the data-repair
   `UPDATE` is idempotent and cheap).
4. **Mobile (Flutter, `mobile/`)** consumes `/sync/bootstrap` + `/sync/pull`; the
   added fields are additive and optional. If the Flutter client model is
   strict-parsed it should add the optional fields — flagged as a follow-up, not
   a blocker (no breaking change to existing payload keys).
5. **Cross-store race**: desktop cancels locally *and* the server cancels on
   maintenance ingest; both converge to the same `CANCELLED`/`MAINTENANCE`
   state, and `_process_reservation_update` is version-guarded. Worst case is a
   redundant no-op UPDATE.
6. Pre-existing uncommitted work from earlier sessions (login retry, vehicle
   form, dashboard cache, api_client, etc.) is untouched and still present in the
   working tree — no `git reset`/`clean`/`checkout` was run.

---

## FINAL VERDICT

**PASS — MAINTENANCE/RESERVATION STATE IS CANONICAL AND LIVE.**

The complete lifecycle test (`desktop/tests/test_full_reactivity_lifecycle.py::test_full_lifecycle`)
passes: an overlapping maintenance immediately and atomically drives the vehicle
to `MAINTENANCE`, cancels the reservation with machine reason `MAINTENANCE`,
converges the dashboard and every view through a single `data_refreshed`, makes
the vehicle unavailable; finishing maintenance frees the vehicle while the
cancelled reservation remains cancelled; a new reservation for the freed slot
then succeeds — with no tab switch, manual refresh, restart, or sync dependency.
Two-sided CIN/licence documents persist end-to-end (create, update, sync,
offline cache, bootstrap) with legacy single-image clients fully compatible, and
the identity images are centred by the layout with aspect ratio preserved across
resize and RTL. Backend 98/98, desktop 145/145, Windows package rebuilt.
