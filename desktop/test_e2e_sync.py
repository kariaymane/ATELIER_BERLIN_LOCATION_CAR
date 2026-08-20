import sys
import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

# Setup path so imports work
sys.path.insert(0, str(Path(__file__).parent.resolve()))

# Initialize config properly
os.environ["API_BASE_URL"] = "http://localhost:8000"

from app.database import init_local_db, get_local_session
from app.models.user import LocalUser
from app.models.vehicle import LocalVehicle
from app.sync.engine import SyncEngine
from app.sync.queue import SyncQueue
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("e2e_test")

async def test_e2e():
    logger.info("1. Initialize Local SQLite")
    init_local_db()
    session = get_local_session()
    from app.database import LocalBase
    for table in reversed(LocalBase.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    session.close()

    # 2. Test Login online
    logger.info("2. Login online")
    # We'll just call the API directly instead of full Qt UI for login since Qt needs an app event loop
    email = "BERLINCAR@GMAIL.COM"
    password = "Berlin20002000"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{os.environ['API_BASE_URL']}/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        auth_data = response.json()
        auth_data["email"] = email

    logger.info("Login successful. Received tokens.")

    # Let's use the UI's caching logic directly
    from argon2 import PasswordHasher
    session = get_local_session()
    try:
        ph = PasswordHasher()
        password_hash = ph.hash(password)
        now = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()

        existing = session.query(LocalUser).filter_by(id=auth_data["user_id"]).first()
        if existing:
            existing.email = email
            existing.password_hash = password_hash
            existing.full_name = auth_data["full_name"]
            existing.role = auth_data["role"]
            existing.updated_at = now
        else:
            user = LocalUser(
                id=auth_data["user_id"],
                email=email,
                username=email.split("@")[0],
                password_hash=password_hash,
                full_name=auth_data["full_name"],
                role=auth_data["role"],
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
        session.commit()
    finally:
        session.close()

    # 3. Create vehicle locally & queue
    logger.info("3. Create vehicle locally")
    vehicle_id = str(uuid4())
    registration = f"TEST-{str(uuid4())[:8].upper()}"
    vin = str(uuid4()).replace("-", "")[:17].upper()

    session = get_local_session()
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    try:
        v = LocalVehicle(
            id=vehicle_id,
            registration=registration,
            vin=vin,
            brand="TestBrand",
            model="TestModel",
            year=2024,
            color="Red",
            fuel_type="GASOLINE",
            transmission="MANUAL",
            current_mileage=100,
            purchase_mileage=0,
            purchase_price=10000,
            daily_rental_price=100,
            status="AVAILABLE",
            created_at=now,
            updated_at=now,
            version=1,
        )
        session.add(v)
        session.commit()

        # Enqueue
        queue = SyncQueue(session, "test-device", auth_data["user_id"])
        queue.enqueue(
            entity_type="vehicle",
            entity_id=vehicle_id,
            operation="CREATE",
            payload={
                "id": vehicle_id,
                "registration": registration,
                "vin": vin,
                "brand": "TestBrand",
                "model": "TestModel",
                "year": 2024,
                "color": "Red",
                "fuel_type": "GASOLINE",
                "transmission": "MANUAL",
                "current_mileage": 100,
                "purchase_mileage": 0,
                "purchase_price": 10000,
                "daily_rental_price": 100,
                "status": "AVAILABLE",
            }
        )
        assert queue.get_pending_count() >= 1, "Queue should have at least 1 pending item"
        logger.info("Local vehicle created and queued.")
    finally:
        session.close()

    # 4. Start synchronization
    logger.info("4. Start synchronization")
    sync_engine = SyncEngine("test-device", auth_data["access_token"])
    res = await sync_engine.sync()
    logger.info(f"Sync result: {res}")

    assert res["push"]["status"] == "ok", "Push failed"
    assert res["push"]["pushed"] >= 1, "Should have pushed at least 1 item"

    session = get_local_session()
    try:
        queue = SyncQueue(session, "test-device")
        assert queue.get_pending_count() == 0, "Queue should be empty after successful sync"
    finally:
        session.close()

    # 5. Verify PostgreSQL contains the vehicle
    logger.info("5. Verify PostgreSQL contains the vehicle")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{os.environ['API_BASE_URL']}/api/v1/vehicles/{vehicle_id}",
            headers={"Authorization": f"Bearer {auth_data['access_token']}"}
        )
        assert response.status_code == 200, "Vehicle not found in PostgreSQL"
        logger.info("Vehicle successfully retrieved from PostgreSQL.")

    # 6. Update vehicle
    logger.info("6. Update vehicle locally and sync")
    session = get_local_session()
    try:
        v = session.query(LocalVehicle).filter_by(id=vehicle_id).first()
        v.color = "Blue"
        v.version += 1
        v.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        session.commit()

        queue = SyncQueue(session, "test-device", auth_data["user_id"])
        queue.enqueue(
            entity_type="vehicle",
            entity_id=vehicle_id,
            operation="UPDATE",
            payload={
                "color": "Blue",
            }
        )
    finally:
        session.close()

    res = await sync_engine.sync()
    assert res["push"]["status"] == "ok", "Update push failed"

    # Verify update in PostgreSQL
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{os.environ['API_BASE_URL']}/api/v1/vehicles/{vehicle_id}",
            headers={"Authorization": f"Bearer {auth_data['access_token']}"}
        )
        assert response.status_code == 200
        assert response.json()["color"] == "Blue", "Vehicle not updated in PostgreSQL"
        logger.info("Vehicle updated successfully in PostgreSQL.")

    # 8. Create maintenance locally and sync
    logger.info("8. Create maintenance locally and sync")
    api_url = f"{os.environ['API_BASE_URL']}/api/v1"
    headers = {"Authorization": f"Bearer {auth_data['access_token']}"}
    now_utc = datetime.now(timezone.utc)
    from app.models.maintenance import LocalMaintenance
    m_id = str(uuid4())
    session = get_local_session()
    queue = SyncQueue(session, "test-device", auth_data["user_id"])
    try:
        v = session.query(LocalVehicle).filter_by(id=vehicle_id).first()
        m = LocalMaintenance(
            id=m_id,
            vehicle_id=vehicle_id,
            type="Entretien",
            start_datetime=now_utc.isoformat(),
            expected_end_datetime=(now_utc + timedelta(days=2)).isoformat(),
            step="DIAGNOSTIC",
            status="ACTIVE",
            created_at=now_utc.isoformat(),
            updated_at=now_utc.isoformat()
        )
        session.add(m)

        queue.enqueue(
            entity_type="maintenance",
            entity_id=m_id,
            operation="CREATE",
            payload={
                "id": m_id,
                "vehicle_id": vehicle_id,
                "type": "Entretien",
                "start_datetime": now_utc.isoformat(),
                "expected_end_datetime": (now_utc + timedelta(days=2)).isoformat(),
                "step": "DIAGNOSTIC",
                "status": "ACTIVE"
            }
        )

        v.status = "MAINTENANCE"
        v.version += 1
        queue.enqueue(
            entity_type="vehicle",
            entity_id=vehicle_id,
            operation="UPDATE",
            payload={"id": vehicle_id, "status": "MAINTENANCE"}
        )
        session.commit()
        logger.info("Local maintenance created and vehicle set to MAINTENANCE.")

        res = await sync_engine.sync()
        logger.info(f"Maintenance Sync Result: {res}")
        assert res["push"]["status"] == "ok"

        async with httpx.AsyncClient() as client:

            res = await client.get(f"{api_url}/vehicles/{vehicle_id}", headers=headers)
            logger.info(f"Vehicle after maintenance: {res.json()}")
            assert res.status_code == 200
            assert res.json()["status"] == "MAINTENANCE"
            logger.info("Maintenance synced and PG vehicle status verified.")
    finally:
        session.close()

    # 9. Delete vehicle locally and sync
    logger.info("9. Delete vehicle locally and sync")
    session = get_local_session()
    try:
        v = session.query(LocalVehicle).filter_by(id=vehicle_id).first()
        m = session.query(LocalMaintenance).filter_by(id=m_id).first()
        queue = SyncQueue(session, "test-device", auth_data["user_id"])
        if m:
            queue.enqueue(
                entity_type="maintenance",
                entity_id=m_id,
                operation="DELETE",
                payload={"id": m_id}
            )
            session.delete(m)
            import time; time.sleep(0.1)
        queue.enqueue(
            entity_type="vehicle",
            entity_id=vehicle_id,
            operation="DELETE",
            payload={
                "id": vehicle_id,
                "registration": v.registration,
            }
        )
        session.delete(v)
        session.commit()
    finally:
        session.close()

    res = await sync_engine.sync()
    assert res["push"]["status"] == "ok", "Delete push failed"

    # Verify delete in PostgreSQL
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{os.environ['API_BASE_URL']}/api/v1/vehicles/{vehicle_id}",
            headers={"Authorization": f"Bearer {auth_data['access_token']}"}
        )
        assert response.status_code == 404, "Vehicle was not deleted in PostgreSQL"
        logger.info("Vehicle successfully deleted in PostgreSQL.")

    logger.info("🎉 All Desktop end-to-end tests passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_e2e())
