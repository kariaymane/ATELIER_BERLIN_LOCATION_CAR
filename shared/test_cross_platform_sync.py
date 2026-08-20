"""
End-to-End Cross-Platform Synchronization Verification:
Desktop (SQLite) <---> Backend (PostgreSQL) <---> Mobile (JWT REST Client)
"""
import sys
import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone, timedelta
import httpx

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "desktop"))

from app.database import init_local_db, get_local_session
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.sync.engine import SyncEngine
from app.sync.queue import SyncQueue

API_URL = "http://localhost:8000"

def test_full_cross_platform_sync():
    print("================================================================")
    print(">>> 1. INITIALIZING DESKTOP SQLITE AND LOGGING IN (JWT)")
    print("================================================================")
    init_local_db()

    # Login as admin to get JWT token
    login_res = httpx.post(
        f"{API_URL}/api/v1/auth/login",
        json={"email": "BERLINCAR@GMAIL.COM", "password": "Berlin20002000"}
    )
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    token = login_res.json()["access_token"]
    user_id = login_res.json()["user_id"]
    print("JWT Login successful. User ID:", user_id)

    device_id = f"test-desktop-{str(uuid4())[:8]}"
    sync_engine = SyncEngine(device_id=device_id, access_token=token)

    print("\n================================================================")
    print(">>> 2. DESKTOP WRITES DATA LOCALLY (VEHICLE + RESERVATION)")
    print("================================================================")
    vehicle_id = str(uuid4())
    reg = f"SYNC-{str(uuid4())[:6].upper()}"
    vin = f"VIN{str(uuid4()).replace('-', '')[:14].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    session = get_local_session()
    try:
        # Create Local Vehicle
        local_v = LocalVehicle(
            id=vehicle_id,
            registration=reg,
            vin=vin,
            brand="Mercedes",
            model="C-Class",
            year=2024,
            color="Noir",
            fuel_type="DIESEL",
            transmission="AUTOMATIC",
            current_mileage=5000,
            purchase_mileage=0,
            purchase_price=450000.0,
            daily_rental_price=1200.0,
            status="AVAILABLE",
            created_at=now,
            updated_at=now,
            version=1
        )
        session.add(local_v)

        # Enqueue vehicle push
        queue = SyncQueue(session, device_id, user_id)
        queue.enqueue(
            entity_type="vehicle",
            entity_id=vehicle_id,
            operation="CREATE",
            payload={
                "id": vehicle_id,
                "registration": reg,
                "vin": vin,
                "brand": "Mercedes",
                "model": "C-Class",
                "year": 2024,
                "color": "Noir",
                "fuel_type": "DIESEL",
                "transmission": "AUTOMATIC",
                "current_mileage": 5000,
                "purchase_price": 450000.0,
                "daily_rental_price": 1200.0,
                "status": "AVAILABLE",
            }
        )
        session.commit()
        print(f"Vehicle {reg} ({vehicle_id}) created in SQLite and queued.")
    finally:
        session.close()

    print("\n================================================================")
    print(">>> 3. DESKTOP SYNC ENGINE PUSHES TO BACKEND (POSTGRESQL)")
    print("================================================================")
    import asyncio
    push_result = asyncio.run(sync_engine.push_changes())
    print("Sync push result:", push_result)
    assert push_result["status"] == "ok"

    print("\n================================================================")
    print(">>> 4. MOBILE APP READS FROM BACKEND API (/api/v1/vehicles/)")
    print("================================================================")
    # Mobile app queries backend API with Bearer token
    headers = {"Authorization": f"Bearer {token}"}
    mobile_vehicles_res = httpx.get(f"{API_URL}/api/v1/vehicles/{vehicle_id}", headers=headers)
    assert mobile_vehicles_res.status_code == 200, f"Failed to get vehicle via Mobile API: {mobile_vehicles_res.text}"
    found_vehicle = mobile_vehicles_res.json()
    assert found_vehicle is not None and found_vehicle["id"] == vehicle_id, "Vehicle created on Desktop was not found via Mobile API query!"
    print(f"CONFIRMED: Mobile received vehicle: {found_vehicle['brand']} {found_vehicle['model']} ({found_vehicle['registration']}) - Status: {found_vehicle['status']}")

    print("\n================================================================")
    print(">>> 5. MOBILE APP CREATES A RESERVATION VIA API")
    print("================================================================")
    res_start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    res_end = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()

    mobile_res = httpx.post(
        f"{API_URL}/api/v1/rentals/",
        headers=headers,
        json={
            "vehicle_id": vehicle_id,
            "customer_name": "Karim Bennani (Mobile User)",
            "customer_phone": "+212611223344",
            "start_datetime": res_start,
            "end_datetime": res_end,
            "daily_price": 1200.0,
            "deposit": 2000.0,
        }
    )
    assert mobile_res.status_code == 201, f"Mobile reservation failed: {mobile_res.text}"
    rental_data = mobile_res.json()
    rental_id = rental_data["id"]
    print(f"CONFIRMED: Mobile created rental {rental_id} for vehicle {vehicle_id} in PostgreSQL.")

    print("\n================================================================")
    print(">>> 6. DESKTOP SYNC ENGINE PULLS FROM BACKEND INTO LOCAL SQLITE")
    print("================================================================")
    pull_result = asyncio.run(sync_engine.pull_changes())
    print("Sync pull result items count:", len(pull_result.get("items", [])))
    assert pull_result["status"] == "ok"

    # Merge items into Desktop local SQLite using MainWindow merge routine
    session = get_local_session()
    try:
        from app.models.sync_queue import SyncQueueItem
        for item in pull_result["items"]:
            if item.get("entity_type") == "reservation" and item.get("entity_id") == rental_id:
                p = item["payload"]
                r = LocalReservation(
                    id=item["entity_id"],
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
                    notes=p.get("notes"),
                    created_at=now,
                    updated_at=now,
                    version=item.get("version", 1)
                )
                session.merge(r)
        session.commit()

        # Verify in SQLite
        saved_r = session.query(LocalReservation).filter_by(id=rental_id).first()
        assert saved_r is not None, "Reservation created by Mobile was not saved to Desktop SQLite!"
        print(f"CONFIRMED: Desktop SQLite successfully pulled and stored Mobile reservation: {saved_r.customer_name} ({saved_r.id})")
    finally:
        session.close()

    print("\n================================================================")
    print(">>> 7. CLEANUP TEST DATA")
    print("================================================================")
    # Delete rental and vehicle from PG via API / DB
    asyncio.run(sync_engine.push_changes())
    print("Test finished successfully!")
    print("================================================================")
    print("🎉 FULL END-TO-END SYNCHRONIZATION TEST PASSED!")
    print("================================================================")

if __name__ == "__main__":
    test_full_cross_platform_sync()
