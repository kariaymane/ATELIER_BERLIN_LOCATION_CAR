"""
Debug Deletion Sync Response
"""
import sys
import asyncio
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
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

def test_delete_debug():
    init_local_db()
    login_res = httpx.post(
        f"{API_URL}/api/v1/auth/login",
        json={"email": "BERLINCAR@GMAIL.COM", "password": "Berlin20002000"}
    )
    token = login_res.json()["access_token"]
    user_id = login_res.json()["user_id"]
    headers = {"Authorization": f"Bearer {token}"}
    device_id = f"test-crud-{str(uuid4())[:8]}"
    sync_engine = SyncEngine(device_id=device_id, access_token=token)

    v_id = str(uuid4())
    reg = f"DEL-{str(uuid4())[:6].upper()}"
    vin = f"VINDEL{str(uuid4()).replace('-', '')[:11].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    # Create locally
    session = get_local_session()
    v_local = LocalVehicle(
        id=v_id, registration=reg, vin=vin, brand="Test", model="Del",
        year=2024, color="Noir", fuel_type="DIESEL", transmission="MANUAL",
        current_mileage=1000, purchase_price=100000.0, daily_rental_price=400.0,
        status="AVAILABLE", created_at=now, updated_at=now, version=1
    )
    session.add(v_local)
    queue = SyncQueue(session, device_id, user_id)
    queue.enqueue("vehicle", v_id, "CREATE", {
        "id": v_id, "registration": reg, "vin": vin, "brand": "Test", "model": "Del",
        "year": 2024, "color": "Noir", "fuel_type": "DIESEL", "transmission": "MANUAL",
        "current_mileage": 1000, "daily_rental_price": 400.0, "status": "AVAILABLE"
    })
    session.commit()
    session.close()

    p_res = asyncio.run(sync_engine.push_changes())
    print("Create push:", p_res)

    # Now delete locally and push
    session = get_local_session()
    v = session.query(LocalVehicle).filter_by(id=v_id).first()
    session.delete(v)
    queue = SyncQueue(session, device_id, user_id)
    queue.enqueue("vehicle", v_id, "DELETE", {"id": v_id, "registration": reg})
    session.commit()
    session.close()

    # Call /sync/push directly to see full server response
    session = get_local_session()
    queue = SyncQueue(session, device_id, user_id)
    pending = queue.get_pending()
    items = []
    for item in pending:
        items.append({
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "operation": item.operation,
            "payload": __import__("json").loads(item.payload),
            "device_id": item.device_id,
            "idempotency_key": item.idempotency_key,
            "timestamp": item.created_at,
            "version": 1
        })
    session.close()

    resp = httpx.post(
        f"{API_URL}/api/v1/sync/push",
        json={"items": items},
        headers=headers
    )
    print("Raw sync push response:", resp.status_code, resp.text)

    # Check vehicle on server
    chk = httpx.get(f"{API_URL}/api/v1/vehicles/{v_id}", headers=headers)
    print("Server vehicle check:", chk.status_code, chk.text)

if __name__ == "__main__":
    test_delete_debug()
