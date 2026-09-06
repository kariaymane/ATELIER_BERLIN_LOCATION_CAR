# Atelier Berlin Location Car

A complete, cross-platform car rental management system.

## Architecture

The system consists of three main components:

1. **Backend (FastAPI & PostgreSQL)**
   - REST API
   - Real-time WebSockets
   - Role-Based Access Control (RBAC)
   - Alembic database migrations

2. **Desktop Client (PySide6 / Qt)**
   - Primary management interface for staff
   - Offline-first capabilities with local SQLite cache
   - Background Synchronization Engine (`SyncEngine`)
   - Vehicle, Reservation, and Maintenance management

3. **Mobile App (Android / Kotlin / Jetpack Compose)**
   - Dashboard for quick access
   - Real-time updates via WebSockets
   - Local persistence with Room database
   - Secure token management

## Setup & Development

### Backend
```bash
cd backend
cp ../.env.example .env   # then fill in the placeholders
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

### Desktop
```bash
cd desktop
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$(pwd)
python app/main.py
```

### Mobile
```bash
cd mobile
./gradlew clean assembleDebug
```

A **release** build needs the signing identity, which is deliberately kept
outside this repository so it can never be committed:

```bash
export KEYSTORE_PATH=/path/to/production-upload-key.jks
export STORE_PASSWORD=... KEY_PASSWORD=... KEY_ALIAS=...
./gradlew clean assembleRelease
```

CI does the same through GitHub Actions secrets (`.github/workflows/android-release.yml`).

## Testing
Run \`pytest\` in the \`backend\` and \`desktop\` directories respectively to execute the test suites.

## Security

- **Secrets** are never committed. The deployed API reads them from `fly secrets`;
  CI reads them from GitHub Actions secrets; local development uses an untracked
  `.env` seeded from `.env.example`.
- **Passwords** are hashed with Argon2id. Access tokens live 15 minutes, refresh
  tokens rotate on use and are stored only as SHA-256 hashes.
- **Accounts lock** for 15 minutes after 5 failed logins; login is rate-limited.
- **Client documents** are stored under unguessable UUID filenames, validated by
  magic bytes on upload, and referenced only by `/static/uploads/...` paths —
  clients refuse a document reference pointing anywhere else.
- **Rotating the administrator password**: `POST /api/v1/auth/change-password`
  (this revokes every refresh token), then update the `ADMIN_PASSWORD` Fly secret
  so a future reseed matches.

## Repository layout

```
backend/     FastAPI application, Alembic migrations, tests
desktop/     PySide6 client and tests
mobile/      Android (Kotlin / Jetpack Compose) client and tests
shared/      Reference implementations shared by all three runtimes
scripts/     Operational and verification scripts
packaging/   Windows packaging (PyInstaller under Wine)
docker/      Backend image and local compose stack
```

Build outputs, database dumps, signing identities and historical engineering
reports are kept outside the repository.
