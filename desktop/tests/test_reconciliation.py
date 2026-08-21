import os
import uuid

import httpx
import pytest

from app.config import API_BASE_URL
from app.services.api_client import ApiClient
from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.sync.engine import SyncEngine


TEST_ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL")
TEST_ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD")

pytestmark = pytest.mark.asyncio


@pytest.mark.skipif(
    not TEST_ADMIN_EMAIL or not TEST_ADMIN_PASSWORD,
    reason="Integration credentials not configured: set TEST_ADMIN_EMAIL and TEST_ADMIN_PASSWORD",
)
async def test_full_reconciliation_desktop_backend_mobile():
    init_local_db()

    # 1. Authenticate against the configured integration environment.
    client = ApiClient(base_url=API_BASE_URL)
    login_data = client.login(TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD)

    assert login_data is not None, "Integration authentication failed"

    token = login_data["access_token"]
    refresh_token = login_data.get("refresh_token")

    # 2. Verify the Mobile Bootstrap endpoint.
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.get(
            f"{API_BASE_URL}/api/v1/sync/bootstrap",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200, (
            f"Mobile bootstrap failed: HTTP {resp.status_code}: {resp.text}"
        )

        boot = resp.json()
        assert "vehicles" in boot
        assert "server_time" in boot

    # 3. Pull backend records into Desktop SQLite.
    device_id = f"reconcile-test-{uuid.uuid4().hex[:6]}"

    engine = SyncEngine(
        device_id=device_id,
        access_token=token,
        refresh_token=refresh_token,
    )

    pull_res = await engine.pull()

    assert pull_res["status"] in ("ok", "offline")

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

        assert not mismatches, (
            "Data mismatches found between Desktop SQLite and Backend: "
            f"{mismatches}"
        )
    finally:
        session.close()

    # 5. Verify notifications endpoint.
    notifs = client.get_notifications(page=1)

    assert notifs is not None
    assert "items" in notifs
