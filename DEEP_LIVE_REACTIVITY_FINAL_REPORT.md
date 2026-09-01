# DEEP LIVE REACTIVITY — FINAL REPORT

Project: `/home/ayman/car-rental-system`
Git HEAD: `df9b96dfa56692845560d18995c5c83503f01140` (branch `main`, worktree dirty — preserved)
Date: 2026-08-29

> Companion to `DEEP_LIVE_REACTIVITY_FORENSIC_REPORT.md` (root causes #1–#9 + §28 verification).
> This report adds the two newly-reported user bugs and their fixes.

---

## 1. Exact root causes (this round)

### BUG 1 — reservation creation shows "Serveur injoignable" when online

| | |
|---|---|
| **Files** | `desktop/app/services/api_client.py` (`_request`, `check_availability`); `desktop/app/ui/reservations/reservation_list.py` (`_create_reservation_record`) |
| **Reproduced** | Yes — a live `POST https://car-rental-system.fly.dev/api/v1/auth/login` **timed out (`httpx.ReadTimeout`)** on the first hit, then succeeded on retry. The fly.dev backend scales to zero and cold-starts in 10–30 s. |
| **Root cause** | `ApiClient.__init__(timeout=10.0)`. `_request` caught `ConnectError` **and** `TimeoutException` together, returned `None`, and did **not retry**. `_create_reservation_record` then hit `if avail_resp is None: … t("sync.server_unavailable"); return`. So a transient cold-start = permanent "Serveur injoignable" + blocked booking. |
| **Second defect** | Every non-200 (`401`, `403`, `409`, `422`, `5xx`, malformed) was collapsed into the **same** `sync.server_unavailable` message — a business/auth error shown as a transport error, violating "preserve the exact useful error category". |
| **Fix** | 1. `_request` now **separates** `TimeoutException` (retryable — retried up to N times with a 2.5× widened timeout) from `ConnectError` (real offline — not retried); it records `_last_transport_error`. 2. `check_availability` uses `retries=2` and returns `{"http_error": <cause>, "transport": True}` instead of a bare `None`. 3. `_create_reservation_record` classifies precisely: `200 available:false` / `409` → conflict message; `401` → session-expired; `403` → permission-denied; `400/422` → invalid-data; `404` → vehicle not synced → **fall through to the local overlap check** (offline-first); `5xx`/malformed → server-error; transport failure → server-unreachable. A genuine technical failure still **blocks** creation (never a silent create). |
| **New i18n** | `common.permission_denied`, `reservations.err_invalid_data`, `reservations.err_server_error` (fr + ar). |
| **Verified** | `desktop/tests/test_bug1_reservation_error_category.py` — 14 cases (11-way category matrix + 404-fallback-creates + 404-still-blocks-on-local-overlap + ApiClient-retries-timeout). Live re-check against production: warm server returns a clean `{"available": false, "reason": "RESERVATION"}` in 0.3 s → shows the conflict message, not "unreachable". |

### BUG 2 — editing a reserved vehicle and changing its "maintenance status" does nothing

| | |
|---|---|
| **Files** | `desktop/app/ui/vehicles/vehicle_form.py` (status combo) |
| **Root cause** | `VehicleFormDialog` offered `["AVAILABLE", "RENTED", "RESERVED", "MAINTENANCE"]` as raw `vehicle.status` column values. But per the canonical rule (Phase 4) `RENTED`/`RESERVED`/`MAINTENANCE` are **derived** from reservation & maintenance records. Setting the column: (a) after Forensic-Report RC#1, is correctly ignored by `_load_vehicles_from_local` → "nothing changes"; (b) before RC#1, produced a Vehicles-view-vs-Dashboard contradiction (list said MAINTENANCE, dashboard derived 0). No maintenance *record* was ever created, so the Maintenance page stayed empty. This is the "duplicate / contradictory source of truth" the brief calls out. |
| **Fix** | The form now offers **only structural** statuses: `["AVAILABLE", "SOLD", "INACTIVE"]`. A vehicle whose current column is a derived value collapses to `AVAILABLE` in the form; `SOLD`/`INACTIVE` are preserved. Sending a vehicle to maintenance is done through the **Maintenance module** (the "Maintenance" button already on every vehicle row), which creates a real ticket and propagates live. |
| **Verified** | `desktop/tests/test_bug2_vehicle_form_status.py` — 5 cases: combo offers exactly the 3 structural states; a `RESERVED` vehicle shows `AVAILABLE` in the form; a `SOLD` vehicle stays `SOLD`; `_save()` payload can never carry `MAINTENANCE`; and the **supported** maintenance flow updates Vehicles + Dashboard live with no tab switch / refresh / sync. |

---

## 2. Before / after propagation

**BUG 1**
```
BEFORE:  click Confirmer → check_availability → 10s timeout → None
         → "Serveur injoignable" → reservation NOT created (even though online)

AFTER:   click Confirmer → check_availability (retry, 10s→25s)
         ├─ 200 available            → create → commit → EventBus → all views
         ├─ 200 not available / 409  → "déjà réservé" (business message)
         ├─ 401                      → "Session expirée"
         ├─ 403                      → "permission"
         ├─ 400/422                  → "données invalides"
         ├─ 404 (vehicle not synced) → local overlap check → create if free
         ├─ 5xx / malformed          → "Erreur du serveur, réessayez"
         └─ transport (real)         → "Serveur injoignable"   (correct, blocks)
```

**BUG 2**
```
BEFORE:  Modifier véhicule → status = "MAINTENANCE" → commit → EventBus
         → _load_vehicles_from_local derives AVAILABLE (no ticket) → NO visible change
         → Maintenance page: still empty      → user sees a dead button

AFTER:   Modifier véhicule → status limited to AVAILABLE/SOLD/INACTIVE (no dead option)
         To put in maintenance: vehicle row → "Maintenance" → MaintenanceFormDialog
         → _create_maintenance_record → commit → EventBus → Vehicles=MAINTENANCE,
           Dashboard maintenance=1/available=0, Maintenance list shows the ticket — live
```

---

## 3. Every broken button found (this round)

| Button | Window | Was | Now |
|--------|--------|-----|-----|
| Confirmer (Nouvelle réservation) | Reservations | any server hiccup → "Serveur injoignable", booking blocked | retried; precise category; offline-first fallback on 404; only a real transport failure blocks |
| Confirmer (Modifier véhicule) with "MAINTENANCE"/"RESERVED"/"RENTED" selected | Vehicles | committed a meaningless column value → no visible effect anywhere | option removed; use the Maintenance module (which is live) |

No other dead buttons found (see §5).

---

## 4. Silent exceptions

`_create_reservation_record`'s `except Exception as e:` around the availability call previously only `logger.warning`-ed and then fell through — it could proceed to the local check on an unexpected error. Now it logs **and** shows `sync.server_unavailable` and returns (no ambiguous half-path). No other change to exception handling this round; the Forensic Report's RC#6 sweep already covered the mutation handlers.

---

## 5. Full audits (this round)

- **EventBus** — unchanged; still one main-thread singleton, one `data_refreshed` structural listener. `_create_reservation_record` still emits exactly once via `reservation_created` → `_on_reservation_updated`.
- **Cache** — no new cache. `check_availability` results are not cached.
- **Transactions** — reservation create is still one transaction (client + reservation + sync-queue), commit-before-event, rollback on failure. Unchanged.
- **Sync** — the 404 fallback path relies on the backend `excl_reservations_no_overlap` exclusion constraint + the existing desktop sync-conflict revert (`engine.py`, emits `data_refreshed`) as the safety net for a genuine offline race. Verified present.
- **Async/thread** — `_create_reservation_record` runs on the UI thread; `check_availability` is a synchronous `httpx` call with a bounded (now retried) timeout — acceptable for a modal confirm action, and it already showed a blocking dialog. No worker touches a widget.
- **Date/time** — `new_start.isoformat()` produces `+00:00`; the backend `datetime.fromisoformat` (Py 3.14) accepts it. Verified live: `check_availability` round-trips `2026-09-01T02:41:35+00:00` correctly. Half-open overlap unchanged.
- **i18n / RTL** — new keys added to **both** `fr.json` and `ar.json`; JSON validated; `set_language('ar')` → `is_rtl()` True and keys resolve.

---

## 6. Cross-window proof

`desktop/tests/test_cross_window_convergence.py` (all pages live, sync neutralised) — every mutation converges Vehicles + Dashboard with no tab switch / refresh / sync / restart:

create vehicle (1 event) · edit vehicle · delete vehicle · create maintenance · finish maintenance · cancel maintenance · create reservation (active) · cancel reservation · complete reservation — **PASS**.

`test_bug2_vehicle_form_status.py::test_maintenance_module_flow_updates_all_views_live` — the maintenance-from-vehicle path: Vehicles → `MAINTENANCE`, Dashboard → `maintenance=1, available=0`, live — **PASS**.

---

## 7. Tests and results (actual execution)

| Suite | tests | failures | errors | skipped | exit |
|-------|------:|---------:|-------:|--------:|:----:|
| desktop (`desktop/venv/bin/python -m pytest tests/`) | **134** | 0 | 0 | 0 | 0 |
| backend (`backend/venv/bin/python -m pytest`) | **84** | 0 | 0 | 0 | 0 |
| **total** | **218** | **0** | **0** | **0** | — |

New this round: `test_bug1_reservation_error_category.py` (14), `test_bug2_vehicle_form_status.py` (5).
Updated to the new "preserve error category" contract (not weakened — the core invariants "never a conflict message for a technical error" and "never a silent create" are kept): `test_forensic_matrix.py::test_technical_errors_never_report_conflict`, `test_false_conflict_regression.py::test_E_api_http_500`.

Prior rounds' suites (`test_status_derivation_regression`, `test_cross_window_convergence`, `test_global_dispatch_isolation`, `test_mutation_failure_no_false_event`, `test_maintenance_frees_vehicle`) — all still green.

---

## 8. Release artifacts (rebuilt from current worktree)

| Artifact | Path | SHA256 | Size |
|----------|------|--------|------|
| EXE | `packaging/windows/dist/ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` | `f4011a9d2cec87f9adac75aa0b01db6a275000914d4719297f4ce403d95b97d8` | 9,096,618 |
| ZIP | `ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip` (clean rebuild — old deleted first) | `9dac4d8f087cf442fc754961945e8ed564d8ff1974e1d2e342fd5d104ac71aa6` | 61,855,122 |

- **ZIP EXE hash == dist EXE hash** (`f4011a9d…`) — PASS (extracted + re-hashed).
- Build: PyInstaller 6.22.2, Windows CPython 3.11.9 (AMD64), via wine, from HEAD `df9b96d` + this session's changes.
- Package scan: `fr.json` + `ar.json` bundled; `shared/` bundled; `tzdata` bundled (fixes the dashboard `ZoneInfo` crash). **No secrets** — only `certifi/cacert.pem` (public CA bundle) matches `-----BEGIN`; no `.env`, `.db`, `JWT_SECRET`, `DATABASE_URL`, or credentials.
- Not smoke-run this round (identical launch path to the previous build, which was verified: DB init, login, WebSocket, sync/pull 200, no ZoneInfo crash).

---

## 9. Remaining risks

1. **Backend not deployed** — Forensic-Report RC#2/#3/#4 (maintenance frees vehicle; complete/advance HTTP 500; `check_availability` structural-only guard) are server-side. The running `car_rental_api_prod` still has the old code. Production DB confirmed to hold at least one vehicle stuck at `status=MAINTENANCE`.
2. **Migration `f1a2b3c4d5e6` not applied to production** — verified safe on a throwaway PG16 clone (single head; full chain applies; repairs only stale rows). Not run on prod by design.
3. **`check_availability` is a blocking call on the UI thread** — bounded (now 10 s → one 25 s retry = ~35 s worst case) and it shows a modal dialog, but a cold server can still make "Confirmer" feel slow. A future improvement: move it to a `QThread` with a "Vérification…" state on the button.
4. **404-fallback trust boundary** — if a vehicle genuinely isn't on the server and two desktops both create overlapping reservations offline, the second one is caught only at sync time (backend exclusion constraint → desktop revert + user notice). This is the accepted offline-first trade-off.
5. **EXE built under wine**, not native Windows — recommend a confirmation run on real Windows.
6. **Mobile app** not audited.

---

## 10. NOT VERIFIED

- Native-Windows execution of the new EXE (built + hash-verified under wine only).
- Production behaviour of BUG 1's fix end-to-end (backend availability endpoint + desktop) — verified against the **live** API read-only; not with an actual reservation write to production.
- Load/concurrency behaviour of the retry under many simultaneous cold-start requests.
