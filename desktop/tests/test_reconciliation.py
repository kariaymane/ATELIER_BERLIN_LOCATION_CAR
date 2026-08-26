import os
import uuid
import pytest
import httpx
from unittest.mock import patch, MagicMock

from app.services.api_client import ApiClient
from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.sync.engine import SyncEngine
from app.config import API_BASE_URL

pytestmark = pytest.mark.asyncio

async def test_full_reconciliation_desktop_backend_mobile(monkeypatch):
    init_local_db()

    mock_vehicle = {
        "id": "v1", "brand": "Dacia", "model": "Logan", 
        "registration": "TEST-1", "vin": "TEST-VIN-123", 
        "year": 2022, "color": "White", "fuel_type": "Diesel", "transmission": "Manual",
        "daily_rental_price": 250.0, "status": "AVAILABLE", "version": 1
    }

    # 1. Mock the API client
    client = ApiClient(base_url=API_BASE_URL)
    client.login = MagicMock(return_value={
        "access_token": "fake-token",
        "refresh_token": "fake-refresh"
    })
    client.get_vehicles = MagicMock(return_value={
        "items": [mock_vehicle]
    })
    client.get_notifications = MagicMock(return_value={"items": []})

    login_data = client.login("admin@test", "pass")
    assert login_data is not None

    token = login_data["access_token"]
    refresh_token = login_data.get("refresh_token")

    # 2. Verify the Mobile Bootstrap endpoint via mocked httpx
    async def mock_handler(request: httpx.Request):
        if "/api/v1/sync/bootstrap" in str(request.url):
            return httpx.Response(200, json={"vehicles": [], "server_time": "2026-08-26T00:00:00Z"})
        if "/api/v1/sync/pull" in str(request.url):
            return httpx.Response(200, json={
                "items": [
                    {
                        "entity_type": "vehicle",
                        "entity_id": "v1",
                        "operation": "CREATE",
                        "version": 1,
                        "payload": mock_vehicle
                    }
                ],
                "latest_version": 1,
                "server_time": "2026-08-26T00:00:00Z"
            })
        return httpx.Response(404, json={"detail": "Not found"})
        
    transport = httpx.MockTransport(mock_handler)
    
    async with httpx.AsyncClient(transport=transport) as http:
        resp = await http.get(
            f"{API_BASE_URL}/api/v1/sync/bootstrap",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        boot = resp.json()
        assert "vehicles" in boot
        assert "server_time" in boot

    # 3. Pull backend records into Desktop SQLite.
    device_id = f"reconcile-test-{uuid.uuid4().hex[:6]}"

    with patch("app.sync.engine.httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        engine = SyncEngine(
            device_id=device_id,
            access_token=token,
            refresh_token=refresh_token
        )
        pull_res = await engine.pull()
        assert pull_res["status"] == "ok"

    # 4. Compare Desktop SQLite with Backend vehicles.
    v_backend = client.get_vehicles(page=1, page_size=100)
    assert v_backend is not None

    backend_vehicles = v_backend.get("items", [])
    session = get_local_session()
    try:
        sqlite_vehicles = session.query(LocalVehicle).all()
        sqlite_ids = {v.id for v in sqlite_vehicles}
        backend_ids = {v["id"] for v in backend_vehicles}

        mismatches = backend_ids - sqlite_ids
        assert not mismatches, f"Data mismatches found: {mismatches}"
    finally:
        session.close()

    # 5. Verify notifications endpoint.
    notifs = client.get_notifications(page=1)
    assert notifs is not None
    assert "items" in notifs
