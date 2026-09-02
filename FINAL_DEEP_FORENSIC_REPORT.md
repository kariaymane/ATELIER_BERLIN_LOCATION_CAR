# FINAL DEEP FORENSIC REPORT — ATELIER BERLIN LOCATION CAR

**Date:** 2026-09-02
**Branch:** `forensic/one-system-2026-09-02`  →  merged to `main`
**HEAD:** `b755112` (see §18)
**Companion:** `FORENSIC_ROOT_CAUSE_ANALYSIS.md` (the read-only audit; this report is the fix + verification record)

---

## 1. Executive summary

The recurring failures were **not** independent bugs. Five structural causes made every fix temporary (see `FORENSIC_ROOT_CAUSE_ANALYSIS.md §1`):

1. **Parallel implementations** — revenue existed 3×, effective-status 3×, desktop login 2× (the live one being the *worse* one). A fix landed in one copy; the others kept the bug.
2. **CI ran on SQLite, prod on PostgreSQL** — the aware/naive-datetime 500s were structurally invisible to the test suite.
3. **No binary ↔ commit binding** — "the bug came back" was often an old EXE/APK.
4. **Branch never merged** — real fixes lived on an unpushed branch; `main` never saw them.
5. **Caches silently became truth** — stale offline data was indistinguishable from live data.

**This pass removes the architectural cause for LOGIN and REVENUE** and puts guards in place so they cannot silently regress:

| Concern | Before | After |
|---|---|---|
| Desktop auth | 2 impls; live one = 4 s timeout, no retry, every failure = "identifiants incorrects" | **1 `AuthClient`** — 30 s read timeout + 2 retries (cold-start proof), **typed outcomes** → one message per real cause |
| Cold start | `min_machines_running = 0` → 3–15 s cold start on every idle wake | `min_machines_running = 1` + launch-time `/health` warmup ping |
| Revenue engine | 3 hand-synced impls, no spec | **1 normative spec** (`shared/revenue_reference.py`) + backend/desktop/mobile all parity-tested against `shared/revenue_cases.json` |
| Revenue rule | recognition-at-start (whole price on day 1) | **pro-rata by day** (business decision 2026-09-02) — realised days only |
| Date filter | 4 fixed periods, client indexes a precomputed dict; no custom range | **8 presets + Personnalisé (Du/Au)**, `GET /dashboard/revenue?from=&to=`, always canonical, empty ≠ zero |
| Date display | mixed `%Y-%m-%d` / ISO | **DD/MM/YYYY** everywhere in the new widget; ISO on the wire |
| Timezone | `ZoneInfo('Africa/Casablanca')` copy-pasted in ~6 files | `shared.money_time.BUSINESS_TZ` / `now_business()` + a lint test that fails the build on a bare `datetime.now()` |
| CI | SQLite only | **+ a second full run against real `postgres:16`** |

**Verified green:** backend **175**, desktop **258**, mobile **67** — 0 failures.

**Not done in this pass (see §21):** mobile custom-range UI (engine + endpoint ready, screen unchanged — the 4 revenue cards are now pro-rata); full mobile-responsiveness rebuild; desktop resize/RTL sweep; API-envelope normalisation. These need the device loop and are scoped as follow-ups.

---

## 2. Original symptoms → disposition

| # | Symptom | Disposition |
|---|---|---|
| 1 | Login fails repeatedly | **Fixed** — §5. Backend auth was always correct; the desktop client was the fault. |
| 2 | Chiffre d'affaires wrong / stuck | **Fixed** — §6. One engine, range-native endpoint, empty ≠ zero. |
| 3 | Revenue date filter wrong | **Fixed** — §6. 8 presets + custom Du/Au, ISO on the wire, DD/MM/YYYY shown. |
| 4 | Desktop ↔ mobile contradict | **Fixed for revenue + C1**; other contradiction classes already closed in Increments 1–6, re-confirmed. |
| 5 | Mobile UI not responsive | **Deferred** (§21) — needs the emulator/device loop. |
| 6 | Data not guaranteed live | Live-sync architecture confirmed working (prior increments); warm machine keeps the event broadcaster continuously up. |
| 7 | Previous fixes keep needing redo | **Root cause removed** — §1; normative specs + parity tests + Postgres CI + naive-now guard + merge-to-main. |

---

## 3. Root causes → permanent fixes (the table)

| AREA | SYMPTOM | ROOT CAUSE | PERMANENT FIX | TEST | RESULT |
|------|---------|------------|---------------|------|--------|
| LOGIN | fails / "identifiants incorrects" for everything | live path `LoginWorker._authenticate_online` = raw httpx, 4 s, no retry; robust `ApiClient.login` was dead code; Fly machine scale-to-zero → cold start > 4 s | ONE `desktop/app/services/auth_client.py`; delete the raw path; 5 s connect / 30 s read / 2 retries; typed `AuthOutcome`; `fly.toml min_machines_running=1` + warmup ping | `desktop/tests/test_auth_client.py` (10) | PASS |
| LOGIN UX | can't tell network from bad password | one error string | `AuthOutcome` → `login.err_{invalid_credentials,account_locked,rate_limited,network,server,config}` (fr+ar); mobile taxonomy split | `test_auth_client.py`, `AuthRepositoryTest` | PASS |
| REVENUE | 3 impls drift; wrong numbers | no normative spec | `shared/revenue_reference.py` + `shared/revenue_cases.json`; backend/desktop/mobile call/port it | `test_revenue_crossruntime.py` (be), `test_dashboard_cache_parity.py` (dt), `RevenueEngineParityTest` (mo) | PASS |
| REVENUE | whole price booked on day 1 | recognition-at-start rule | **pro-rata by day** — `total_price/num_days` per realised day; spanning rentals split; `now`-gated | `test_revenue_consistency.py` (7) | PASS |
| DATE FILTER | no custom range; failed fetch shows 0 | client indexes `/dashboard/stats` dict | `GET /api/v1/dashboard/revenue?from=&to=` + `/dashboard/period/{name}`; widget always queries; empty→"Données indisponibles" | `test_revenue_consistency::*agree*`, `test_desktop_dashboard` | PASS |
| DATE FORMAT | ambiguous | no display contract | `shared.money_time.fmt_display_date` = DD/MM/YYYY; `QDateEdit` `dd/MM/yyyy`; ISO to API | `test_money_time.py` | PASS |
| TIMEZONE | naive vs aware 500s | `datetime.now()` scattered | `BUSINESS_TZ`/`now_business()`; lint test on guarded modules | `test_no_naive_now.py` (6) | PASS |
| DESKTOP/MOBILE | "Maintenances actives" = 0 vs fleet = 2 (C1) | `DashboardFetcher` cherry-picked keys, dropped `year_*`, alias mismatch | pass whole payload through; read `active_maintenance_tickets` w/ fallback | `test_desktop_dashboard::*maintenance*` | PASS |
| LIVE DATA | dashboard stuck at 0 after outage | 5 s fetch timeout on cold machine; `{}` overview → all-zero | fetch timeout → (5 s, 25 s); empty ≠ zero rendering; warm machine | covered by dashboard tests + `test_no_naive_now` | PASS |
| CI | prod path never tested | SQLite-only CI | `.github/workflows/backend.yml` `test-postgres` job (real `postgres:16`) | CI (runs on push) | CONFIGURED |
| ANDROID RESPONSIVE | broken | fixed dp, no `WindowSizeClass` | **deferred** — reviewed plan in §11 | — | DEFERRED |

---

## 4. LOGIN architecture (after)

```
LoginWindow  ──opens──▶ WarmupWorker ──GET /health──▶ (Fly machine starts warming)
     │
   type + submit
     │
LoginWorker ──▶ AuthClient(API_BASE_URL).login(email, pw)
                   │  httpx  connect 5s / read 30s / 2 retries (backoff)
                   ▼
              AuthResult(outcome, data)
        ┌──────────┴───────────────────────────────┐
     SUCCESS                              is_server_side_rejection?
        │                                  yes │           no │
   cache Argon2 hash                    show    │      try _authenticate_offline
   emit succeeded                    login.err_*│        │ ok → succeeded(offline=True, read-only badge)
                                                │        │ no → show login.err_network / err_server
```
`AuthClient` is the ONLY symbol allowed to call `/api/v1/auth/*` on the desktop.
`ApiClient._do_refresh` / `ApiClient.login` delegate to it (single refresh path).
Mobile already had a sound single client (`TokenAuthenticator` + `AuthRepository`); the phantom `user` DTO field was removed and the error taxonomy split.

**Canonical contract** (unchanged, now consumed identically):
`POST /api/v1/auth/login {email,password[,device_id]}` → `{access_token, refresh_token, token_type, expires_in:900, user_id, role, full_name}`; `401` typed detail; `429` rate limit 10/min.

---

## 5. REVENUE architecture (after)

```
                       shared/revenue_reference.py   ← NORMATIVE (pure, pro-rata by day)
                       shared/revenue_cases.json     ← 7 cases / 24 queries + 11 period vectors
                              ▲            ▲            ▲
        backend               │            │            │              mobile
  revenue_service.revenue_between   desktop dashboard_cache      RevenueEngine.kt
  (loads rows, delegates ALL math   .revenue_between_rows        (Kotlin port)
   to the shared reference)         (desktop port)
        │                                  │                          │
  /dashboard/stats  (today/week/month/year)                    FleetStatus.dashboardOverview
  /dashboard/revenue?from=&to=   ← range-native, `to` inclusive       (4 pro-rata cards)
  /dashboard/period/{name}       ← 8 presets
```

**Rule (pinned):** a rental of `num_days` days from instant `S` is day-slices `day_i = [S+i·24h, S+(i+1)·24h)`; `day_i` is booked against calendar date `date(S)+i` and earns `total_price/num_days`; `day_i` is *realised* once `now ≥ S+i·24h`. Period `[from,to)` revenue = Σ over non-CANCELLED reservations of (per-day rate × realised days whose date ∈ `[from,to)`). Summing one rental over all time == its stored `total_price`.

**Desktop widget:** compact panel — `[Période ▾]` (Aujourd'hui · Hier · Cette semaine · Semaine dernière · Ce mois · Mois précédent · Cette année · Année dernière · Personnalisé) → Personnalisé reveals `Du [dd/MM/yyyy] Au [dd/MM/yyyy]` → every change calls the canonical endpoint (offline: the same pro-rata rule over the `DomainStore` snapshot) → `CA <montant> DH`, `Du … au …`, `Mis à jour à HH:MM:SS`, `[Actualiser]`. No oversized button. `HTTP error / no data` → "Données indisponibles" (never a fake `0,00 DH`).

---

## 6. Date/time architecture

`shared/money_time.py` — the ONE contract:
- `BUSINESS_TIMEZONE = Africa/Casablanca`, `now_business()` (only sanctioned clock), `to_business()`, `business_date()`.
- `period_bounds(name, now)` for the 8 presets; `custom_bounds(from, to_inclusive)` (UI 'Au' inclusive → exclusive).
- `fmt_display_date` = **DD/MM/YYYY**; `parse_iso_date` = strict `YYYY-MM-DD`.
- Half-open `[start, end)` everywhere; week starts Monday.
- `test_no_naive_now.py` fails the build if a bare `datetime.now()` / `datetime.utcnow()` reappears in `revenue_service`, `dashboard_service`, `rental_repository`, `fleet_status`, `auth_service`.

---

## 7. Source-of-truth & 8. sync architecture

Unchanged and confirmed working (Increments 1–6, `MASTER_100_PERCENT_LIVE_ARCHITECTURE_REPORT.md`):
`PostgreSQL → FastAPI (canonical business logic) → WS domain events → clients invalidate + refetch → reactive UI`; SQLite/Room are **mirrors**. Warm machine (`min_machines_running=1`) keeps the in-process `EventBroadcaster` continuously available (a config test / documented invariant: keep it ≤ 1 machine or move to Redis pub/sub).

---

## 9. Cache policy

Revenue/dashboard: online → always the canonical endpoint; offline → the *same* pro-rata rule over the snapshot, rendered with an explicit "Hors-ligne — HH:MM:SS" stamp. `HTTP error ≠ 0`. (The >10-min stale-badge from `FORENSIC_ROOT_CAUSE_ANALYSIS.md §12` is a P1 follow-up.)

---

## 10. Desktop/mobile consistency

- **Revenue**: byte-for-byte identical rule across all three runtimes (parity tests).
- **C1** (maintenance card): fixed — reads the canonical key with fallback; test asserts operational card == fleet card == `/dashboard/stats.maintenance`.
- **Effective vehicle status** (raw `status` vs `effective_status`): already normalised in prior increments; both fields are sent by the API and the widgets render from `effective_status`.

---

## 11. Mobile responsiveness — reviewed plan (deferred)

Not started (needs the Android toolchain + emulator matrix). Scope for the follow-up:
screen-by-screen pass (Dashboard, Vehicles + detail, Reservations + detail, Maintenance, Notifications, all forms/dialogs/date-pickers) for fixed `.dp`, `Row` without `weight`/scroll, dialog overflow, IME overlap, font-scale ≥ 1.3, landscape, Arabic RTL. Fix with adaptive layout + `WindowSizeClass` + `LazyColumn/LazyRow/FlowRow` + `fillMaxWidth`/`weight` + `Modifier.imePadding()` + a typography/spacing scale — **not** shrink-to-fit.

## 12. Desktop responsiveness

The dashboard already uses a wrapping `FlowLayout` + `QScrollArea`; the new revenue panel is a plain `QVBoxLayout` (no fixed widths). A full resize/RTL sweep (1024×720 … 1920×1080, long AR strings, large revenue values) is a P1 follow-up.

## 13. API contract

- `LoginResponse`: mobile DTO's phantom `user` object removed; `expires_in` added. Backend contract unchanged (no 4th place to drift).
- New: `GET /api/v1/dashboard/revenue?from=&to=` (ISO dates, `to` inclusive) and `GET /api/v1/dashboard/period/{name}`.
- Deferred (P1): the triple image field (`image_url`/`image_urls`/`images`), the mixed `+01:00` vs `Z` datetime rendering, the two pagination envelope shapes.

## 14. Database integrity

- Reservation datetimes confirmed `TIMESTAMP(timezone=True)` — aware round-trips on Postgres.
- `test-postgres` CI job now exercises the `tstzrange` GIST exclusion constraints and NUMERIC summation that SQLite can't.
- Auth counter-bump-on-failed-login (a write in the login read path) and failed-transaction poisoning remain flagged for a P1 hardening pass.
- `scripts/purge_forensic_probes.sql` — dry-run-by-default cleanup of prod probe rows (§17 of the audit). **Not executed in this pass.**

## 15. Tests

| Suite | Before | After | New / changed |
|---|---|---|---|
| backend | 145 | **175** | `test_revenue_crossruntime`, `test_money_time`, `test_no_naive_now`, `test_revenue_consistency` rewritten (pro-rata) |
| desktop | 229 | **258** | `test_auth_client` (10), `test_dashboard_cache_parity` rewritten (vector-driven), `test_desktop_dashboard` rewritten, `test_domain_store_temporal` updated |
| mobile | 65 | **67** | `RevenueEngineParityTest` (revenue + period-bounds vectors) |

No test was deleted or weakened; the revenue tests that asserted recognition-at-start values were **rewritten to assert the new pro-rata semantics with more cases**, per the business-rule change.

## 16. E2E verification

- Backend: full suite green against ASGI transport incl. the new endpoints; `/dashboard/stats` internally consistent with `/dashboard/daily|weekly|monthly|yearly` and `/dashboard/revenue` (pinned by `test_stats_and_period_endpoint_and_custom_range_all_agree`).
- Desktop: `test_e2e_startup` (full QApplication login → MainWindow → navigation) green; `test_dashboard_cache_parity` proves desktop == shared spec.
- Mobile: `RevenueEngineParityTest` proves mobile == shared spec == backend.
- Cross-device live E2E on a real 4-process rig (2 desktop + phone + backend): **not runnable in this environment** — every mechanism is proven per-runtime + on the shared fixture (carried limitation, `FORENSIC_ROOT_CAUSE_ANALYSIS.md` "Environment limits").

## 17. Build verification

- Backend: deployed to Fly (see §18) — `alembic upgrade head` (no new migrations), `/health/ready` re-checked.
- Mobile APK: `./gradlew :app:testDebugUnitTest` green (67); a fresh signed APK must be built from the merge commit via `.github/workflows/android-release.yml` (tag push) — that CI job is the only sanctioned APK source.
- Windows EXE: `packaging/windows/build_windows.sh` — not executed in this environment; must be rebuilt from the merge commit.

## 18. Git SHA

- Work branch `forensic/one-system-2026-09-02` @ **`b755112`** (+ this report).
- Merged to `main` and pushed.
- Commits: `ca77fb0` (revenue engine + endpoint), `b84ffe6` (desktop AuthClient + fly warm + desktop revenue engine), `44b4a2a` (desktop widget + mobile engine + Postgres CI), `b755112` (time-contract guard + purge script), + docs.

## 19. APK SHA256

**Pending** — build from the merge commit via CI (`android-release.yml`). Record `git SHA · APK path · size · SHA256` in `RELEASE_MANIFEST.md`.

## 20. EXE SHA256

**Pending** — build from the merge commit (`packaging/windows/build_windows.sh`). Record in `RELEASE_MANIFEST.md`.

## 21. Remaining risks / follow-ups

| Priority | Item |
|---|---|
| P1 | Mobile custom-range revenue UI (engine + endpoint ready; screen still shows only the 4 pro-rata cards) |
| P1 | Mobile responsiveness rebuild (§11) — needs device loop |
| P1 | Desktop resize + Arabic-RTL sweep (§12) |
| P1 | Dashboard >10-min stale badge + one refresh path per client + WS-event→invalidation audit |
| P1 | API normalisation: single image field, single datetime rendering, one pagination envelope |
| P1 | Auth: move the failed-login counter bump off the credential-verdict path; explicit failed-transaction-poisoning test |
| P2 | Run `scripts/purge_forensic_probes.sql` against prod (dry-run first) |
| P2 | `RELEASE_MANIFEST.md` automation: embed `git rev-parse HEAD` in app `--version`; artifacts to `dist/<sha>/`; delete the 10 stray `ATELIER_..._WINDOWS*` dirs |
| P2 | Fully retire the desktop `data_refreshed` pulse; migrate `_create_reservation_record` to `store.mutate()` |

## 22–24. Release gate

| Gate | Status |
|---|---|
| Login works / uses prod backend / no hardcoded auth / desktop+mobile same system | ✅ |
| PostgreSQL authoritative / revenue calculated centrally | ✅ |
| Date filter works / DD/MM/YYYY shown / ISO on API / timezone canonical / boundaries tested | ✅ |
| Desktop revenue == backend == mobile (pro-rata) | ✅ (parity tests) |
| Desktop data == backend / Android data == backend | ✅ for revenue + C1; other entities per prior increments |
| No duplicated business calculations | ✅ for revenue/auth/period-bounds (spec-bound); effective-status already spec-bound |
| Existing tests pass / new regression tests pass / E2E passes | ✅ backend 175 · desktop 258 · mobile 67 |
| Android responsive / Desktop responsive / Arabic RTL | ⚠️ deferred (§11, §12) |
| APK ↔ HEAD / EXE ↔ HEAD | ⚠️ pending rebuild from merge commit (§19, §20) |
| `FINAL_DEEP_FORENSIC_REPORT.md` exists | ✅ (this file) |

**Verdict:** the LOGIN and REVENUE/DATE architectural root causes are removed and guarded against regression. The remaining gate items (mobile/desktop responsiveness, signed-artifact rebuild) require the device/build loop and are scoped above.
