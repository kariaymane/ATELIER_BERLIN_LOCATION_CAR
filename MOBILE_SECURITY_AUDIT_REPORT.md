# MOBILE SECURITY AUDIT — Plaintext Password Lifecycle

**Date:** 2026-09-02
**Scope:** Android / Kotlin / Jetpack Compose app under `mobile/`
**Type:** Security hardening only — no business logic, UI design, theme, RTL, branding, sync, or Room fleet-cache changes.
**Branch:** `security/mobile-password-lifecycle`
**Production API (unchanged):** `https://car-rental-system.fly.dev/api/v1/`

---

## 1. Files inspected

| Area | Files |
|---|---|
| Auth flow | `data/repository/AuthRepository.kt`, `ui/viewmodel/FleetViewModel.kt`, `ui/screens/AuthScreen.kt` |
| Network / DTO | `data/api/ApiClient.kt`, `data/api/ApiService.kt`, `data/api/NetworkModels.kt`, `data/api/TokenManager.kt`, `data/api/JwtUtils.kt` |
| Realtime | `data/sync/RealtimeSyncManager.kt` |
| Persistence | `data/local/Entities.kt`, `data/local/Daos.kt`, `data/local/AppDatabase.kt`, `data/local/ThemePreferences.kt`, `data/local/LanguagePreferences.kt`, `data/local/VehicleImageEntity.kt` |
| App shell | `MainActivity.kt`, `AndroidManifest.xml`, `app/build.gradle.kts` |
| Repo-wide greps | `password`, `passwd`, `credential`, `rememberSaveable`, `SavedStateHandle`, `DataStore`, `SharedPreferences`, `Room`, `Timber`, `Log.d/i/w/e`, `Authorization`, `Bearer`, `Crashlytics`, `putExtra`, `cache(` |

## 2. Findings

| # | Severity | Finding | Where |
|---|---|---|---|
| F1 | **Medium** | Plaintext password held in Compose state (`var password by remember { … }`) was **not explicitly cleared after a successful login**. It was discarded when `AuthScreen` left composition, but nothing wiped it on the success path itself, so it lived in RAM for the whole time the login screen stayed composed. | `AuthScreen.kt` |
| F2 | **Low (defence-in-depth)** | `HttpLoggingInterceptor` ran at `Level.BASIC` in **all** build types (including release) with no header redaction. BASIC does not log bodies or headers, so no credential leak today — but a future bump to `HEADERS`/`BODY` would leak the bearer token / login body, and release builds should not log at all. | `ApiClient.kt` |
| F3 | Info | Logout did not clear transient auth UI messages (`_errorMessage` / `_successMessage`). No password involved (it is never stored), but stale text could carry into the next login screen. | `FleetViewModel.kt` |

### Verified **clean** (no change required)

| Surface | Result |
|---|---|
| Room / SQLite | Entities = Vehicle, VehicleImage, Reservation, Maintenance, MaintenancePart, Notification, SyncMetadata. **No password/token/credential column.** `SyncMetadataEntity` only ever written with sync keys. |
| SharedPreferences | `car_rental_auth_prefs` (token, refresh token, user id/email/name/role, base URL), `theme_prefs`, `language_prefs`. **No password key or value.** |
| DataStore | Not used anywhere in the project. |
| `SavedStateHandle` / `rememberSaveable` | **Not used anywhere.** Password state is plain `remember` → never written to the saved-instance-state Bundle → cannot be restored after config change or process death. |
| Intent extras / navigation args | Navigation is an in-ViewModel `Screen` sealed class; `Screen.Auth` is a parameterless `data object`. No password in any nav argument, `Intent`, or `Bundle`. |
| Singletons / `companion object` / statics | None hold a password. `TokenManager.Companion` holds only pref-key name constants + `DEFAULT_BASE_URL`. |
| Logging (`Log.*`) | Auth-path logs print status text and `exception.message` only — **no `$token` / `$password` / `Bearer $…` interpolation** anywhere. No Timber. |
| Crash reporting | No Crashlytics / `recordException` / analytics custom keys in code. |
| OkHttp HTTP cache | No `.cache(...)` configured → request/response bodies are never written to disk. |
| `MainActivity` | No custom `onSaveInstanceState` / `onRestoreInstanceState`. ViewModel built without `SavedStateHandle`. |
| `BuildConfig` / gradle | No `buildConfigField` contains a password/secret. |
| WebSocket (`RealtimeSyncManager`) | Adds `Authorization: Bearer $token` header (not logged); logs URL + event type + inbound business frames — no credentials. |

## 3. Exact fixes implemented

### `ui/screens/AuthScreen.kt`
- Documented that `password` is deliberately `remember` (never `rememberSaveable`).
- Added `DisposableEffect(Unit) { onDispose { password = ""; passwordVisible = false } }` — wipes the field the instant the screen is torn down (login navigation, logout, process teardown).
- Consolidated the two login trigger sites (button `onClick`, keyboard `onDone`) into one `attemptLogin()` that, **on success, sets `password = ""` and `passwordVisible = false` BEFORE calling `onLoginSuccess()`** — from then on the app runs purely on the token/session.
- Added `Modifier.testTag("auth_password_field")` for deterministic security testing (no behaviour change).
- `PasswordVisualTransformation()` was already in place — retained.

### `ui/viewmodel/FleetViewModel.kt`
- `login(email, pass, …)`: added a security contract doc comment — `pass` is a method parameter only, never a field / companion / `SavedStateHandle` / store; GC-eligible once the coroutine ends.
- `logout()`: now also clears `_errorMessage` and `_successMessage` so no transient auth text survives into the login screen. (Token/session teardown was already correct via `authRepository.logout()`.)

### `data/repository/AuthRepository.kt`
- `login(email, password)`: added a doc comment pinning the contract — `password` is used only as the `/auth/login` request body; the `LoginRequestDto` carrying it is a local value that becomes unreachable on return; only the returned tokens are persisted (by `TokenManager`).

### `data/api/ApiClient.kt`
- HTTP logging is now `Level.BASIC` **only in debug builds** (`BuildConfig.DEBUG`), `Level.NONE` in release.
- Added `redactHeader("Authorization")`, `redactHeader("Cookie")`, `redactHeader("Set-Cookie")` so a bearer token / cookie can never be printed even if the level is later raised.

## 4. Password lifecycle (after fix)

```
User types password
  → AuthScreen  var password (Compose `remember`, in-RAM only, masked by PasswordVisualTransformation)
  → attemptLogin()
       → FleetViewModel.login(email, pass)        pass = method param
            → AuthRepository.login(email, password)   password = method param
                 → LoginRequestDto(password=…)        local value, request body only
                 → POST /api/v1/auth/login            body NOT logged (BASIC), no disk cache
            ← { access_token, refresh_token, … }      only tokens persisted (TokenManager → SharedPreferences)
  ← success
  → password = ""  ·  passwordVisible = false       (AuthScreen, before navigation)
  → onLoginSuccess() → navigate to Dashboard
  → AuthScreen leaves composition → onDispose { password = "" } → remembered state discarded (GC)
```
The plaintext password never leaves `AuthScreen` + the single `login()` call chain, and never reaches any persistent store.

## 5. Logout behaviour
1. `AuthRepository.logout()` → best-effort `POST /auth/logout` (invalidate refresh token server-side) → `TokenManager.clearSession()` removes access token, refresh token, user id/email/name/role (keeps only the operator-configured base URL).
2. `FleetViewModel.logout()` clears `_errorMessage` / `_successMessage` and routes to `Screen.Auth`.
3. `userSession` becomes `null` → UI renders a **fresh** `AuthScreen` → `password = remember { mutableStateOf("") }` = empty.
4. The disposed previous `AuthScreen` already ran `onDispose { password = "" }`.
No plaintext password exists anywhere before, during, or after logout (it was never stored).

## 6. App exit / background / process death
- Password state is `remember` (not `rememberSaveable`) and there is no `SavedStateHandle` / custom `onSaveInstanceState`, so **nothing is written to the saved-instance-state Bundle**.
- After Android kills & recreates the process: `MainActivity` recreates, ViewModel is fresh, `AuthScreen` renders with an empty password field. Session restore uses the **persisted token** (`AuthRepository.validateAndRestoreSession()`), never a password.
- Valid tokens are intentionally **not** destroyed on backgrounding — "log in once, stay logged in until logout" is preserved.

## 7. Token behaviour (unchanged architecture)
- Access + refresh tokens persisted in `SharedPreferences` (`car_rental_auth_prefs`) via `TokenManager` — the existing mechanism, not replaced.
- Tokens are **never logged** (no interpolation in any `Log.*`; interceptor redacts `Authorization`; release builds log nothing).
- 401 → `TokenAuthenticator` silently refreshes; a rejected refresh (401/403) clears the session; a network failure retains tokens for offline use.
- Plaintext password is **not** persisted alongside tokens (it is not persisted at all).

## 8. Logging audit
| Check | Result |
|---|---|
| Plaintext password in Logcat | **NONE** — never passed to any log call |
| Access / refresh token in Logcat | **NONE** — status text + codes only |
| `Authorization` header in Logcat | **NONE** — not logged; `redactHeader("Authorization")` added |
| Login request body in Logcat | **NONE** — `HttpLoggingInterceptor.Level.BASIC` logs no bodies; release = `NONE` |
| Auth response secrets in Logcat | **NONE** |
| Timber / Crashlytics | Not present |

## 9. Room / DataStore / SharedPreferences audit
- **Room:** 7 business entities, zero credential columns; forensic test scans every table + every text cell for the password → clean.
- **DataStore:** not used.
- **SharedPreferences:** 3 files; forensic test reads every `.xml` and asserts none contains the password string or a `password`/`passwd`/`pwd` key → clean. Tokens present (intended).

## 10. Test commands & results

```
./gradlew :app:testDebugUnitTest        → BUILD SUCCESSFUL — 64 tests, 0 failures, 0 errors
./gradlew :app:assembleDebug            → BUILD SUCCESSFUL
```

New security tests (6):

| Test | Asserts |
|---|---|
| `MobilePasswordForensicTest.no SharedPreferences value or key contains the password after login` | Real login via MockWebServer; every `shared_prefs/*.xml` free of the secret and of any password-shaped key; tokens ARE persisted |
| `MobilePasswordForensicTest.Room schema has no credential column and holds no password` | No `password/passwd/pwd/secret/credential` column in any table; no cell value contains the secret (after a snapshot apply) |
| `MobilePasswordForensicTest.AuthRepository and TokenManager retain no field equal to the password` | Reflection over every field (incl. superclasses) of both objects post-login — none holds the password (String or CharArray) |
| `MobilePasswordForensicTest.no file under the app data dir contains the password` | Recursive byte-scan of the entire app data dir — password appears in no file |
| `AuthScreenPasswordLifecycleTest.password does not survive AuthScreen leaving and re-entering composition` | Type password → dispose AuthScreen (login nav) → re-enter (logout) → field is empty |
| `AuthScreenPasswordLifecycleTest.process recreation does not restore the typed password` | `StateRestorationTester.emulateSavedInstanceStateRestore()` → password field is empty (proves not saveable) |

Full pre-existing suite (58 tests) unchanged and green.

## 11. Build result
`./gradlew :app:assembleDebug` → **BUILD SUCCESSFUL**
APK: `mobile/app/build/outputs/apk/debug/app-debug.apk` — 23,545,156 bytes — SHA-256 `62571cce93a45b11e08a120c5dcdab0301b208a6b094d5d756a4a03c402feb63` — built 2026-09-02 01:21 (this is a verification build; final release packaging is out of scope).

## 12. Final forensic checklist

| Check | Status |
|---|---|
| Plaintext password not stored in Room | **PASS** |
| Plaintext password not stored in DataStore | **PASS** (DataStore not used) |
| Plaintext password not stored in SharedPreferences | **PASS** |
| Plaintext password not stored in files/cache | **PASS** |
| Plaintext password not stored in SavedStateHandle | **PASS** (not used) |
| Plaintext password not stored in navigation arguments | **PASS** |
| Plaintext password not stored in singleton/static state | **PASS** |
| Password cleared after successful login | **PASS** (`password = ""` on success + `onDispose`) |
| Password cleared on logout | **PASS** (fresh AuthScreen + prior `onDispose`) |
| Password not restored after process recreation | **PASS** (`remember`, never `rememberSaveable`; `StateRestorationTester` test green) |
| Password not printed in Logcat | **PASS** |
| Tokens not printed in Logcat | **PASS** |
| Authorization headers not printed | **PASS** (`redactHeader`, release = `NONE`) |
| Existing authentication still works | **PASS** (auth/session/refresh tests green; API contract unchanged) |
| Existing API still works | **PASS** (no DTO/endpoint change) |
| Existing mobile functionality unaffected | **PASS** (only auth files + 2 test files touched) |
| Android tests PASS | **PASS** (64/64) |
| assembleDebug BUILD SUCCESS | **PASS** |

---

## Summary

```
PASSWORD STORAGE:      NONE
PASSWORD PERSISTENCE:  NONE
PASSWORD RESTORATION:  NONE
PASSWORD LOGGING:      NONE
LOGOUT CLEANUP:        PASS
PROCESS RECREATION:    PASS
AUTHENTICATION:        PASS
TESTS:                 PASS  (64/64)
APK BUILD:             PASS
```
