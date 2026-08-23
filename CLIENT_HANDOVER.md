# ATELIER BERLIN LOCATION CAR — Client Handover

## Application

ATELIER BERLIN LOCATION CAR — professional car rental management system.

## Delivered Components

| Component | Technology | Purpose |
|---|---|---|
| Windows Desktop Application | PySide6 (Qt) | Main workstation application with offline capability |
| Android Application | Kotlin + Jetpack Compose | Mobile read-only companion |
| Backend / API | FastAPI | Central server for all data and synchronization |
| Database | PostgreSQL | Authoritative storage on the server |
| Synchronization system | SyncEngine | Keeps desktop offline work and server data consistent |

## Main Features

- Dashboard with key business indicators
- Vehicle management (specifications, documents, photos)
- Reservations with double-booking protection
- Maintenance tracking
- Notifications
- Secure authentication (individual user accounts, role-based access)
- Offline desktop cache: keep working when the internet drops
- Automatic synchronization of offline changes
- Vehicle photos and client document images (identity card, driving license)
- Realtime updates between desktop and mobile

## Installation — Windows

1. Unzip `ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip`.
2. Open the folder and double-click `ATELIER_BERLIN_LOCATION_CAR.exe`.
   - No installation is required; all libraries are included.
3. Log in with the company account provided by your administrator.

If Windows SmartScreen shows a warning for an unsigned application, choose
"More info" → "Run anyway".

## Installation — Android

1. Copy `app-debug.apk` to the phone.
2. Tap the file and allow "Install from unknown sources" if prompted.
3. Log in with the company account provided by your administrator.
   - The application connects automatically to the company server.

## Important Operational Notes

- **Desktop connectivity**: the desktop application needs an internet
  connection to log in and to synchronize with the server.
- **Offline desktop work**: if the connection drops, you can continue working;
  all changes are stored locally and synchronize automatically once the
  connection returns. Photos/documents taken while offline are uploaded
  automatically as well.
- **Android**: the mobile app always shows current server data through a
  secure connection and keeps a local read cache for faster loading.
- **Realtime updates**: live updates between devices require an authenticated
  session (logged-in user). Unauthorized connections are rejected by the server.
- **Double-booking protection**: overlapping reservations for the same vehicle
  are blocked automatically, both on the server and in the desktop app.

## Support Notes

- Data entered while the server is unreachable is never lost; it syncs later.
- Do not share login credentials between employees; each user has their own
  account and permissions.
