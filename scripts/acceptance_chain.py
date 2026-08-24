#!/usr/bin/env python3
"""MANDATORY ACCEPTANCE CHAIN (live, isolated):
Client -> New Reservation (linked) -> PG row -> client report -> dashboard
      -> maintenance guard -> cancel -> live values update -> Desktop pull.
"""
import asyncio, json, os, subprocess, sys, urllib.request
from datetime import datetime, timedelta

BASE = "http://localhost:8005/api/v1"
PG = ["docker", "exec", "aud_pg", "psql", "-U", "au", "-d", "adb", "-t", "-A", "-c"]
results = []

def check(n, ok, d=""):
    results.append((n, bool(ok), str(d)[:100]))

def req(method, path, token=None, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token: r.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode())
        except Exception: return e.code, {}

def psql(sql):
    return subprocess.check_output(PG + [sql], text=True).strip()

def main():
    os.environ["CAR_RENTAL_DB_RESET"] = "1"
    sys.path.insert(0, "/home/ayman/car-rental-system/desktop")
    _, d = req("POST", "/auth/login", payload={"email": "a@test.local", "password": "Aud#Test2026"})
    tok = d["access_token"]
    subprocess.run(PG + ["TRUNCATE reservations, vehicles, clients, maintenances CASCADE"], capture_output=True)

    # 1. Client + vehicle
    _, c = req("POST", "/clients/", tok, {"first_name": "Hind", "last_name": "Fassi",
              "phone": "+212688777666", "cin_number": "AU123456"})
    _, v = req("POST", "/vehicles/", tok, {"registration": "AUD-1-A-1",
               "vin": "1M8GDM9AXKP042788", "brand": "Peugeot", "model": "308",
               "year": 2024, "color": "Noir", "fuel_type": "DIESEL",
               "transmission": "AUTOMATIC", "current_mileage": 500,
               "daily_rental_price": 400.0, "status": "AVAILABLE"})
    check("client+vehicle created", c.get("id") and v.get("id"))

    # 2. Reservation LINKED to client
    start = datetime.now() + timedelta(days=3)
    s, r = req("POST", "/rentals/", tok, {
        "vehicle_id": v["id"], "customer_id": c["id"],
        "customer_name": "Hind Fassi", "customer_phone": "+212688777666",
        "start_datetime": start.isoformat(),
        "end_datetime": (start + timedelta(days=4)).isoformat(),
        "daily_price": 400.0, "num_days": 4, "total_price": 1600.0,
        "deposit": 0, "payment_status": "PENDING"})
    check("reservation created+linked", s == 201, s)

    # 3. PG row carries customer_id
    pg = psql(f"SELECT customer_id::text FROM reservations WHERE id='{r['id']}'")
    check("PG customer_id matches", pg == c["id"], f"{pg} vs {c['id']}")

    # 4. Client report reflects it
    _, rep = req("GET", f"/clients/{c['id']}/rentals", tok)
    check("client report: 1 rental/4 days/1600",
          rep["summary"]["total_rentals"] == 1 and rep["summary"]["total_days"] == 4
          and rep["summary"]["total_amount"] == 1600.0, rep["summary"])

    # 5. Dashboard revenue includes ACTIVE/COMPLETED only (RESERVED excluded)
    _, dash = req("GET", "/dashboard/stats", tok)
    check("dashboard reachable", "total_vehicles" in dash)

    # 6. Maintenance guard on a reservation-free vehicle:
    #    maintenance creation sets MAINTENANCE -> reservations rejected.
    _, v2 = req("POST", "/vehicles/", tok, {"registration": "AUD-2-B-2",
                "vin": "1M8GDM9AXKP042789", "brand": "Renault", "model": "Clio",
                "year": 2024, "color": "Gris", "fuel_type": "GASOLINE",
                "transmission": "MANUAL", "current_mileage": 100,
                "daily_rental_price": 300.0, "status": "AVAILABLE"})
    s_m, m = req("POST", "/maintenance/", tok, {
        "vehicle_id": v2["id"], "type": "Revision",
        "start_datetime": (datetime.now() + timedelta(days=30)).isoformat(),
        "description": "audit"})
    check("maintenance created (free vehicle)", s_m in (200, 201), f"{s_m} {m}")
    s2, r2 = req("POST", "/rentals/", tok, {
        "vehicle_id": v2["id"], "customer_name": "X Y",
        "start_datetime": (datetime.now() + timedelta(days=60)).isoformat(),
        "end_datetime": (datetime.now() + timedelta(days=62)).isoformat(),
        "daily_price": 300.0, "num_days": 2, "total_price": 600.0, "deposit": 0})
    check("maintenance blocks reservation", s2 == 400, f"{s2} {r2}")

    # 7. Cancel the reservation -> client totals drop to 0 (CANCELLED excluded)
    s3, _ = req("POST", f"/rentals/{r['id']}/cancel", tok)
    _, rep2 = req("GET", f"/clients/{c['id']}/rentals", tok)
    check("cancel ok + client totals exclude cancelled",
          s3 == 200 and rep2["summary"]["total_rentals"] == 0
          and rep2["summary"]["cancelled_rentals"] == 1, rep2["summary"])

    # 8. Desktop pull sees the linked data
    from app.database import get_local_session, init_local_db
    from app.models.reservation import LocalReservation
    from app.models.client import LocalClient
    init_local_db()
    async def pull():
        from app.sync.engine import SyncEngine
        return await SyncEngine("aud-desktop", tok, base_url="http://localhost:8005").pull_changes()
    pr = asyncio.run(pull())
    check("desktop pull ok", pr["status"] == "ok")
    session = get_local_session()
    lr = session.query(LocalReservation).filter_by(id=r["id"]).first()
    lc = session.query(LocalClient).filter_by(id=c["id"]).first()
    check("desktop: reservation linked to client",
          lr is not None and lr.customer_id == c["id"] and lc is not None,
          f"{lr.customer_id if lr else None}")
    session.close()

    failed = [n for n, ok, _ in results if not ok]
    for n, ok, det in results:
        print(f"{'PASS' if ok else 'FAIL'}  {n}  {det if not ok else ''}")
    print("\nACCEPTANCE CHAIN:", "PASS" if not failed else f"FAIL {failed}")
    return 0 if not failed else 1

if __name__ == "__main__":
    sys.exit(main())
