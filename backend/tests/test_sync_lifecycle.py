"""
Comprehensive tests for Sync API endpoints: Push, Pull, Bootstrap, Idempotency, Conflicts, Photos.
"""
import pytest
from httpx import AsyncClient
from uuid import uuid4
from datetime import datetime, timezone, timedelta

@pytest.mark.asyncio
class TestSyncLifecycle:

    async def test_sync_push_create_vehicle_with_photos(self, client: AsyncClient, admin_token: str):
        v_id = str(uuid4())
        reg = f"SYNC-{uuid4().hex[:6].upper()}"
        vin = f"VNSYNC{uuid4().hex[:11].upper()}"
        photos = [f"/static/uploads/vehicles/photo_{i}.jpg" for i in range(5)]

        idem_key = f"idem-{uuid4()}"
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "items": [
                {
                    "idempotency_key": idem_key,
                    "entity_type": "vehicle",
                    "entity_id": v_id,
                    "operation": "CREATE",
                    "payload": {
                        "id": v_id,
                        "registration": reg,
                        "vin": vin,
                        "brand": "Porsche",
                        "model": "Panamera Executive",
                        "year": 2024,
                        "color": "Noir",
                        "fuel_type": "GASOLINE",
                        "transmission": "AUTOMATIC",
                        "daily_rental_price": 2500.0,
                        "current_mileage": 15000,
                        "status": "AVAILABLE",
                        "image_url": ",".join(photos),
                        "images": photos,
                    },
                    "version": 1,
                    "device_id": "test-desktop-device",
                    "timestamp": now_iso,
                }
            ]
        }

        # 1. Push create
        res = await client.post(
            "/api/v1/sync/push",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res.status_code == 200, f"Push create failed: {res.text}"
        data = res.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["status"] == "ok"

        # 2. Verify Bootstrap contains vehicle and all 5 photos
        boot_res = await client.get(
            "/api/v1/sync/bootstrap",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert boot_res.status_code == 200
        boot_data = boot_res.json()
        veh_found = next((v for v in boot_data["vehicles"] if v["id"] == v_id), None)
        assert veh_found is not None, "Vehicle not found in bootstrap!"
        assert veh_found["registration"] == reg
        assert len(veh_found["images"]) == 5, f"Expected 5 photos, got {len(veh_found['images'])}"

        # 3. Test Idempotency: push the exact same request again
        res_dup = await client.post(
            "/api/v1/sync/push",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res_dup.status_code == 200
        data_dup = res_dup.json()
        assert data_dup["results"][0]["status"] == "ok"

        # 4. Push update
        update_idem = f"idem-{uuid4()}"
        update_payload = {
            "items": [
                {
                    "idempotency_key": update_idem,
                    "entity_type": "vehicle",
                    "entity_id": v_id,
                    "operation": "UPDATE",
                    "payload": {
                        "id": v_id,
                        "daily_rental_price": 2800.0,
                        "current_mileage": 16000,
                        "status": "RENTED",
                    },
                    "version": 1,
                    "device_id": "test-desktop-device",
                    "timestamp": now_iso,
                }
            ]
        }
        res_update = await client.post(
            "/api/v1/sync/push",
            json=update_payload,
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res_update.status_code == 200
        assert res_update.json()["results"][0]["status"] == "ok"
        assert res_update.json()["results"][0]["server_version"] == 2

        # 5. Pull changes since 5 minutes ago
        since_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        pull_res = await client.post(
            "/api/v1/sync/pull",
            json={"since": since_iso, "device_id": "test-desktop-device"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert pull_res.status_code == 200
        pull_items = pull_res.json()["items"]
        pulled_veh = next((i for i in pull_items if i["entity_id"] == v_id), None)
        assert pulled_veh is not None, "Updated vehicle not found in pull!"
        assert pulled_veh["payload"]["daily_rental_price"] == 2800.0
        assert pulled_veh["payload"]["status"] == "RENTED"

        # 6. Test Optimistic Version Conflict
        conflict_idem = f"idem-{uuid4()}"
        conflict_payload = {
            "items": [
                {
                    "idempotency_key": conflict_idem,
                    "entity_type": "vehicle",
                    "entity_id": v_id,
                    "operation": "UPDATE",
                    "payload": {"daily_rental_price": 3200.0},
                    "version": 1,  # Outdated version (server is at 2)
                    "device_id": "test-desktop-device",
                    "timestamp": now_iso,
                }
            ]
        }
        res_conflict = await client.post(
            "/api/v1/sync/push",
            json=conflict_payload,
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res_conflict.status_code == 200
        assert res_conflict.json()["results"][0]["status"] == "conflict"

        # 7. Push delete
        del_idem = f"idem-{uuid4()}"
        del_payload = {
            "items": [
                {
                    "idempotency_key": del_idem,
                    "entity_type": "vehicle",
                    "entity_id": v_id,
                    "operation": "DELETE",
                    "payload": {},
                    "version": 2,
                    "device_id": "test-desktop-device",
                    "timestamp": now_iso,
                }
            ]
        }
        res_del = await client.post(
            "/api/v1/sync/push",
            json=del_payload,
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res_del.status_code == 200
        assert res_del.json()["results"][0]["status"] == "ok"

        # 8. Verify vehicle no longer exists
        get_res = await client.get(
            f"/api/v1/vehicles/{v_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert get_res.status_code == 404

    async def test_sync_unauthorized(self, client: AsyncClient):
        """Verify anonymous requests to sync endpoints are rejected with 401."""
        res_push = await client.post("/api/v1/sync/push", json={"items": []})
        assert res_push.status_code in (401, 403)
        res_pull = await client.post("/api/v1/sync/pull", json={"since": datetime.now(timezone.utc).isoformat(), "device_id": "test"})
        assert res_pull.status_code in (401, 403)
        res_boot = await client.get("/api/v1/sync/bootstrap")
        assert res_boot.status_code in (401, 403)
