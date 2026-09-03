"""Test Phase 6 & 7: Desktop Full Bootstrap Reconciliation & Sync Cursor Safety."""
import os
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch
import httpx

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.client import LocalClient
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.sync.engine import SyncEngine


@pytest.fixture(autouse=True)
def _db():
    init_local_db()


@pytest.mark.asyncio
async def test_full_bootstrap_reconciles_all_four_domains():
    """Verify that bootstrap purges server-deleted records and upserts fresh records
    across vehicles, clients, reservations, and maintenance."""
    now_iso = datetime.now(timezone.utc).isoformat()
    session = get_local_session()

    # Pre-seed: 1 valid record and 1 obsolete record in each domain
    session.add(LocalVehicle(id="v-keep", registration="KEEP-V", vin="VIN-KEEP-00000001", brand="B", model="M", year=2024, color="N", fuel_type="D", transmission="M", status="AVAILABLE", created_at=now_iso, updated_at=now_iso))
    session.add(LocalVehicle(id="v-drop", registration="DROP-V", vin="VIN-DROP-00000002", brand="B", model="M", year=2024, color="N", fuel_type="D", transmission="M", status="AVAILABLE", created_at=now_iso, updated_at=now_iso))

    session.add(LocalClient(id="c-keep", first_name="Jean", last_name="Keep", phone="0611111111", email="keep@example.com", status="ACTIVE", created_at=now_iso, updated_at=now_iso))
    session.add(LocalClient(id="c-drop", first_name="Marc", last_name="Drop", phone="0622222222", email="drop@example.com", status="ACTIVE", created_at=now_iso, updated_at=now_iso))

    session.add(LocalReservation(id="r-keep", vehicle_id="v-keep", customer_name="Keep", start_datetime=now_iso, end_datetime=now_iso, daily_price=100, num_days=1, total_price=100, status="RESERVED", created_at=now_iso, updated_at=now_iso))
    session.add(LocalReservation(id="r-drop", vehicle_id="v-drop", customer_name="Drop", start_datetime=now_iso, end_datetime=now_iso, daily_price=100, num_days=1, total_price=100, status="RESERVED", created_at=now_iso, updated_at=now_iso))

    session.add(LocalMaintenance(id="m-keep", vehicle_id="v-keep", type="VIDANGE", start_datetime=now_iso, status="ACTIVE", created_at=now_iso, updated_at=now_iso))
    session.add(LocalMaintenance(id="m-drop", vehicle_id="v-drop", type="FREINS", start_datetime=now_iso, status="ACTIVE", created_at=now_iso, updated_at=now_iso))

    session.commit()
    session.close()

    # Mock bootstrap endpoint returning ONLY the keep records + 1 brand new client
    mock_bootstrap_data = {
        "sync_version": 1,
        "revision": 12345,
        "server_time": now_iso,
        "vehicles": [
            {"id": "v-keep", "registration": "KEEP-V", "vin": "VIN-KEEP-00000001", "brand": "B", "model": "M", "year": 2024, "color": "N", "fuel_type": "D", "transmission": "M", "status": "AVAILABLE", "version": 2}
        ],
        "clients": [
            {"id": "c-keep", "first_name": "Jean", "last_name": "Keep", "phone": "0611111111", "email": "keep@example.com", "status": "ACTIVE", "version": 2},
            {"id": "c-new", "first_name": "Alice", "last_name": "New", "phone": "0633333333", "email": "new@example.com", "status": "ACTIVE", "version": 1}
        ],
        "rentals": [
            {"id": "r-keep", "vehicle_id": "v-keep", "customer_name": "Keep", "start_datetime": now_iso, "end_datetime": now_iso, "daily_price": 100, "num_days": 1, "total_price": 100, "status": "RESERVED", "version": 2}
        ],
        "maintenance": [
            {"id": "m-keep", "vehicle_id": "v-keep", "type": "VIDANGE", "start_datetime": now_iso, "status": "ACTIVE", "version": 2}
        ]
    }

    def mock_handler(request: httpx.Request):
        if "sync/bootstrap" in str(request.url):
            return httpx.Response(200, json=mock_bootstrap_data)
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    with patch("app.sync.engine.httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        engine = SyncEngine(device_id="test_dev_01", access_token="test_token", base_url="http://127.0.0.1:8000")
        res = await engine.bootstrap()
        assert res["status"] == "ok"

    # Verify SQLite state
    verify_session = get_local_session()
    v_ids = {v.id for v in verify_session.query(LocalVehicle).all()}
    c_ids = {c.id for c in verify_session.query(LocalClient).all()}
    r_ids = {r.id for r in verify_session.query(LocalReservation).all()}
    m_ids = {m.id for m in verify_session.query(LocalMaintenance).all()}
    verify_session.close()

    assert v_ids == {"v-keep"}, f"Expected only v-keep, got {v_ids}"
    assert c_ids == {"c-keep", "c-new"}, f"Expected c-keep and c-new, got {c_ids}"
    assert r_ids == {"r-keep"}, f"Expected only r-keep, got {r_ids}"
    assert m_ids == {"m-keep"}, f"Expected only m-keep, got {m_ids}"
