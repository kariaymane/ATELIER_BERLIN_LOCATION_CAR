import pytest
from httpx import AsyncClient

SAMPLE_CLIENT = {
    "first_name": "Karim",
    "last_name": "El Idrissi",
    "email": "karim.elidrissi@example.com",
    "phone": "+212612345678",
    "cin_number": "AB123456",
    "identity_card_image": "/static/uploads/clients/cin_test.jpg",
    "license_number": "01/123456",
    "driving_license_image": "/static/uploads/clients/permis_test.jpg",
    "photo_url": "/static/uploads/clients/photo_test.jpg",
    "notes": "Client VIP fidèle",
}

@pytest.mark.asyncio
class TestClientCRUD:
    async def test_create_client(self, client: AsyncClient, admin_token: str):
        response = await client.post(
            "/api/v1/clients/",
            json=SAMPLE_CLIENT,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["first_name"] == "Karim"
        assert data["last_name"] == "El Idrissi"
        assert data["cin_number"] == "AB123456"
        assert data["license_number"] == "01/123456"
        assert data["photo_url"] == "/static/uploads/clients/photo_test.jpg"
        assert data["identity_card_image"] == "/static/uploads/clients/cin_test.jpg"
        assert data["driving_license_image"] == "/static/uploads/clients/permis_test.jpg"

    async def test_list_clients(self, client: AsyncClient, admin_token: str):
        # Create a client first
        await client.post(
            "/api/v1/clients/",
            json=SAMPLE_CLIENT,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        response = await client.get(
            "/api/v1/clients/",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "clients" in data
        assert len(data["clients"]) >= 1

    async def test_get_client(self, client: AsyncClient, admin_token: str):
        create_resp = await client.post(
            "/api/v1/clients/",
            json=SAMPLE_CLIENT,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        client_id = create_resp.json()["id"]

        get_resp = await client.get(
            f"/api/v1/clients/{client_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["id"] == client_id
        assert data["first_name"] == "Karim"

    async def test_update_client(self, client: AsyncClient, admin_token: str):
        create_resp = await client.post(
            "/api/v1/clients/",
            json=SAMPLE_CLIENT,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        client_id = create_resp.json()["id"]

        update_resp = await client.put(
            f"/api/v1/clients/{client_id}",
            json={"phone": "+212699887766", "notes": "Updated notes"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["phone"] == "+212699887766"
        assert data["notes"] == "Updated notes"

    async def test_client_history(self, client: AsyncClient, admin_token: str):
        create_resp = await client.post(
            "/api/v1/clients/",
            json=SAMPLE_CLIENT,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        client_id = create_resp.json()["id"]

        history_resp = await client.get(
            f"/api/v1/clients/{client_id}/history",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert history_resp.status_code == 200
        data = history_resp.json()
        assert "history" in data
