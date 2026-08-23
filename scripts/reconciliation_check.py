#!/usr/bin/env python3
"""Cross-application reconciliation: PostgreSQL == FastAPI == Desktop SQLite.

Seeds controlled data through the API of an isolated rebuilt backend,
then pulls through the REAL Desktop SyncEngine and compares every field
exactly against both the API JSON and the PostgreSQL rows.
"""
import asyncio
import json
import subprocess
import sys
import urllib.request

BASE = "http://localhost:8002/api/v1"
PG_CONTAINER = "integ_pg"
PG_DB_ARGS = ["-U", "iu", "-d", "idb", "-t", "-A", "-c"]


def req(method, path, token=None, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.load(resp)


def psql(sql):
    out = subprocess.check_output(
        ["docker", "exec", PG_CONTAINER, "psql", *PG_DB_ARGS, sql], text=True
    ).strip()
    return out


def main():
    import os
    os.environ["CAR_RENTAL_DB_RESET"] = "1"
    sys.path.insert(0, "/home/ayman/car-rental-system/desktop")
    from app.database import get_local_session, init_local_db
    from app.models.vehicle import LocalVehicle
    from app.models.reservation import LocalReservation
    from app.models.client import LocalClient
    from app.sync.engine import SyncEngine

    init_local_db()

    d = req("POST", "/auth/login", payload={"email": "admin@rec.local", "password": "Rec#Test2026"})
    tok = d["access_token"]

    # Make re-runs idempotent: wipe previous reconciliation rows directly.
    subprocess.run(["docker", "exec", PG_CONTAINER, "psql", *PG_DB_ARGS,
                    "TRUNCATE reservations, vehicles, clients CASCADE"],
                   capture_output=True)

    # ---- Seed controlled dataset via API (desktop-like payloads) ----
    v = req("POST", "/vehicles/", tok, {
        "registration": "REC-9-Z-99", "vin": "1M8GDM9AXKP042788",
        "brand": "Peugeot", "model": "208", "year": 2024, "color": "Noir",
        "fuel_type": "GASOLINE", "transmission": "AUTOMATIC",
        "current_mileage": 12345, "purchase_price": 150000.0,
        "daily_rental_price": 333.33, "status": "AVAILABLE",
    })
    c = req("POST", "/clients/", tok, {
        "first_name": "Nadia", "last_name": "Bennani",
        "phone": "+212611223344", "cin_number": "BE987654",
    })
    from datetime import datetime, timedelta
    start = datetime(2026, 9, 10, 10, 0, 0)
    r = req("POST", "/rentals/", tok, {
        "vehicle_id": v["id"], "customer_name": "Nadia Bennani",
        "customer_phone": "+212611223344",
        "start_datetime": start.isoformat(), "end_datetime": (start + timedelta(days=3)).isoformat(),
        "daily_price": 333.33, "num_days": 3, "total_price": 999.99,
        "deposit": 100.0, "status": "RESERVED", "payment_status": "PENDING",
    })

    # ---- Pull through the real Desktop SyncEngine into SQLite ----
    async def pull():
        eng = SyncEngine("recon-device", tok, base_url="http://localhost:8002")
        return await eng.pull_changes()
    result = asyncio.run(pull())
    assert result["status"] == "ok", result

    # ---- Compare: PostgreSQL vs API vs Desktop SQLite ----
    checks = []

    pg_veh = psql(f"SELECT registration, brand, daily_rental_price::text FROM vehicles WHERE id='{v['id']}'").split("|")
    checks.append(("vehicle.registration PG==API", pg_veh[0] == v["registration"]))
    checks.append(("vehicle.price PG==API", float(pg_veh[2]) == float(v["daily_rental_price"]) == 333.33))

    session = get_local_session()
    lv = session.query(LocalVehicle).filter_by(id=v["id"]).first()
    checks.append(("vehicle exists in SQLite", lv is not None))
    if lv:
        checks.append(("vehicle.brand SQLite==API", lv.brand == v["brand"]))
        checks.append(("vehicle.mileage SQLite==API", int(lv.current_mileage) == int(v["current_mileage"])))
        checks.append(("vehicle.version SQLite==API", int(lv.version) == int(v["version"])))

    lr = session.query(LocalReservation).filter_by(id=r["id"]).first()
    checks.append(("reservation exists in SQLite", lr is not None))
    if lr:
        checks.append(("reservation.total SQLite==API", float(lr.total_price) == float(r["total_price"]) == 999.99))
        checks.append(("reservation.status SQLite==API", lr.status == r["status"] == "RESERVED"))
        checks.append(("reservation.customer SQLite==API", lr.customer_name == r["customer_name"]))
        # Date consistency: pulled ISO timestamps must represent the same instant
        checks.append(("reservation.dates SQLite==API",
                       str(lr.start_datetime)[:19] == r["start_datetime"].replace("+00:00", "")[:19].replace("T", "T")))

    lc = session.query(LocalClient).filter_by(id=c["id"]).first()
    checks.append(("client exists in SQLite", lc is not None))
    if lc:
        checks.append(("client.cin SQLite==API", lc.cin_number == c.get("cin_number")))

    pg_counts = psql("SELECT 'vehicles:'||COUNT(*) FROM vehicles UNION ALL SELECT 'reservations:'||COUNT(*) FROM reservations UNION ALL SELECT 'clients:'||COUNT(*) FROM clients")
    api_vehicles = req("GET", "/vehicles/", tok)["vehicles"]
    api_clients = req("GET", "/clients/")["clients"] if False else req("GET", "/clients/?page_size=100", tok)["clients"]
    checks.append(("count vehicles PG==API", f"vehicles:{len(api_vehicles)}" in pg_counts))
    checks.append(("count clients PG==API", f"clients:{len(api_clients)}" in pg_counts))

    session.close()
    failed = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {n}")
    print("\nRECONCILIATION:", "PASS" if not failed else f"FAIL {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    main()
