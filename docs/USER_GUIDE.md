# User & Operational Guide

## Overview

**ATELIER BERLIN LOCATION CAR** is a cross-platform car rental management system designed for vehicle fleet operations, reservation scheduling, client management, and maintenance tracking.

---

## System Components

| Component | Platform / Technology | Purpose |
|---|---|---|
| **Desktop Application** | Windows / Linux (PySide6 / Qt) | Primary management workstation interface for fleet operators |
| **Mobile Application** | Android (Kotlin / Jetpack Compose) | Mobile companion for fleet status and overview |
| **Backend API** | FastAPI / Python | Central business logic, REST API, WebSockets, and authentication |
| **Database** | PostgreSQL | Authoritative relational data store |
| **Sync Engine** | Background Client Worker | Transparent synchronization between desktop workstations and backend |

---

## Key Features

- **Dashboard**: Real-time fleet metrics (active rentals, committed reservations, vehicles in maintenance, available fleet).
- **Vehicle Management**: Comprehensive vehicle inventory, registration records, status tracking, and photo attachments.
- **Reservation Workflow**: Reservation creation, active rental lifecycle, automatic double-booking prevention, and client record linking.
- **Maintenance Tracking**: Scheduling and execution of routine maintenance, repairs, and inspections with automatic fleet status updates.
- **Secure Authentication**: Role-Based Access Control (RBAC), Argon2id password hashing, short-lived access tokens, and rotating refresh tokens.
- **Client & Document Handling**: Management of client identities (CIN, driving license, contract documents) with cryptographic verification.
- **Resilient Connectivity**: Client-side retry policies, automatic reconnection, and offline resilience during network interruptions.

---

## Desktop Application Setup (Windows)

1. Extract the release archive `ATELIER_BERLIN_LOCATION_CAR_WINDOWS.zip`.
2. Launch `ATELIER_BERLIN_LOCATION_CAR.exe`.
3. Enter your assigned operator or administrator credentials on the login screen.
4. If Windows SmartScreen displays a verification prompt for an ad-hoc build, select **More info** -> **Run anyway**.

---

## Mobile Application Setup (Android)

1. Transfer the APK package to the Android device.
2. Install the package (enable "Install unknown apps" in system settings if prompted).
3. Open the app and log in with your credentials.
4. The mobile application connects to the secure backend service to stream live fleet data.

---

## Operational Notes

- **Network Connectivity**: The client applications communicate with the backend server via secure HTTPS/WSS channels.
- **Double-Booking Guard**: The system enforces strict scheduling validation; overlapping active periods for the same vehicle are automatically prevented.
- **Access Control**: User accounts must remain individualized to ensure audit trail integrity across all fleet modifications.
