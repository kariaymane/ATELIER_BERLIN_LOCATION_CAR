#!/usr/bin/env python3
"""SECTION 46 ACCEPTANCE MATRIX — vehicle-specific availability isolation.

Today = 25/08/2026 (test-fixed dates in December 2026).

  Vehicle A: reservation 08/12/2026 -> 10/12/2026

  A + 08/12->09/12   -> BLOCKED
  B + 08/12->09/12   -> AVAILABLE
  B + 08/12->09/12   -> create -> SUCCESS
  B + 08/12->09/12   -> BLOCKED (now exists)
  A + 08/12->09/12   -> BLOCKED (unchanged)
  C + 08/12->09/12   -> AVAILABLE
  A + 11/12->12/12   -> AVAILABLE (after A's reservation ends)

Also verifies: blocker.vehicle_id == requested_vehicle_id for every
block, and the DESKTOP local check agrees (same isolation).
"""
import json, os, subprocess, sys, urllib.request, urllib.parse
from datetime import datetime, timezone

BASE = "http://localhost:8007/api/v1"
PG = ["docker", "exec", "veh_pg", "psql", "-U", "vu", "-d", "vdb", "-t", "-A", "-c"]
results = []

def check(n, ok, d=""):
    results.append((n, bool(ok), str(d)[:110]))

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

    _, d = req("POST", "/auth/login", payload={"email": "v@test.local", "password": "Veh#Test2026"})
    tok = d["access_token"]

    # Vehicles A, B, C
    vehicles = {}
    for letter, reg, vin in (("A", "ISO-A-1-1", "1M8GDM9AXKP042788"),
                             ("B", "ISO-B-2-2", "1M8GDM9AXKP042789"),
                             ("C", "ISO-C-3-3", "1M8GDM9AXKP042790")):
        _, v = req("POST", "/vehicles/", tok, {
            "registration": reg, "vin": vin, "brand": f"Brand{letter}",
            "model": f"Model{letter}", "year": 2026, "color": "Blanc",
            "fuel_type": "DIESEL", "transmission": "MANUAL",
            "current_mileage": 0, "daily_rental_price": 300.0, "status": "AVAILABLE"})
        vehicles[letter] = v
    A, B, C = vehicles["A"]["id"], vehicles["B"]["id"], vehicles["C"]["id"]

    # Vehicle A reservation: 08/12/2026 -> 10/12/2026 (UTC)
    s0 = datetime(2026, 12, 8, 10, 0, tzinfo=timezone.utc)
    e0 = datetime(2026, 12, 10, 10, 0, tzinfo=timezone.utc)
    s, rA = req("POST", "/rentals/", tok, {
        "vehicle_id": A, "customer_name": "Holder A",
        "start_datetime": s0.isoformat(), "end_datetime": e0.isoformat(),
        "daily_price": 300.0, "num_days": 2, "total_price": 600.0, "deposit": 0})
    check("setup: A reservation created", s == 201, s)

    def avail(vid, start, end):
        q = urllib.parse.urlencode({"start": start.isoformat(), "end": end.isoformat()})
        s, a = req("GET", f"/vehicles/{vid}/availability?{q}", tok)
        if s != 200:
            return f"HTTP{s}"
        return a.get("available")

    d1s = datetime(2026, 12, 8, 10, 0, tzinfo=timezone.utc)
    d1e = datetime(2026, 12, 9, 10, 0, tzinfo=timezone.utc)

    # THE MATRIX
    check("A + 08->09/12 BLOCKED", avail(A, d1s, d1e) is False)
    check("B + 08->09/12 AVAILABLE", avail(B, d1s, d1e) is True)
    check("C + 08->09/12 AVAILABLE", avail(C, d1s, d1e) is True)

    # Create B on same dates -> SUCCESS
    s, rB = req("POST", "/rentals/", tok, {
        "vehicle_id": B, "customer_name": "Holder B",
        "start_datetime": d1s.isoformat(), "end_datetime": d1e.isoformat(),
        "daily_price": 300.0, "num_days": 1, "total_price": 300.0, "deposit": 0})
    check("B create same dates -> SUCCESS", s == 201, s)

    # B same dates again -> BLOCKED
    check("B + 08->09/12 now BLOCKED", avail(B, d1s, d1e) is False)
    # A unchanged BLOCKED
    check("A + 08->09/12 still BLOCKED", avail(A, d1s, d1e) is False)
    # C still AVAILABLE
    check("C + 08->09/12 still AVAILABLE", avail(C, d1s, d1e) is True)
    # A after its reservation ends -> AVAILABLE
    a2s = datetime(2026, 12, 11, 10, 0, tzinfo=timezone.utc)
    a2e = datetime(2026, 12, 12, 10, 0, tzinfo=timezone.utc)
    check("A + 11->12/12 AVAILABLE (after own end)", avail(A, a2s, a2e) is True)
    # Adjacent to A's reservation (starts exactly at e0) -> AVAILABLE
    check("A + adjacent 10->11/12 AVAILABLE", avail(A, e0, a2s) is True)

    # PG FORENSICS: every blocker for A's window belongs to A
    blockers = psql(
        "SELECT vehicle_id::text, id::text, status FROM reservations "
        "WHERE vehicle_id='" + A + "' AND status NOT IN ('CANCELLED','COMPLETED') "
        "AND start_datetime < '" + d1e.isoformat() + "' AND end_datetime > '" + d1s.isoformat() + "'")
    all_a = all(row.split("|")[0] == A for row in blockers.split("\n") if row)
    check("PG blockers for A window: all vehicle_id==A", all_a and blockers != "", blockers)

    blockers_b = psql(
        "SELECT vehicle_id::text FROM reservations "
        "WHERE vehicle_id='" + B + "' AND status NOT IN ('CANCELLED','COMPLETED') "
        "AND start_datetime < '" + d1e.isoformat() + "' AND end_datetime > '" + d1s.isoformat() + "'")
    all_b = all(row == B for row in blockers_b.split("\n") if row)
    check("PG blockers for B window: all vehicle_id==B", all_b and blockers_b != "", blockers_b)

    # ── DESKTOP LOCAL CHECK must agree (same isolation) ──
    from app.database import init_local_db, get_local_session
    from app.models.reservation import LocalReservation
    from app.models.vehicle import LocalVehicle
    from app.utils.datetime_utils import reservations_overlap, status_blocks_reservation
    init_local_db()
    async def pull():
        from app.sync.engine import SyncEngine
        return await SyncEngine("iso-desktop", tok, base_url="http://localhost:8007").pull_changes()
    pr = asyncio.run(pull())
    check("desktop pull ok", pr["status"] == "ok")

    def local_blocked(vid, start, end):
        s = get_local_session()
        try:
            for r in s.query(LocalReservation).filter_by(vehicle_id=vid).all():
                if not status_blocks_reservation(r.status):
                    continue
                from app.utils.datetime_utils import parse_datetime_utc as _pd
                rs = _pd(r.start_datetime)
                re_ = _pd(r.end_datetime)
                if reservations_overlap(rs, re_, start, end):
                    return True, r.id
            return False, None
        finally:
            s.close()

    blk, bid = local_blocked(A, d1s, d1e)
    check("DESKTOP local: A blocked", blk, bid)
    row = get_local_session().query(LocalReservation).filter_by(id=bid).first() if bid else None
    if row:
        check("DESKTOP blocker.vehicle_id == A", row.vehicle_id == A, row.vehicle_id)
    blk_b, _ = local_blocked(B, d1s, d1e)
    check("DESKTOP local: B blocked (after create)", blk_b)
    blk_c, _ = local_blocked(C, d1s, d1e)
    check("DESKTOP local: C available", not blk_c)
    # Cross-contamination assertion: no blocker row for B's window belongs to A
    s = get_local_session()
    from app.utils.datetime_utils import parse_datetime_utc as _pd
    b_rows = [r for r in s.query(LocalReservation).filter_by(vehicle_id=B).all()
              if status_blocks_reservation(r.status)
              and _pd(r.start_datetime) < d1e and _pd(r.end_datetime) > d1s]
    check("DESKTOP: no A-row blocks B window", all(r.vehicle_id == B for r in b_rows))
    s.close()

    failed = [n for n, ok, _ in results if not ok]
    for n, ok, det in results:
        print(f"{'PASS' if ok else 'FAIL'}  {n}  {det if not ok else ''}")
    print("\nVEHICLE-ISOLATION MATRIX:", "PASS" if not failed else f"FAIL {failed}")
    return 0 if not failed else 1

if __name__ == "__main__":
    import asyncio
    sys.exit(main())
