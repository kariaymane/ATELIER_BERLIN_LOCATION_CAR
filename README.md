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
\`\`\`bash
cd backend
cp ../.env.example .env # Update credentials
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
\`\`\`

### Desktop
\`\`\`bash
cd desktop
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$(pwd)
python app/main.py
\`\`\`

### Mobile
\`\`\`bash
cd mobile
./gradlew clean assembleDebug
\`\`\`

## Testing
Run \`pytest\` in the \`backend\` and \`desktop\` directories respectively to execute the test suites.
