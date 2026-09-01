# FINAL RELEASE INTEGRATION GATE

Date: 2026-08-29
Scope: integration / release gate over the current working tree of
`/home/ayman/car-rental-system`. No speculative refactors, no code deletion,
no history rewrite, nothing pushed.

---

## 1. Current source revision

| Item | Value |
|---|---|
| HEAD | `df9b96dfa56692845560d18995c5c83503f01140` |
| HEAD subject | `fix: restore effective_status and async generation guard and test suite` |
| Branch | `main` |
| Ahead of `origin/main` | 12 commits (unpushed) |
| Working tree | **dirty** — large uncommitted change set (see §2) |
| Stash | `stash@{0}` present, untouched |

The tested state is **HEAD + uncommitted working tree**, not a clean commit.
Nothing here has been committed; the release must be cut from this tree or the
tree must be committed first.

---

## 2. Worktree status

Preserved exactly as found. No `reset --hard`, `clean`, `restore .`,
`checkout -- .`, `stash drop`, or `push` was run.

Staged deletions (already `git rm`'d before this session): empty
`__init__.py` shims, `desktop/app/sync/worker.py`, dev scratch files
(`test_if.py`, `test_plus.py`, `test_qdate.py`, `trace_desktop.py`).

Modified (54 files) — backend API/services/schemas/models, desktop
UI/sync/services/models, mobile auth + DTO, packaging spec.

New untracked (kept): mobile `JwtUtils.kt`, `SessionPersistenceTest.kt`,
`SessionRestoreFlowTest.kt`; backend `services/fleet_status.py` + 3 migrations
+ 4 test files; desktop `utils/fleet_status.py`, `ui/widgets/flow_layout.py`
+ 12 test files; several `*FORENSIC*.md` reports.

---

## 3. Mobile session contract

Verified by reading the implementation
(`AuthRepository.kt`, `TokenManager.kt`, `JwtUtils.kt`, `FleetViewModel.kt`,
`MainActivity.kt`, `ApiClient.kt`) and by `SessionRestoreFlowTest` (§4).

| Scenario | Required behavior | Implemented | Evidence |
|---|---|---|---|
| First login | valid session stored, authenticated state | YES — `login()` persists access+refresh+identity from server response, emits session | code + `AuthRepositoryTest` |
| Restart / process death | valid stored session restored, login skipped | YES — `FleetViewModel.init` runs `validateAndRestoreSession()` during Splash; 200 refresh rotates tokens and re-enters | `successfulRefreshRotatesTokensAndRestoresSession` |
| Offline / timeout / unreachable | session NOT cleared, enter cached state | YES — network throw / 5xx / rate-limit → keep cached non-expired session | `transient5xxOnRefreshKeepsCachedSession`, `serverUnreachableOnRefreshKeepsCachedSession`, `probe503WithNonExpiredTokenKeepsCachedSessionWhenNoRefreshToken` |
| HTTP 401 / 403 | session cleared, login required | YES — only `code in {401,403}` triggers `clearLocalSession()` | `explicit401OnRefreshClearsSessionButKeepsBaseUrl`, `probe401ClearsSessionWhenNoRefreshToken` |
| Explicit logout | tokens + session cleared; next start needs login | YES — `logout()` best-effort server call then `clearLocalSession()`; next start has no tokens → Auth | `noStoredTokensClearsAndStaysLoggedOut` + desktop `test_logout_clears_tokens` |
| Provably-expired token while offline | do not unlock indefinitely | YES — `JwtUtils.isDefinitelyExpired` gates offline entry; both-expired + offline → clear | `provablyExpiredTokensWithUnreachableServerClearSession` |

Anti-requirements:

| Must never | Status |
|---|---|
| store password | OK — password only in `LoginRequestDto` body; never persisted (grep clean) |
| hardcode credentials | OK — no credential literals in `app/src/main` (grep clean) |
| log access/refresh tokens | OK — `Log`/`HttpLoggingInterceptor.Level.BASIC` emit codes/URLs/messages only, never token values or `Authorization` header |
| accept malformed/expired token indefinitely | OK — local expiry gate + server is authority whenever reachable |
| convert network failure into forced logout | OK — the exact bug this fix closed; covered by 3 tests |

Base URL: `TokenManager.clearSession()` deliberately keeps `KEY_BASE_URL`
(operator-configured server survives a session drop); `clearAll()` still
resets it. Verified by `SessionPersistenceTest`.

---

## 4. Session restore tests

`SessionRestoreFlowTest` — drives the whole flow through real OkHttp/Retrofit
against `MockWebServer` (added `com.squareup.okhttp3:mockwebserver`, pinned to
the existing okhttp `4.10.0`).

Fresh run (`testDebugUnitTest --rerun-tasks`, results file 22:22:47):

```
com.example.SessionRestoreFlowTest   tests=9  failures=0  errors=0  skipped=0
```

9 cases: successfulRefreshRotatesTokensAndRestoresSession ·
explicit401OnRefreshClearsSessionButKeepsBaseUrl ·
transient5xxOnRefreshKeepsCachedSession ·
probe200RestoresSessionWhenNoRefreshToken ·
probe503WithNonExpiredTokenKeepsCachedSessionWhenNoRefreshToken ·
noStoredTokensClearsAndStaysLoggedOut · probe401ClearsSessionWhenNoRefreshToken ·
serverUnreachableOnRefreshKeepsCachedSession ·
provablyExpiredTokensWithUnreachableServerClearSession

`SessionPersistenceTest` — helper-level (JwtUtils + clearSession): **5 / 5 PASS**.

---

## 5. Mobile unit tests

Fresh full run — `./gradlew --offline testDebugUnitTest --rerun-tasks`
(33 tasks executed):

| Suite | tests | pass |
|---|---|---|
| AuthRepositoryTest | 3 | 3 |
| ExampleRobolectricTest | 1 | 1 |
| ExampleUnitTest | 1 | 1 |
| FleetDataTest | 5 | 5 |
| GreetingScreenshotTest | 2 | 2 |
| SessionPersistenceTest | 5 | 5 |
| SessionRestoreFlowTest | 9 | 9 |
| **Total** | **26** | **26** |

`0 failures, 0 errors, 0 skipped`. `BUILD SUCCESSFUL`.

Build: `./gradlew --offline assembleDebug --rerun-tasks` → `BUILD SUCCESSFUL`
(mockwebserver resolves online on first fetch, then `--offline` works — this
machine reaches Maven Central; the old "no network" env note is stale).

---

## 6. Desktop tests

`cd desktop && PYTHONPATH=. ./venv/bin/pytest` (full, no cache):

```
147 passed in 358.70s
```

Collection confirmed to include every new untracked test file
(`test_cross_window_convergence`, `test_full_reactivity_lifecycle`,
`test_global_dispatch_isolation`, `test_maintenance_wins_reservation_desktop`,
`test_mutation_failure_no_false_event`, `test_status_derivation_regression`,
`test_fleet_parity_desktop`, `test_client_details_documents`,
`test_bug1_reservation_error_category`, `test_bug2_vehicle_form_status`) —
147 collected == 147 run.

Fresh focused re-run of the reactivity / parity critical set
(`test_reactivity_regression`, `test_full_reactivity_lifecycle`,
`test_cross_window_convergence`, `test_global_dispatch_isolation`,
`test_mutation_failure_no_false_event`, `test_dashboard_cache_parity`,
`test_fleet_parity_desktop`, `test_status_derivation_regression`,
`test_maintenance_wins_reservation_desktop`, `test_false_conflict_regression`):

```
30 passed in 111.01s
```

No test was weakened, skipped, or deleted.

---

## 7. Backend tests

`cd backend && ./venv/bin/pytest` (full, no cache):

```
101 passed in 7.90s
```

101 collected == 101 run; includes new `test_client_back_images`,
`test_fleet_status_parity`, `test_maintenance_frees_vehicle`,
`test_maintenance_wins_reservation`.

Fresh focused re-run (fleet-status parity + maintenance-wins + client back
images): `21 passed in 1.24s`.

DB: tests use the in-repo throwaway fixtures / sqlite emulation in
`tests/conftest.py`. Production PostgreSQL was **not** contacted or modified.

---

## 8. Cross-layer verification

Canonical fields checked end-to-end (backend schema ↔ desktop model ↔ mobile DTO/UI):

| Field | Backend | Desktop | Mobile | Verdict |
|---|---|---|---|---|
| `effective_status` (vehicle derived state) | `VehicleResponse.effective_status` + `services/fleet_status.py` | `utils/fleet_status.py`, consumed in lists/dashboard | `VehicleDto.effectiveStatus`, `mapVehicleDtoToDomain` uses `effectiveStatus ?: status` | **ALIGNED** — parity tested on backend (`test_fleet_status_parity`) and desktop (`test_fleet_parity_desktop`); mobile renders the server-derived value |
| reservation `status` | canonical enum | `ReservationStatus` | `ReservationStatus.fromApi` | ALIGNED |
| maintenance `status` / `step` | canonical | mirrored | `MaintenanceDto` + `MaintenanceStep` | ALIGNED |
| `cancellation_reason` (reservation) | `RentalResponse.cancellation_reason`, model col, migration `g2b3c4d5e6f7` | `LocalReservation.cancellation_reason` | **NOT carried** by `RentalDto` / mobile UI | Backend↔Desktop ALIGNED. Mobile does not surface it — pre-existing scope boundary (mobile is a read-only fleet viewer), not a regression from this work. Flagged §14. |
| client identity front **and back** | `identity_card_image[_back]`, `driving_license_image[_back]` + migration `h3c4d5e6f7g8` | same 4 columns on `LocalClient` | mobile carries **front only** (`identityCardImage`, `drivingLicenseImage`) on `RentalDto`/`ClientDto` | Backend↔Desktop ALIGNED (`test_client_back_images`, `test_client_details_documents`). Mobile back-image display not implemented — pre-existing scope boundary. Flagged §14. |
| dates | ISO strings | ISO strings | ISO strings passed through | ALIGNED |
| IDs | UUID str | str | str | ALIGNED |
| image URLs | relative path | resolved via root URL | `ImageUrlResolver.resolve(dto.imageUrl, rootUrl, version)` | ALIGNED |

No field is silently dropped **in a mapping that receives it**. The two mobile
gaps (`cancellation_reason`, document back-images) are fields the mobile client
never requested or displayed — a feature-parity gap that predates this session,
not data loss introduced here.

**Verdict: PASS** (with two documented mobile feature-parity gaps).

---

## 9. Login / logout verification

**Startup navigation (mobile, §6):** `FleetViewModel._navigationStack` starts
`[Screen.Splash]`. A `_bootstrapped` flag stays `false` until
`validateAndRestoreSession()` returns. The nav collector:

- `session != null` → Dashboard
- `session == null && bootstrapped` → Auth
- otherwise → Splash

so the sequence is **Splash → (restore completes) → Dashboard | Auth**. There
is no "navigate Login → async restore → navigate Home" path; the login screen
cannot flash for a cold start that has a valid stored session. `MainActivity`
renders `SplashScaffold()` whenever `currentScreen is Screen.Splash`. Initial
auth state is resolved **before** the destination is chosen. **PASS.**

**Logout (mobile, §7):** `logout()` → best-effort server `auth/logout` →
`clearLocalSession()` (tokens + identity cleared, base URL kept). ViewModel
sets `_navigationStack = [Screen.Auth]` (single entry) so `navigateBack()`
(guarded by `size > 1`) cannot reopen an authenticated screen, and
`BackHandler` is disabled on `Screen.Auth`. Process restart after logout: no
tokens → `validateAndRestoreSession` clears and routes to Auth. **PASS.**

**Desktop:** `test_ui_interactions::test_logout_clears_tokens` passes within the
147. `LoginWorker.run()` now wrapped in try/except (unexpected error →
`rejected` signal, no thread crash). Offline login still uses an Argon2 **hash**
(not plaintext) — unchanged desktop design. **PASS.**

---

## 10. Error semantics

Restore flow partitions transport outcomes correctly:

| Outcome | Restore action |
|---|---|
| connect refused / DNS fail (`IOException`) | keep cached session |
| read timeout | keep cached session |
| HTTP 5xx / 429 | keep cached session |
| HTTP 401 / 403 | **clear session**, require login |
| HTTP 200 (valid body) | rotate tokens, enter |

401 and 403 both invalidate auth (correct — both are "server rejected the
credential"). Every non-auth-rejection outcome retains the session. A network
failure is never turned into a logout. Login-form errors stay distinct
(`401/404` → bad credentials, `403` → role refused, `429` → rate-limited,
other → generic with code).

Desktop `ApiClient._request` now separates `timeout` (retried with widened
timeout, for fly.dev cold start) from `ConnectError` (not retried, real
offline), exposing `_last_transport_error` to callers. **PASS.**

---

## 11. Offline session verification

With a valid persisted session and the server unreachable / slow / 5xx:

- app opens (routes to Dashboard, not Auth) — proven by
  `serverUnreachableOnRefreshKeepsCachedSession`,
  `transient5xxOnRefreshKeepsCachedSession`
- session + tokens retained — asserted in the same tests
- cached fleet data served from Room (`FleetRepository` flows)
- background re-sync: nav collector calls `refreshAll()` and
  `RealtimeSyncManager.start()` on entering Dashboard; next reachable call
  re-validates
- no credential re-entry

**PASS** (JVM/Robolectric + MockWebServer level; not on-device).

---

## 12. Desktop live state (canonical architecture)

Not modified. Critical lifecycle
(AVAILABLE → reservation → RENTED/RESERVED → overlapping maintenance →
reservation auto-cancelled with `cancellation_reason='MAINTENANCE'` →
maintenance finish → AVAILABLE → new reservation) is exercised by
`test_full_reactivity_lifecycle`, `test_cross_window_convergence`,
`test_maintenance_wins_reservation_desktop`, `test_reactivity_regression`,
`test_dashboard_cache_parity` — all green in the fresh 30-test focused run and
in the full 147.

Canonical rule confirmed in code: the maintenance-side overlap trigger
(`trg_check_overlap_maint`) is removed; only the reservation-side guard remains;
the application layer atomically cancels the conflicting reservation.
Dashboard / Vehicles / Reservations / Maintenance converge via `EventBus`.

**PASS.**

---

## 13. Artifact provenance & SHA256

### Timeline
- newest `desktop/app/**/*.py` mtime: `2026-08-29 19:09:17`
- `packaging/windows/ATELIER_BERLIN_LOCATION_CAR.spec` mtime: `2026-08-29 19:16:05`
- Windows EXE build (`packaging/windows/{build,dist}/`): `2026-08-29 19:17:38`
- Windows ZIP: `2026-08-29 19:17:51`
- mobile source changes this session, then `assembleDebug`: `2026-08-29 22:17`+

The Windows EXE and ZIP **post-date** the newest desktop source change → they
reflect current desktop source. The mobile APK was rebuilt this session after
the mobile source changes.

### Hashes

| Artifact | Path | SHA256 |
|---|---|---|
| Android APK (debug) | `mobile/app/build/outputs/apk/debug/app-debug.apk` | `71dc95b72dc79b0019e5af42fb40a17b7d554821c1cf2d01600aa76594fea697` — reproducible: identical across the 22:17 build and a fresh `assembleDebug --rerun-tasks` (39 tasks executed) |
| Windows EXE | `packaging/windows/dist/ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` | `3dc5f13425980439e0f6461a2abe3b148a123cb85f691477f17c8fd819ac7e3b` |
| Windows EXE (build/ copy) | `packaging/windows/build/ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` | `3dc5f13425980439e0f6461a2abe3b148a123cb85f691477f17c8fd819ac7e3b` — **identical** |
| Windows ZIP | `ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip` | `99fec1835413597c2dcdb6119d4c58395b5dba4a4220d05b0ac27c9f4636e549` |
| EXE inside the ZIP | `ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` | `3dc5f13425980439e0f6461a2abe3b148a123cb85f691477f17c8fd819ac7e3b` |

**ZIP-EXE hash match: PASS** — the EXE extracted from
`ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip` is byte-identical to the freshly
built `build/` and `dist/` EXEs (`3dc5f134…`).

### Stale artifact warning
`./ATELIER_BERLIN_LOCATION_CAR_WINDOWS/ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe`
(mtime `02:59:57`, size 9095560, SHA256 `37b9c268741f8db8ca7f76130d137be871cb0ad7522f001c937f5989460d208f`)
is an **older extraction left in the repo root** and does **not** match the
current build. The authoritative distributable is the `.zip`, which is correct.
`dist/ATELIER_BERLIN_LOCATION_CAR_WIN.zip` (516 MB, Aug 29 00:58) is likewise
an old, differently-named archive — not current.

**Provenance verdict: PASS** for APK (rebuilt this session) and for the Windows
EXE/ZIP (post-date source, three byte-identical copies incl. the ZIP payload).
Not verified: that the EXE *executes* on a real Windows host (no Windows / no
emulation run here).

---

## 14. NOT VERIFIED

1. **On-device / emulator auth E2E** — no AVD/emulator on this machine; the
   real login → restart → restore → logout loop on Android hardware was not
   run. All mobile evidence is JVM + Robolectric + MockWebServer.
2. **Windows EXE runtime** — no Windows host and no wine execution run; only
   build provenance and hash integrity are verified, not that the binary
   launches or that the desktop app works packaged.
3. **Signed release APK** — keystore is CI-secret-only; only the **debug** APK
   exists. `assembleRelease` was not attempted.
4. **Production PostgreSQL parity** — no production credentials; migrations
   `f1a2b3c4d5e6`, `g2b3c4d5e6f7`, `h3c4d5e6f7g8` verified only against test
   fixtures, not applied/validated against prod.
5. **Live multi-client sync E2E** against the deployed fly.dev backend (may be
   scaled to zero).
6. **Mobile feature parity** for `cancellation_reason` and client document
   **back** images — backend and desktop carry them; mobile does not display
   them (pre-existing scope boundary, not a regression).

---

## 15. Remaining risks

- **Uncommitted release**: the entire verified state is an uncommitted working
  tree on top of `df9b96d`. If the tree is stashed/reset before a commit, the
  fix and all new tests are lost. Recommend committing before cutting the
  release. 12 commits are also still unpushed.
- **Mid-session refresh rejection (mobile)**: `TokenAuthenticator` (OkHttp
  `authenticator`, hit on a 401 during normal API calls) calls
  `tokenManager.clearTokens()` but does **not** update
  `AuthRepository._currentUserSession`, so if the refresh token is
  server-rejected *while the app is already running*, the UI stays on Dashboard
  (with failing API calls) until the next app start or manual logout. Not a
  security hole (no access is granted), but a UX gap. Pre-existing; out of
  scope for this gate.
- **Windows EXE trust**: shipped without on-Windows smoke test.
- **Stale artifacts in the tree** (`ATELIER_BERLIN_LOCATION_CAR_WINDOWS/` dir,
  `dist/ATELIER_BERLIN_LOCATION_CAR_WIN.zip`) could be mistaken for the current
  release — recommend removing or clearly archiving them.
- Deprecation warnings (Pydantic v2 class-config, Gradle 10, Compose
  AutoMirrored icons) — non-blocking, accumulating tech debt.

---

## 16. Final verdict

All code-level, unit, and integration evidence is green:

- Mobile: 26/26 unit (incl. 9/9 full session-restore flow), `assembleDebug` OK
- Desktop: 147/147 full, 30/30 focused reactivity/parity
- Backend: 101/101 full, 21/21 focused parity
- Cross-layer canonical fields aligned (2 documented mobile feature gaps)
- Login / logout / offline / 401 / error-semantics contract satisfied in code
  and tests
- Artifact provenance + ZIP-EXE hash integrity verified

The only material gap for the mobile release is on-device auth E2E; the Windows
EXE also lacks an on-Windows runtime check.

**CODE + UNIT + INTEGRATION VERIFIED; ON-DEVICE AUTH E2E NOT VERIFIED**

**FINAL: READY FOR MANUAL DEVICE TEST**
