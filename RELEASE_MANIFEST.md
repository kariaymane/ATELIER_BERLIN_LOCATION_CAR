# RELEASE MANIFEST

| Field | Value |
|---|---|
| Git branch | `main` |
| Git SHA | `7ebde59` (fix(revenue): unify canonical pro-rata business rule, fix silent dashboard mismatch, add release gates) |
| Build date (UTC) | 2026-09-03 ~01:05 |
| Tree state | clean (committed) |

## Android

| Field | Value |
|---|---|
| File | `ATELIER_BERLIN_LOCATION_CAR_7ebde59.apk` |
| Type | debug-signed (`debugConfig`) |
| Size | 23,375,146 bytes |
| SHA256 | `254d1b5ad2141ff6daccfa2b0b8f29c7cfd222717aa2ec8ce0d6619dfe9fa816` |
| Contains | Canonical pro-rata revenue parity, RevenueEngine parity tests against 33 golden vectors, FleetStatus timezone normalization |

## Windows

| Field | Value |
|---|---|
| ZIP | `ATELIER_BERLIN_LOCATION_CAR_WINDOWS_7ebde59.zip` |
| ZIP size | 61,951,742 bytes |
| ZIP SHA256 | `86d4967ad34668419e929623971a15d4564471f3e3b0758839f2b2a040658312` |
| EXE | `ATELIER_BERLIN_LOCATION_CAR/ATELIER_BERLIN_LOCATION_CAR.exe` |
| EXE size | 9,150,336 bytes |
| EXE SHA256 | `4b79aafbff3dfe7e8deb3cde5152d781fe7cddd3337b0b23420ad69650d4dcc2` |
| Contains | Canonical pro-rata dashboard revenue calculation, ServerContractMismatchError handling, prominent mismatch warning, timezone wall-clock preservation for Casablanca |

## Supersedes

Prior artifacts: `ATELIER_BERLIN_LOCATION_CAR_20f29fb.apk`, `ATELIER_BERLIN_LOCATION_CAR_WINDOWS_20f29fb.zip`, `ATELIER_BERLIN_LOCATION_CAR_6ba055c.apk`, `ATELIER_BERLIN_LOCATION_CAR_WINDOWS_6ba055c.zip`, and older builds.

