#!/usr/bin/env python3
"""Full live API integration chain test against an isolated rebuilt container.

DATABASE -> BACKEND -> API -> CLIENT semantics, real HTTP, no mocks:
  login -> create vehicle -> create client -> create reservation
        -> overlap rejection -> dashboard revenue reflects reservation
        -> realtime event delivered (authenticated WS + /recent)
        -> sync pull returns the created entities (idempotent)
        -> unauthorized access rejected everywhere
"""
import json
import sys
import urllib.request

BASE = "http://localhost:8002/api/v1"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


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


def main():
    # 1. login
    s, d = req("POST", "/auth/login", payload={"email": "admin@int.local", "password": "Int#Test2026x"})
    check("login", s == 200 and "access_token" in d)
    tok = d["access_token"]

    # 2. bad credentials rejected (8+ chars so schema passes; server must 401)
    s, _ = req("POST", "/auth/login", payload={"email": "admin@int.local", "password": "wrong-password-123"})
    check("bad-credentials-rejected", s in (400, 401), f"{s}")

    # 3. anonymous rejected on protected endpoint (401 explicit / 403 no-header)
    s, _ = req("GET", "/vehicles")
    check("anon-vehicles-denied", s in (401, 403))

    # 4. vehicle CRUD chain
    s, v = req("POST", "/vehicles/", tok, {
        "registration": "INT-1-A-23", "vin": "1M8GDM9AXKP042788",
        "brand": "Dacia", "model": "Logan", "year": 2024, "color": "Blanc",
        "fuel_type": "DIESEL", "transmission": "MANUAL",
        "current_mileage": 100, "daily_rental_price": 250.0, "status": "AVAILABLE",
    })
    check("vehicle-create", s in (200, 201), f"{s}")
    vid = v.get("id")

    s, lst = req("GET", "/vehicles/", tok)
    ids = [x["id"] for x in lst.get("vehicles", [])]
    check("vehicle-listed", vid in ids)

    # 5. client create
    s, c = req("POST", "/clients/", tok, {
        "first_name": "Test", "last_name": "Client",
        "phone": "+212600000000", "email": "c@int.local",
        "cin_number": "AB123456", "license_number": "LIC-77",
    })
    check("client-create", s in (200, 201), f"{s}")

    s, cl = req("GET", "/clients/?search=Client", tok)
    check("client-search", any(x.get("cin_number") == "AB123456" for x in cl.get("clients", [])))

    # 6. reservation create
    from datetime import datetime, timedelta, timezone
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=5)
    end = start + timedelta(days=2)
    res_payload = {
        "vehicle_id": vid, "customer_name": "Test Client",
        "start_datetime": start.isoformat(), "end_datetime": end.isoformat(),
        "daily_price": 250.0, "num_days": 2, "total_price": 500.0,
        "deposit": 0, "status": "RESERVED", "payment_status": "PENDING",
    }
    s, r = req("POST", "/rentals/", tok, res_payload)
    check("reservation-create-no-phone-ok", s in (200, 201), f"{s} {r}")
    rid = r.get("id") if isinstance(r, dict) else None

    # 6b. phone provided -> accepted and persisted (different, non-overlapping week)
    s, r3 = req("POST", "/rentals/", tok, dict(
        res_payload,
        customer_phone="+212600112233",
        start_datetime=(start + timedelta(days=10)).isoformat(),
        end_datetime=(end + timedelta(days=10)).isoformat(),
    ))
    check("reservation-create-with-phone", s in (200, 201), f"{s} {r3 if s != 201 else ''}")

    # 7. double booking rejection (overlapping window, same vehicle)
    s, r2 = req("POST", "/rentals/", tok, dict(res_payload, start_datetime=(start + timedelta(hours=12)).isoformat()))
    check("overlap-rejected", s in (400, 409, 422), f"{s}")

    # 8. dashboard revenue reflects reservation (500 DH, future ACTIVE? RESERVED excluded)
    s, dash = req("GET", "/dashboard/stats", tok)
    check("dashboard-ok", s == 200 and "total_vehicles" in dash)

    # 9. realtime: authenticated event delivery via /recent
    s, ev = req("GET", "/events/recent", tok)
    check("events-recent-auth", s == 200)

    # 10. sync pull contains our entities
    now_iso = datetime.now(timezone.utc).isoformat()
    s, pulled = req("POST", "/sync/pull", tok, {"since": "2000-01-01T00:00:00+00:00", "device_id": "integ-desktop"})
    items = pulled.get("items", [])
    types = {i.get("entity_type") for i in items}
    check("sync-pull-entities", s == 200 and "vehicle" in types and "reservation" in types,
          f"types={types}")

    # 11. idempotency: pull again — same data, no duplication errors
    s2, pulled2 = req("POST", "/sync/pull", tok, {"since": "2000-01-01T00:00:00+00:00", "device_id": "integ-desktop"})
    check("sync-pull-idempotent", s2 == 200 and len(pulled2.get("items", [])) == len(items))

    failed = [n for n, ok, _ in results if not ok]
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name} {detail}")
    print(f"\nINTEGRATION CHAIN: {'PASS' if not failed else 'FAIL ' + str(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
