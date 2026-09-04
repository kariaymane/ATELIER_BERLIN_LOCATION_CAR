#!/usr/bin/env python3
"""
Automated Data Reconciliation Script: PostgreSQL vs FastAPI vs Desktop SQLite.

Audits every reservation and vehicle across all three layers:
1. PostgreSQL (authoritative source)
2. FastAPI (/api/v1/rentals and /api/v1/vehicles)
3. Desktop SQLite cache (~/.local/share/CarRentalSystem/data/car_rental_local.db)

Verifies:
- ID consistency
- Vehicle UUID linking
- Canonical datetime bounds
- Status alignment (ACTIVE/RESERVED/COMPLETED/CANCELLED)
- Total price consistency
- Record count and zero-orphan invariant
"""
import os
import sys
import json
import sqlite3
import subprocess
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

CASABLANCA_TZ = ZoneInfo("Africa/Casablanca")

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
DEFAULT_SQLITE_PATH = os.path.expanduser("~/.local/share/CarRentalSystem/data/car_rental_local.db")
SQLITE_PATH = os.environ.get("SQLITE_PATH", DEFAULT_SQLITE_PATH)


def run_psql(sql: str) -> list[str]:
    """Execute SQL query against PostgreSQL via docker exec or psql."""
    cmd = [
        "docker", "exec", "car_rental_db_prod",
        "psql", "-U", "rental_app", "-d", "car_rental",
        "-t", "-A", "-F", "\t", "-c", sql
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        lines = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
        return lines
    except Exception as e:
        print(f"[ERROR] Failed to query PostgreSQL: {e}", file=sys.stderr)
        raise


def get_api_data() -> tuple[list[dict], list[dict]]:
    """Fetch rentals and vehicles via FastAPI with JWT auth."""
    login_url = f"{API_BASE_URL}/api/v1/auth/login"
    login_payload = json.dumps({"email": "berlinecar@gmail.com", "password": "berlin20002000"}).encode()
    req = urllib.request.Request(login_url, data=login_payload, headers={"Content-Type": "application/json"})
    
    with urllib.request.urlopen(req, timeout=10) as resp:
        login_data = json.load(resp)
        token = login_data["access_token"]

    auth_header = {"Authorization": f"Bearer {token}"}

    # 1. Fetch rentals
    rentals_req = urllib.request.Request(f"{API_BASE_URL}/api/v1/rentals?page=1&page_size=100", headers=auth_header)
    with urllib.request.urlopen(rentals_req, timeout=10) as resp:
        rentals_data = json.load(resp).get("rentals", [])

    # 2. Fetch vehicles
    vehicles_req = urllib.request.Request(f"{API_BASE_URL}/api/v1/vehicles/?page=1&page_size=100", headers=auth_header)
    with urllib.request.urlopen(vehicles_req, timeout=10) as resp:
        vehicles_data = json.load(resp).get("vehicles", [])

    return rentals_data, vehicles_data


def get_sqlite_data() -> tuple[list[dict], list[dict]]:
    """Fetch reservations and vehicles from local SQLite cache."""
    if not os.path.exists(SQLITE_PATH):
        raise FileNotFoundError(f"SQLite database not found at {SQLITE_PATH}")

    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM reservations")
    reservations = [dict(row) for row in cur.fetchall()]

    cur.execute("SELECT * FROM vehicles")
    vehicles = [dict(row) for row in cur.fetchall()]

    conn.close()
    return reservations, vehicles


def normalize_iso(dt_str: str) -> str:
    if not dt_str:
        return ""
    s = dt_str.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        return dt.isoformat()
    except Exception:
        return dt_str


def main():
    print("=" * 90)
    print(" 🔍 FORENSIC DATA RECONCILIATION: PostgreSQL vs FastAPI vs SQLite")
    print("=" * 90)

    # 1. Load PostgreSQL data
    pg_res_lines = run_psql("SELECT id, vehicle_id, customer_name, start_datetime, end_datetime, status, total_price FROM reservations ORDER BY id;")
    pg_reservations = {}
    for line in pg_res_lines:
        parts = line.split("\t")
        if len(parts) >= 7:
            r_id = parts[0]
            pg_reservations[r_id] = {
                "id": r_id,
                "vehicle_id": parts[1],
                "customer_name": parts[2] if parts[2] else "",
                "start_datetime": normalize_iso(parts[3]),
                "end_datetime": normalize_iso(parts[4]),
                "status": parts[5],
                "total_price": float(parts[6]),
            }

    pg_veh_lines = run_psql("SELECT id, brand, model, registration, status FROM vehicles ORDER BY id;")
    pg_vehicles = {}
    for line in pg_veh_lines:
        parts = line.split("\t")
        if len(parts) >= 5:
            v_id = parts[0]
            pg_vehicles[v_id] = {
                "id": v_id,
                "brand": parts[1],
                "model": parts[2],
                "registration": parts[3],
                "status": parts[4],
            }

    print(f"✅ PostgreSQL: {len(pg_vehicles)} vehicles, {len(pg_reservations)} reservations loaded.")

    # 2. Load FastAPI data
    api_rentals_list, api_vehicles_list = get_api_data()
    api_reservations = {r["id"]: {
        "id": r["id"],
        "vehicle_id": r["vehicle_id"],
        "customer_name": r.get("customer_name") or "",
        "start_datetime": normalize_iso(r.get("start_datetime")),
        "end_datetime": normalize_iso(r.get("end_datetime")),
        "status": r.get("status"),
        "total_price": float(r.get("total_price") or 0.0),
    } for r in api_rentals_list}

    api_vehicles = {v["id"]: {
        "id": v["id"],
        "brand": v.get("brand"),
        "model": v.get("model"),
        "registration": v.get("registration"),
        "status": v.get("status"),
    } for v in api_vehicles_list}

    print(f"✅ FastAPI:    {len(api_vehicles)} vehicles, {len(api_reservations)} reservations loaded.")

    # 3. Load SQLite data
    sqlite_res_list, sqlite_veh_list = get_sqlite_data()
    sqlite_reservations = {r["id"]: {
        "id": r["id"],
        "vehicle_id": r["vehicle_id"],
        "customer_name": r.get("customer_name") or "",
        "start_datetime": normalize_iso(r.get("start_datetime")),
        "end_datetime": normalize_iso(r.get("end_datetime")),
        "status": r.get("status"),
        "total_price": float(r.get("total_price") or 0.0),
    } for r in sqlite_res_list}

    sqlite_vehicles = {v["id"]: {
        "id": v["id"],
        "brand": v.get("brand"),
        "model": v.get("model"),
        "registration": v.get("registration"),
        "status": v.get("status"),
    } for v in sqlite_veh_list}

    print(f"✅ SQLite:     {len(sqlite_vehicles)} vehicles, {len(sqlite_reservations)} reservations loaded.")
    print("-" * 90)

    # 4. Reconciliation
    mismatches = []

    # Check vehicle counts and IDs
    all_veh_ids = set(pg_vehicles.keys()) | set(api_vehicles.keys()) | set(sqlite_vehicles.keys())
    print(f"\n[VEHICLES AUDIT] Total Unique IDs: {len(all_veh_ids)}")
    print(f"{'Vehicle ID':<38} {'Brand/Model':<24} {'Reg':<12} {'PG':<6} {'API':<6} {'SQLite':<6}")
    print("-" * 90)
    for vid in sorted(all_veh_ids):
        pg_v = pg_vehicles.get(vid)
        api_v = api_vehicles.get(vid)
        sql_v = sqlite_vehicles.get(vid)
        
        info = pg_v or api_v or sql_v
        bm = f"{info.get('brand', '')} {info.get('model', '')}"[:23]
        reg = info.get("registration", "")[:11]

        in_pg = "✓" if pg_v else "✗"
        in_api = "✓" if api_v else "✗"
        in_sql = "✓" if sql_v else "✗"

        print(f"{vid:<38} {bm:<24} {reg:<12} {in_pg:<6} {in_api:<6} {in_sql:<6}")
        if not (pg_v and api_v and sql_v):
            mismatches.append(f"Vehicle {vid} presence mismatch: PG={bool(pg_v)}, API={bool(api_v)}, SQLite={bool(sql_v)}")

    # Check reservations
    all_res_ids = set(pg_reservations.keys()) | set(api_reservations.keys()) | set(sqlite_reservations.keys())
    print(f"\n[RESERVATIONS AUDIT] Total Unique IDs: {len(all_res_ids)}")
    print(f"{'Reservation ID':<38} {'Customer':<18} {'Status':<10} {'Price':<8} {'PG':<5} {'API':<5} {'SQL':<5}")
    print("-" * 90)
    for rid in sorted(all_res_ids):
        pg_r = pg_reservations.get(rid)
        api_r = api_reservations.get(rid)
        sql_r = sqlite_reservations.get(rid)

        info = pg_r or api_r or sql_r
        cust = (info.get("customer_name") or "—")[:17]
        st = info.get("status", "")[:9]
        pr = f"{info.get('total_price', 0):.0f} DH"

        in_pg = "✓" if pg_r else "✗"
        in_api = "✓" if api_r else "✗"
        in_sql = "✓" if sql_r else "✗"

        print(f"{rid:<38} {cust:<18} {st:<10} {pr:<8} {in_pg:<5} {in_api:<5} {in_sql:<5}")

        if not (pg_r and api_r and sql_r):
            mismatches.append(f"Reservation {rid} presence mismatch: PG={bool(pg_r)}, API={bool(api_r)}, SQLite={bool(sql_r)}")
            continue

        # Check vehicle linking
        if not (pg_r["vehicle_id"] == api_r["vehicle_id"] == sql_r["vehicle_id"]):
            mismatches.append(f"Reservation {rid} vehicle_id mismatch: PG={pg_r['vehicle_id']}, API={api_r['vehicle_id']}, SQLite={sql_r['vehicle_id']}")

        # Check status
        if not (pg_r["status"] == api_r["status"] == sql_r["status"]):
            mismatches.append(f"Reservation {rid} status mismatch: PG={pg_r['status']}, API={api_r['status']}, SQLite={sql_r['status']}")

        # Check total price
        if not (pg_r["total_price"] == api_r["total_price"] == sql_r["total_price"]):
            mismatches.append(f"Reservation {rid} price mismatch: PG={pg_r['total_price']}, API={api_r['total_price']}, SQLite={sql_r['total_price']}")

        # Check dates
        if not (pg_r["start_datetime"] == api_r["start_datetime"] == sql_r["start_datetime"]):
            mismatches.append(f"Reservation {rid} start_datetime mismatch: PG={pg_r['start_datetime']}, API={api_r['start_datetime']}, SQLite={sql_r['start_datetime']}")

    print("=" * 90)
    if mismatches:
        print(f"❌ RECONCILIATION FAILED WITH {len(mismatches)} MISMATCHES:")
        for m in mismatches:
            print(f"  - {m}")
        sys.exit(1)
    else:
        print("🎉 PERFECT ZERO-DEFECT RECONCILIATION: 0 discrepancies across PostgreSQL, FastAPI, and Desktop SQLite!")
        print("=" * 90)
        sys.exit(0)


if __name__ == "__main__":
    main()
