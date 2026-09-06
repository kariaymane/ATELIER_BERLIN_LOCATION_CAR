# ATELIER BERLIN LOCATION CAR — Android Mobile App

The Android companion application for **ATELIER BERLIN LOCATION CAR**, providing mobile supervision, fleet status monitoring, and real-time operations dashboard.

## Architecture

- **UI**: Jetpack Compose, Material 3 design system, responsive RTL & Arabic support.
- **Networking**: Retrofit 2, OkHttp with `AuthInterceptor` and automatic token refresh via `TokenAuthenticator`.
- **Realtime**: WebSockets connection for live updates between workstation and mobile devices.
- **Local Cache**: Android Room database for offline persistence and instant screen loading.
- **Security**: Cleartext HTTP traffic is blocked via network security configuration (`network_security_config.xml`). No credentials or database URLs are baked into the APK.

## Development & Build

### Prerequisites

- JDK 17
- Android SDK (API Level 36, minimum SDK 24)

### Build Debug APK

```bash
cd mobile
./gradlew clean assembleDebug
```

### Run Unit Tests

```bash
cd mobile
./gradlew testDebugUnitTest
```

### Release Signing

Release builds require signing credentials provided via environment variables (kept outside version control):

```bash
export KEYSTORE_PATH=/path/to/keystore.jks
export STORE_PASSWORD=...
export KEY_PASSWORD=...
export KEY_ALIAS=...
./gradlew clean assembleRelease
```
