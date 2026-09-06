# Atelier Berlin Location Car

Car rental management software for staff, with a FastAPI backend, a Qt desktop
client, and an Android application.

## Features

- Vehicle inventory, availability, and maintenance tracking
- Customer records and reservation management
- Revenue and fleet utilization dashboards
- Role-based access and authenticated realtime updates
- French and Arabic interfaces

## Architecture

```text
Desktop (Python / PySide6) ─┐
                          ├── FastAPI ── PostgreSQL
Android (Kotlin / Compose) ┘
```

PostgreSQL is the authoritative server database. Neither client connects to it
directly. REST endpoints handle application operations; WebSockets notify clients
of changes. Shared Python reference calculations and synthetic fixtures verify
cross-client date, availability, and revenue rules.

**Current client behavior:** the desktop still maintains a SQLite cache and a
pending-write queue; Android uses Room snapshots and local read-side calculations.
These active compatibility paths mean the clients are not yet API-only. Keep
connectivity and authentication checks enabled; cached state is not proof that a
server-side operation succeeded.

```text
backend/     FastAPI application, Alembic migrations, and tests
desktop/    PySide6 application and tests
mobile/     Android application, Gradle wrapper, and tests
shared/     Domain rules and cross-runtime test fixtures
docker/     Container build and deployment templates
packaging/  Native Windows packaging
scripts/    Backup/restore and fixture utilities
docs/       Deployment guidance
```

## Requirements

- Python 3.11 or newer (CI and the backend image use Python 3.12)
- Docker Engine with Compose v2 for the local API/database stack
- JDK 17 and the Android SDK required by `mobile/app/build.gradle.kts` for Android
- A graphical desktop and the platform libraries required by Qt for the desktop
  client; Windows builds must be produced on Windows

Run the following commands from the repository root unless noted otherwise.
Do not use a production database or account for development or tests.

## Run the backend

1. Copy the deployment template:

   ```sh
   cp docker/.env.example docker/.env
   ```

2. Set independent `POSTGRES_PASSWORD`, `JWT_SECRET`, and `JWT_REFRESH_SECRET`
   values in `docker/.env`. Use a password manager to generate strong, URL-safe
   values. To provision the first administrator, also set `ADMIN_EMAIL` and
   `ADMIN_PASSWORD`; there is no built-in login.

3. Initialize the database and start the API:

   ```sh
   docker compose --env-file docker/.env -f docker/compose.yml up -d postgres
   docker compose --env-file docker/.env -f docker/compose.yml run --rm backend alembic upgrade head
   docker compose --env-file docker/.env -f docker/compose.yml up -d backend
   ```

The local API is available at `http://127.0.0.1:8000`. Explore its schema at
[`/docs`](http://127.0.0.1:8000/docs). `/health/live` checks the process;
`/health/ready` also checks database access. PostgreSQL has **no published host
port** in this stack.

For native backend development, create a virtual environment in `backend/`,
install `requirements-dev.txt`, and copy `backend/.env.example` to `backend/.env`.
Supply URLs for your own disposable PostgreSQL instance, then run
`alembic upgrade head` and `python -m uvicorn app.main:app --reload` from `backend/`.

## Run the desktop client

```sh
cd desktop
python -m venv .venv
# POSIX: source .venv/bin/activate
# PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cp .env.example .env
python -m app.main
```

Set `API_BASE_URL` in `desktop/.env` to the API origin, without `/api/v1`.
The default targets the local API, never a shared deployment. Application data
is stored in the platform's per-user data directory, not in the source tree.

## Build Android

Open `mobile/` in Android Studio or use its Gradle wrapper. Configure an HTTPS API
origin with `-PapiBaseUrl` or the `API_BASE_URL` environment variable:

```sh
cd mobile
./gradlew testDebugUnitTest assembleDebug -PapiBaseUrl=https://api.example.invalid/
```

Replace the example origin with your development API before using the app.
Use `gradlew.bat` on Windows. The placeholder build cannot reach a real service.
Release builds require an explicit API origin and private signing configuration;
see [deployment](docs/deployment.md).

## Tests and development checks

Use separate Python virtual environments for the backend and desktop, as both
expose a top-level `app` package.

```sh
# In backend/, with its virtual environment activated:
python -m pip install -r requirements-dev.txt
python -m pytest tests

# In desktop/, with its virtual environment activated:
python -m pip install -r requirements-dev.txt
python -m pytest tests
```

Desktop tests can run headlessly with `QT_QPA_PLATFORM=offscreen` where Qt's native
libraries are installed. Backend tests default to disposable in-memory SQLite;
CI also runs the migration-backed suite against an isolated PostgreSQL service.
Never point `TEST_DATABASE_URL` at a persistent database: the suite resets it.

Keep tests, migrations, and fixtures alongside code changes. Use synthetic
customer data and reserved example domains. Do not commit local configuration,
customer uploads, screenshots of customer records, database exports, or installers.

## Deployment and security

- [Deployment and release builds](docs/deployment.md)
- [Security policy and private reporting process](SECURITY.md)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [Qt for Python documentation](https://doc.qt.io/qtforpython-6/)
- [Android developer documentation](https://developer.android.com/)

No open-source license has been declared in this repository. Public visibility
does not grant a license; obtain permission from the rights holder before reuse.
