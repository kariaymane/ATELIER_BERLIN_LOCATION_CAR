# MOBILE SECURITY RELEASE — BUILD REPORT

**Generated:** 2026-09-02
**Repository:** `car-rental-system`
**Branch:** `security/mobile-password-lifecycle`
**Commit:** `e447da7e9b9726f0c26a9faa35f1245adb1afec8`
**Subject:** `security(mobile): plaintext password never persisted or restorable`

---

## 1. Git state at build time

```
$ git rev-parse HEAD
e447da7e9b9726f0c26a9faa35f1245adb1afec8

$ git status --porcelain
(empty — working tree clean)

$ git log --oneline -3
e447da7  security(mobile): plaintext password never persisted or restorable
9822831  fix(responsive): dashboard vertical scroll + offline banner on all mobile list screens
f1a0888  fix(backend,mobile): DB pool sizing, real liveness/readiness split, mobile offline cache fallback
```

## 2. Source-of-APK verification

The APK is built from commit `e447da7`, working tree clean. Confirmation that
the security-hardened code is compiled into the artifact:

```
$ unzip -p app-debug.apk 'classes*.dex' | strings | grep -c 'auth_password_field'
1        # the testTag added to AuthScreen's password field in e447da7
```

Same marker is present in the release-variant APK.

## 3. Tests (pre-build gate)

```
./gradlew :app:testDebugUnitTest   → BUILD SUCCESSFUL — 64 tests, 0 failures, 0 errors
./gradlew :app:assembleDebug       → BUILD SUCCESSFUL
```

Security tests included: `MobilePasswordForensicTest` (4), `AuthScreenPasswordLifecycleTest` (2).

## 4. Build commands run

| Command | Result |
|---|---|
| `./gradlew :app:assembleDebug` | **BUILD SUCCESSFUL** → `app-debug.apk` |
| `./gradlew :app:assembleRelease` (project default config) | **BUILD FAILED** at `:app:packageRelease` — see §5 |
| `./gradlew :app:assembleRelease` (`STORE_PASSWORD`/`KEY_PASSWORD`/`KEY_ALIAS` supplied, `-x lintVital*`) | **BUILD SUCCESSFUL** → `app-release.apk` (see §5 for the signing caveat) |

## 5. ⚠️ Production release-signing blocker

`./gradlew :app:assembleRelease` with the project's real configuration **fails**:

```
> Task :app:packageRelease FAILED
  Execution failed for task ':app:packageRelease'.
  > SigningConfig "release" is missing required property "storePassword".
```

**Why:** `mobile/app/build.gradle.kts` `signingConfigs.release` reads
`STORE_PASSWORD` / `KEY_PASSWORD` from environment variables, and
`.github/workflows/android-release.yml` supplies the production keystore and
those passwords from **GitHub Actions secrets** (`KEYSTORE_BASE64`,
`secrets.STORE_PASSWORD`, `secrets.KEY_PASSWORD`, `secrets.KEY_ALIAS`). None of
those secrets are available in this environment.

**The local `mobile/my-upload-key.jks` is NOT the production key** — it is
byte-identical to the Android debug keystore
(`sha256 dab44b44e1195726a5a8584442a9ba5598d3cb66245227f78e0f57927f1c8c43`,
certificate `SHA-256 7aad8e0e0d6cb20a744516de27d8ec6850af99e942c017e8dde2f4c15bb85174`,
alias `androiddebugkey`). It is a placeholder committed for CI-path parity.

**Consequence:** a genuine, distributable **production release APK cannot be
produced here.** The `app-release.apk` that was built (with the placeholder key
+ `-x lintVital*` to avoid an OOM on this machine) is a *release build type*
APK **signed with the Android debug certificate** — suitable for QA / manual
inspection only, **NOT for Play Store / production distribution**.

To cut the real production release: push a `v*` tag (or run the
`Android Release` workflow) with the repo's configured signing secrets — that
job runs `./gradlew clean assembleRelease` and publishes the signed APK/AAB.

## 6. Artifacts produced

| File | Size (bytes) | SHA-256 | Signing cert | Status |
|---|---|---|---|---|
| `app-debug.apk` | 23545156 | `62571cce93a45b11e08a120c5dcdab0301b208a6b094d5d756a4a03c402feb63` | Android Debug (`7aad8e0e…`) | **VERIFIED — primary deliverable** (built from `e447da7`) |
| `app-release.apk` | 16151543 | `7fe7ce9a77c2e6a529bac05ca1dd838db81619831d1e799c2b3673eb5084b61e` | Android Debug (`7aad8e0e…`) | release build type, **debug-signed → NON-PRODUCTION** |

Both: `applicationId com.example`, `versionCode 1`, `versionName 1.0`,
`minSdk 24`, `targetSdk 36`, label "ATELIER BERLIN LOCATION CAR".
Both: `apksigner verify` → **VERIFIED** (v2 scheme).

## 7. Smoke verification (post-build)

| Check | debug | release |
|---|---|---|
| `apksigner verify` | ✅ VERIFIED | ✅ VERIFIED |
| `aapt dump badging` (package / sdk / label) | ✅ | ✅ |
| Security marker `auth_password_field` in dex | ✅ (1) | ✅ (1) |
| No hardcoded signing secret / keystore path in dex | ✅ | ✅ |
| `INTERNET` permission + `MainActivity` component | ✅ | ✅ |

## 8. Packaging

`atelier-berlin-location-car-mobile-security-e447da7.zip` contains:
`app-debug.apk`, `app-release.apk` (labeled non-production), this report,
`MOBILE_SECURITY_AUDIT_REPORT.md`, and `SHA256SUMS`. No `build/`, `.gradle/`,
`.git/`, caches, or intermediates are included.

## 9. Security audit status

`MOBILE_SECURITY_AUDIT_REPORT.md` — plaintext password: **STORAGE NONE /
PERSISTENCE NONE / RESTORATION NONE / LOGGING NONE**; logout cleanup PASS;
process-recreation PASS; 64/64 tests PASS.

## 10. No unrelated changes

Only auth files + 2 test files + 2 report docs were added/changed on this
branch. Vehicles, reservations, maintenance, dashboard, notifications, revenue,
sync, Room fleet cache, Pistache theme, Arabic RTL, branding, and the backend
API are untouched.

## 11. Push status

**NOT pushed.** Branch `security/mobile-password-lifecycle` is local only.
