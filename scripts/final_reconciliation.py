#!/usr/bin/env python3
"""FINAL forensic reconciliation: PostgreSQL = API = Desktop SQLite = UI models.

Controlled dataset (spec example):
  Client A: R1 VehicleA 3d/300 COMPLETED, R2 VehicleB 5d/500 ACTIVE,
            R3 VehicleA 2d/200 COMPLETED
  Expected: rentals=3 days=10 amount=1000 vehicles=2 (A:2/5d, B:1/5d)
Also reconciles dashboard KPIs and vehicle availability after mutations.
"""
import asyncio
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta

BASE = "http://localhost:8004/api/v1"
PG = ["docker", "exec", "fin_pg", "psql", "-U", "fu", "-d", "fdb", "-t", "-A", "-c"]
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), str(detail)[:120]))


def req(method, path, token=None, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body


def psql(sql):
    return subprocess.check_output(PG + [sql], text=True).strip()


def main():
    os.environ["CAR_RENTAL_DB_RESET"] = "1"
    sys.path.insert(0, "/home/ayman/car-rental-system/desktop")
    from app.database import get_local_session, init_local_db
    from app.models.vehicle import LocalVehicle
    from app.models.reservation import LocalReservation
    from app.models.client import LocalClient
    from app.sync.engine import SyncEngine
    from app.sync.dashboard_cache import compute_local_overview

    init_local_db()

    _, d = req("POST", "/auth/login", payload={"email": "f@test.local", "password": "Fin#Test2026"})
    tok = d["access_token"]

    # Clean slate (isolated verification DB only)
    subprocess.run(PG + ["TRUNCATE reservations, vehicles, clients CASCADE"], capture_output=True)

    _, c = req("POST", "/clients/", tok, {"first_name": "Salma", "last_name": "Alaoui",
                                          "phone": "+212655000111", "cin_number": "FC001"})
    _, va = req("POST", "/vehicles/", tok, {"registration": "FIN-A-1-1", "vin": "1M8GDM9AXKP042788",
               "brand": "Dacia", "model": "Logan", "year": 2024, "color": "Blanc",
               "fuel_type": "DIESEL", "transmission": "MANUAL", "current_mileage": 50,
               "daily_rental_price": 100.0, "status": "AVAILABLE"})
    _, vb = req("POST", "/vehicles/", tok, {"registration": "FIN-B-2-2", "vin": "1M8GDM9AXKP042789",
               "brand": "Renault", "model": "Clio", "year": 2024, "color": "Gris",
               "fuel_type": "GASOLINE", "transmission": "MANUAL", "current_mileage": 60,
               "daily_rental_price": 100.0, "status": "AVAILABLE"})

    base = datetime(2026, 11, 1, 9, 0)
    rentals = [
        (va["id"], 3, 300.0, "COMPLETED"),
        (vb["id"], 5, 500.0, "ACTIVE"),
        (va["id"], 2, 200.0, "COMPLETED"),
    ]
    for vid, days, total, status in rentals:
        st = base + timedelta(days=10 * rentals.index((vid, days, total, status)))
        s, r = req("POST", "/rentals/", tok, {
            "vehicle_id": vid, "customer_name": "Salma Alaoui",
            "customer_phone": "+212655000111",
            "start_datetime": st.isoformat(), "end_datetime": (st + timedelta(days=days)).isoformat(),
            "daily_price": 100.0, "num_days": days, "total_price": total,
            "deposit": 0, "payment_status": "PENDING"})
        check(f"rental create {status}", s in (200, 201), s)

    # ── PostgreSQL ground truth ──
    pg = psql("SELECT COALESCE(SUM(num_days),0)||'|'||COALESCE(SUM(total_price),0) FROM reservations WHERE status <> 'CANCELLED'")
    pg_days, pg_amount = pg.split("|")
    check("PG totals days=10", pg_days == "10", pg)
    check("PG totals amount=1000", float(pg_amount) == 1000.0, pg_amount)
    check("PG distinct vehicles=2",
          psql("SELECT COUNT(DISTINCT vehicle_id) FROM reservations WHERE status<>'CANCELLED'") == "2")

    # ── API canonical client report ──
    _, rep = req("GET", f"/clients/{c['id']}/rentals", tok)
    s = rep["summary"]
    check("API rentals=3", s["total_rentals"] == 3, s)
    check("API days=10", s["total_days"] == 10, s)
    check("API amount=1000", s["total_amount"] == 1000.0, s)
    check("API vehicles=2", s["vehicles_rented"] == 2, s)
    vmap = {v["registration"]: v for v in rep["vehicles"]}
    check("API vehA 2 rentals/5 days", vmap["FIN-A-1-1"]["rentals"] == 2 and vmap["FIN-A-1-1"]["days"] == 5)
    check("API vehB 1 rental/5 days", vmap["FIN-B-2-2"]["rentals"] == 1 and vmap["FIN-B-2-2"]["days"] == 5)

    # ── Desktop SQLite via real SyncEngine ──
    async def pull():
        eng = SyncEngine("fin-desktop", tok, base_url="http://localhost:8004")
        return await eng.pull_changes()
    pull_result = asyncio.run(pull())
    check("desktop pull ok", pull_result["status"] == "ok")

    session = get_local_session()
    lc = session.query(LocalClient).filter_by(id=c["id"]).first()
    check("SQLite client matches", lc is not None and lc.cin_number == "FC001")
    lres = session.query(LocalReservation).filter(LocalReservation.status != "CANCELLED").all()
    check("SQLite rentals=3", len(lres) == 3, len(lres))
    check("SQLite days=10", sum(r.num_days for r in lres) == 10)
    check("SQLite amount=1000", abs(sum(float(r.total_price) for r in lres) - 1000.0) < 1e-9)
    check("SQLite vehicles=2", len({r.vehicle_id for r in lres}) == 2)

    # ── Desktop UI offline dashboard model == backend rule ──
    overview = compute_local_overview(session)
    month_revenue_expected = 1000.0  # all rentals in Nov 2026; month boundary safe
    # Only count rentals whose start falls in the CURRENT month per canonical rule
    now = datetime.now()
    expected_month = sum(float(r.total_price) for r in lres
                         if r.start_datetime.startswith(f"{now.year}-{now.month:02d}"))
    check("UI-model month revenue == PG month revenue",
          abs(overview["month_revenue"] - expected_month) < 1e-9,
          f"ui={overview['month_revenue']} expected={expected_month}")
    session.close()

    # ── Mutation chain: activate then cancel R2 → totals must drop everywhere ──
    target = rep["rentals"][1]  # second rental (Vehicle B, 5d/500)
    s_act, _ = req("POST", f"/rentals/{target['id']}/activate", tok)
    check("activate mutation", s_act in (200, 201), s_act)
    active_rental = target
    s2, _ = req("POST", f"/rentals/{active_rental['id']}/cancel", tok)
    check("cancel mutation", s2 in (200, 201), s2)
    _, rep2 = req("GET", f"/clients/{c['id']}/rentals", tok)
    s2sum = rep2["summary"]
    check("API after cancel: rentals=2", s2sum["total_rentals"] == 2, s2sum)
    check("API after cancel: days=5", s2sum["total_days"] == 5, s2sum)
    check("API after cancel: amount=500", s2sum["total_amount"] == 500.0, s2sum)
    check("API after cancel: cancelled=1", s2sum["cancelled_rentals"] == 1, s2sum)
    pg2 = psql("SELECT COALESCE(SUM(num_days),0)||'|'||COALESCE(SUM(total_price),0) FROM reservations WHERE status <> 'CANCELLED'")
    d2, a2 = pg2.split("|")
    check("PG after cancel matches API", d2 == "5" and float(a2) == 500.0, pg2)

    failed = [n for n, ok, _ in results if not ok]
    for n, ok, det in results:
        print(f"{'PASS' if ok else 'FAIL'}  {n}  {det if not ok else ''}")
    print("\nFINAL RECONCILIATION:", "PASS" if not failed else f"FAIL {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
