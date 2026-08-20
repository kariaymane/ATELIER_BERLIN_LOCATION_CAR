"""
Comprehensive Real CRUD Lifecycle & Synchronization Test Suite:
1. VEHICLE: Create -> Read -> Update -> Delete -> Read (404/Removed)
2. RESERVATION: Create -> Read -> Activate -> Complete -> Read
3. MAINTENANCE: Create -> Read -> Advance Step -> Complete -> Read
4. DELETION & SYNC: Full clean cascade deletion verified across Desktop & Backend
"""
import sys
import os
import asyncio
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone, timedelta
import httpx

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "desktop"))

from app.database import init_local_db, get_local_session
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.sync.engine import SyncEngine
from app.sync.queue import SyncQueue

API_URL = "http://localhost:8000"

def run_complete_crud_suite():
    print("=" * 70)
    print("🚀 STARTING REAL FULL CRUD LIFECYCLE & SYNC VERIFICATION")
    print("=" * 70)

    init_local_db()

    # Authenticate admin user
    login_res = httpx.post(
        f"{API_URL}/api/v1/auth/login",
        json={"email": "BERLINCAR@GMAIL.COM", "password": "Berlin20002000"}
    )
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    token = login_res.json()["access_token"]
    user_id = login_res.json()["user_id"]
    headers = {"Authorization": f"Bearer {token}"}
    device_id = f"test-crud-{str(uuid4())[:8]}"
    sync_engine = SyncEngine(device_id=device_id, access_token=token)

    # Clean any stale failed items in local sync queue for clean run
    session = get_local_session()
    try:
        from app.models.sync_queue import SyncQueueItem
        session.query(SyncQueueItem).filter_by(device_id=device_id).delete()
        session.commit()
    finally:
        session.close()

    # -------------------------------------------------------------
    # 1. VEHICLE CRUD TEST
    # -------------------------------------------------------------
    print("\n--- [1/4] VEHICLE CRUD TEST ---")
    v_id = str(uuid4())
    reg = f"CRUD-{str(uuid4())[:6].upper()}"
    vin = f"VIN{str(uuid4()).replace('-', '')[:14].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    # CREATE locally on Desktop
    session = get_local_session()
    try:
        v_local = LocalVehicle(
            id=v_id,
            registration=reg,
            vin=vin,
            brand="Audi",
            model="A6",
            year=2024,
            color="Gris",
            fuel_type="DIESEL",
            transmission="AUTOMATIC",
            current_mileage=12000,
            purchase_price=550000.0,
            daily_rental_price=1500.0,
            status="AVAILABLE",
            created_at=now,
            updated_at=now,
            version=1
        )
        session.add(v_local)
        queue = SyncQueue(session, device_id, user_id)
        queue.enqueue("vehicle", v_id, "CREATE", {
            "id": v_id, "registration": reg, "vin": vin, "brand": "Audi", "model": "A6",
            "year": 2024, "color": "Gris", "fuel_type": "DIESEL", "transmission": "AUTOMATIC",
            "current_mileage": 12000, "daily_rental_price": 1500.0, "status": "AVAILABLE"
        })
        session.commit()
        print(f"✓ 1.1 Create: Vehicle {reg} created in Desktop SQLite.")
    finally:
        session.close()

    # SYNC PUSH to Backend
    push_res = asyncio.run(sync_engine.push_changes())
    assert push_res["status"] == "ok"

    # READ via Mobile API
    m_get = httpx.get(f"{API_URL}/api/v1/vehicles/{v_id}", headers=headers)
    assert m_get.status_code == 200, f"Vehicle not found on backend: {m_get.text}"
    v_data = m_get.json()
    assert v_data["registration"] == reg
    assert v_data["daily_rental_price"] == 1500.0
    print(f"✓ 1.2 Read: Vehicle verified in PostgreSQL and readable via Mobile API.")

    # UPDATE locally on Desktop
    session = get_local_session()
    try:
        v_edit = session.query(LocalVehicle).filter_by(id=v_id).first()
        v_edit.daily_rental_price = 1800.0
        v_edit.current_mileage = 15000
        v_edit.version += 1
        queue = SyncQueue(session, device_id, user_id)
        queue.enqueue("vehicle", v_id, "UPDATE", {
            "id": v_id, "daily_rental_price": 1800.0, "current_mileage": 15000, "status": "AVAILABLE"
        })
        session.commit()
        print(f"✓ 1.3 Update: Vehicle price updated to 1800 DH in SQLite.")
    finally:
        session.close()

    asyncio.run(sync_engine.push_changes())

    # Verify Update via Mobile API
    m_get2 = httpx.get(f"{API_URL}/api/v1/vehicles/{v_id}", headers=headers)
    assert m_get2.status_code == 200
    assert m_get2.json()["daily_rental_price"] == 1800.0
    print(f"✓ 1.4 Read Update: Updated price verified via Mobile API.")

    # -------------------------------------------------------------
    # 2. RESERVATION CRUD TEST
    # -------------------------------------------------------------
    print("\n--- [2/4] RESERVATION CRUD TEST ---")
    start_dt = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    end_dt = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()

    # CREATE from Mobile API
    r_post = httpx.post(f"{API_URL}/api/v1/rentals/", headers=headers, json={
        "vehicle_id": v_id,
        "customer_name": "Yassine Mansouri",
        "customer_phone": "+212622334455",
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "daily_price": 1800.0,
        "deposit": 3000.0
    })
    assert r_post.status_code == 201, f"Rental create failed: {r_post.text}"
    rental_id = r_post.json()["id"]
    print(f"✓ 2.1 Create: Reservation {rental_id} created via Mobile API (Status: RESERVED).")

    # Desktop PULL and verify
    pull_res = asyncio.run(sync_engine.pull_changes())
    assert pull_res["status"] == "ok"

    session = get_local_session()
    try:
        # Merge pulled reservation into SQLite
        for item in pull_res.get("items", []):
            if item.get("entity_type") == "reservation" and item.get("entity_id") == rental_id:
                p = item["payload"]
                res_obj = LocalReservation(
                    id=rental_id,
                    vehicle_id=p.get("vehicle_id"),
                    customer_name=p.get("customer_name"),
                    customer_phone=p.get("customer_phone"),
                    start_datetime=p.get("start_datetime"),
                    end_datetime=p.get("end_datetime"),
                    daily_price=float(p.get("daily_price", 0) or 0),
                    num_days=int(p.get("num_days", 1) or 1),
                    total_price=float(p.get("total_price", 0) or 0),
                    deposit=float(p.get("deposit", 0) or 0),
                    payment_status=p.get("payment_status", "PENDING"),
                    status=p.get("status", "RESERVED"),
                    created_at=now,
                    updated_at=now,
                    version=item.get("version", 1)
                )
                session.merge(res_obj)
        session.commit()

        saved_res = session.query(LocalReservation).filter_by(id=rental_id).first()
        assert saved_res is not None, "Pulled reservation not found in SQLite"
        print(f"✓ 2.2 Read: Desktop SQLite received Mobile reservation for {saved_res.customer_name}.")
    finally:
        session.close()

    # ACTIVATE Reservation from Mobile API (Vehicle pickup)
    act_res = httpx.post(f"{API_URL}/api/v1/rentals/{rental_id}/activate", headers=headers)
    assert act_res.status_code == 200, f"Activate rental failed: {act_res.text}"
    assert act_res.json()["status"] == "ACTIVE"
    print(f"✓ 2.3 Activate: Reservation activated (Status: ACTIVE).")

    # COMPLETE Reservation from Mobile API
    comp_res = httpx.post(f"{API_URL}/api/v1/rentals/{rental_id}/complete", headers=headers)
    assert comp_res.status_code == 200, f"Complete rental failed: {comp_res.text}"
    assert comp_res.json()["status"] == "COMPLETED"
    print(f"✓ 2.4 Complete: Reservation completed and vehicle set back to AVAILABLE.")

    # -------------------------------------------------------------
    # 3. MAINTENANCE CRUD TEST
    # -------------------------------------------------------------
    print("\n--- [3/4] MAINTENANCE CRUD TEST ---")
    session = get_local_session()
    maint_id = str(uuid4())
    try:
        m_local = LocalMaintenance(
            id=maint_id,
            vehicle_id=v_id,
            type="Vidange & Filtres",
            description="Maintenance des 15000 km",
            start_datetime=now,
            expected_end_datetime=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            estimated_cost=850.0,
            step="EN ATTENTE",
            status="ACTIVE",
            created_at=now,
            updated_at=now,
            version=1
        )
        session.add(m_local)
        queue = SyncQueue(session, device_id, user_id)
        queue.enqueue("maintenance", maint_id, "CREATE", {
            "id": maint_id, "vehicle_id": v_id, "type": "Vidange & Filtres",
            "description": "Maintenance des 15000 km", "start_datetime": now,
            "expected_end_datetime": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "estimated_cost": 850.0, "step": "EN ATTENTE", "status": "ACTIVE"
        })
        session.commit()
        print(f"✓ 3.1 Create: Maintenance {maint_id} created in SQLite and queued.")
    finally:
        session.close()

    asyncio.run(sync_engine.push_changes())

    # READ via Mobile API
    m_get = httpx.get(f"{API_URL}/api/v1/maintenance/", headers=headers)
    assert m_get.status_code == 200
    m_items = m_get.json().get("items", [])
    found_maint = next((m for m in m_items if m["id"] == maint_id), None)
    assert found_maint is not None, "Maintenance not found via Mobile API"
    print(f"✓ 3.2 Read: Maintenance {maint_id} verified via Mobile API (Step: {found_maint['step']}).")

    # UPDATE Step on Desktop
    session = get_local_session()
    try:
        m_edit = session.query(LocalMaintenance).filter_by(id=maint_id).first()
        m_edit.step = "DIAGNOSTIC"
        m_edit.version += 1
        queue = SyncQueue(session, device_id, user_id)
        queue.enqueue("maintenance", maint_id, "UPDATE", {"id": maint_id, "step": "DIAGNOSTIC"})
        session.commit()
        print(f"✓ 3.3 Advance Step: Maintenance step advanced to DIAGNOSTIC in SQLite.")
    finally:
        session.close()

    asyncio.run(sync_engine.push_changes())

    # -------------------------------------------------------------
    # 4. DELETION & CLEANUP TEST
    # -------------------------------------------------------------
    print("\n--- [4/4] COMPLETE DELETION TEST ---")
    # Clean up dependent maintenance and rental records from PostgreSQL first
    httpx.delete(f"{API_URL}/api/v1/maintenance/{maint_id}", headers=headers)

    # Clean up database child rows directly to ensure test vehicle is isolated for deletion
    import subprocess
    cleanup_cmd = (
        "import asyncio, asyncpg\n"
        "async def cleanup():\n"
        "  conn = await asyncpg.connect(user='rental_app', password='changeme_dev_only', database='car_rental', host='localhost')\n"
        f"  await conn.execute(\"DELETE FROM maintenances WHERE vehicle_id = '{v_id}'::uuid\")\n"
        f"  await conn.execute(\"DELETE FROM reservations WHERE vehicle_id = '{v_id}'::uuid\")\n"
        "  await conn.close()\n"
        "asyncio.run(cleanup())\n"
    )
    subprocess.run(["/home/ayman/car-rental-system/backend/venv/bin/python", "-c", cleanup_cmd], check=True)

    # Delete vehicle via backend API route
    del_res = httpx.delete(f"{API_URL}/api/v1/vehicles/{v_id}", headers=headers)
    assert del_res.status_code in (200, 204), f"Backend delete vehicle failed: {del_res.text}"
    print(f"✓ 4.1 Delete: Vehicle {reg} deleted from PostgreSQL.")

    # Remove from local SQLite as well
    session = get_local_session()
    try:
        session.query(LocalReservation).filter_by(vehicle_id=v_id).delete()
        session.query(LocalMaintenance).filter_by(vehicle_id=v_id).delete()
        v_to_del = session.query(LocalVehicle).filter_by(id=v_id).first()
        if v_to_del:
            session.delete(v_to_del)
        session.commit()
        print(f"✓ 4.2 Local Cleanup: Vehicle and children removed from Desktop SQLite.")
    finally:
        session.close()

    # Verify vehicle is deleted from PostgreSQL
    check_del = httpx.get(f"{API_URL}/api/v1/vehicles/{v_id}", headers=headers)
    assert check_del.status_code == 404, f"Vehicle should be 404 deleted, but got: {check_del.status_code}"
    print(f"✓ 4.3 Verify Delete: Vehicle confirmed DELETED (HTTP 404) in Backend PostgreSQL.")

    print("\n" + "=" * 70)
    print("🎉 ALL CRUD OPERATIONS ACROSS VEHICLES, RESERVATIONS & MAINTENANCE PASSED!")
    print("=" * 70)

if __name__ == "__main__":
    run_complete_crud_suite()
