# Atelier Berlin Location Car

A complete, enterprise-grade, cross-platform car rental management system.

---

## Architecture Overview

The system consists of three integrated components backed by an authoritative relational database:

1. **Backend API (FastAPI & PostgreSQL)**
   - High-performance asynchronous REST API
   - Real-time event updates via WebSockets
   - Role-Based Access Control (RBAC) and JWT authentication
   - Database schema migrations via Alembic
   - Private network data isolation

2. **Desktop Application (PySide6 / Qt)**
   - Comprehensive workstation interface for fleet operators and staff
   - Offline resilience with local caching and background `SyncEngine`
   - Fleet inventory, reservation scheduling, document viewing, and maintenance lifecycle

3. **Mobile Application (Android / Kotlin / Jetpack Compose)**
   - Modern native mobile companion app
   - Real-time fleet metrics and status monitoring
   - Local persistence via Room database
   - Secure token lifecycle management

---

## Repository Structure

```text
├── backend/          # FastAPI application, Alembic migrations, test suites
├── desktop/          # PySide6 desktop client and UI test suites
├── mobile/           # Android application (Kotlin / Jetpack Compose)
├── shared/           # Cross-runtime domain models, business logic & schemas
├── docker/           # Production container builds & local compose stack
├── packaging/        # Packaging definitions and release build scripts
├── scripts/          # Operational tools and data reconciliation utilities
├── docs/             # Documentation and user guides
├── .github/          # CI/CD workflows and automated release pipelines
├── LICENSE           # MIT License
├── README.md         # Project overview and setup instructions
└── SECURITY.md       # Security policy and vulnerability disclosure process
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL 15+ (or Docker)
- Android SDK / JDK 17 (for mobile build)

### 1. Backend Setup

```bash
cd backend
cp ../.env.example .env   # Configure environment variables
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

The API will be accessible at `http://localhost:8000` with documentation at `http://localhost:8000/docs`.

### 2. Desktop Application Setup

```bash
cd desktop
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$(pwd)
python app/main.py
```

### 3. Mobile Application Setup

```bash
cd mobile
./gradlew clean assembleDebug
```

For release signing, configure keystore parameters via environment variables or CI secrets as described in `.github/workflows/android-release.yml`.

---

## Testing & Quality Assurance

Run the automated test suites from their respective directories:

```bash
# Backend suite (API contracts, domain logic, security checks)
pytest backend/tests/

# Desktop suite (UI flows, sync engine, document viewer security)
PYTHONPATH=desktop pytest desktop/tests/

# Mobile unit tests
cd mobile && ./gradlew test
```

---

## Security & Compliance

- **Secrets Management**: Credentials and signing secrets are managed through isolated runtime environment secrets and never committed to source control.
- **Access Control**: Passwords are cryptographically hashed using Argon2id. API requests require signed Bearer tokens with strict expiration and rotation policies.
- **Workflow Isolation**: All GitHub Actions workflows operate under minimal read-only permissions (`contents: read`).

For details on vulnerability reporting and security standards, please see [SECURITY.md](SECURITY.md).

---

## Documentation

- [User & Operational Guide](docs/USER_GUIDE.md)
- [Security Policy](SECURITY.md)
- [License](LICENSE)
