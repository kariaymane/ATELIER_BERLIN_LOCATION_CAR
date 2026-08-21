"""
Tests for vehicle endpoints — CRUD, constraints, and RBAC.
"""
import pytest
from httpx import AsyncClient
from uuid import uuid4


SAMPLE_VEHICLE = {
    "registration": "AB-123-CD",
    "vin": "WVWZZZ3CZWE123456",
    "brand": "Dacia",
    "model": "Logan",
    "year": 2024,
    "color": "Blanc",
    "fuel_type": "DIESEL",
    "transmission": "MANUAL",
    "current_mileage": 15000,
    "purchase_mileage": 0,
    "purchase_price": 120000.00,
    "daily_rental_price": 350.00,
}


@pytest.mark.asyncio
class TestVehicleCRUD:
    """Test vehicle CRUD operations."""

    async def test_create_vehicle(self, client: AsyncClient, admin_token: str):
        """Test creating a vehicle."""
        response = await client.post(
            "/api/v1/vehicles/",
            json=SAMPLE_VEHICLE,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["registration"] == "AB-123-CD"
        assert data["vin"] == "WVWZZZ3CZWE123456"
        assert data["status"] == "AVAILABLE"

    async def test_list_vehicles(self, client: AsyncClient, admin_token: str):
        """Test listing vehicles."""
        # Create a vehicle first
        await client.post(
            "/api/v1/vehicles/",
            json={**SAMPLE_VEHICLE, "registration": "EF-456-GH", "vin": "WVWZZZ3CZWE654321"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        response = await client.get(
            "/api/v1/vehicles/",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "vehicles" in data
        assert data["total"] >= 1

    async def test_get_vehicle(self, client: AsyncClient, admin_token: str):
        """Test getting a specific vehicle."""
        # Create
        create_resp = await client.post(
            "/api/v1/vehicles/",
            json={**SAMPLE_VEHICLE, "registration": "IJ-789-KL", "vin": "WVWZZZ3CZWE789012"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        vehicle_id = create_resp.json()["id"]

        # Get
        response = await client.get(
            f"/api/v1/vehicles/{vehicle_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["id"] == vehicle_id

    async def test_update_vehicle(self, client: AsyncClient, admin_token: str):
        """Test updating a vehicle."""
        # Create
        create_resp = await client.post(
            "/api/v1/vehicles/",
            json={**SAMPLE_VEHICLE, "registration": "MN-012-OP", "vin": "WVWZZZ3CZWE012345"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        vehicle_id = create_resp.json()["id"]

        # Update
        response = await client.put(
            f"/api/v1/vehicles/{vehicle_id}",
            json={"color": "Rouge", "daily_rental_price": 400.00},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["color"] == "Rouge"
        assert response.json()["daily_rental_price"] == 400.00

    async def test_delete_vehicle(self, client: AsyncClient, admin_token: str):
        """Test deleting a vehicle."""
        # Create
        create_resp = await client.post(
            "/api/v1/vehicles/",
            json={**SAMPLE_VEHICLE, "registration": "QR-345-ST", "vin": "WVWZZZ3CZWE345678"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        vehicle_id = create_resp.json()["id"]

        # Delete
        response = await client.delete(
            f"/api/v1/vehicles/{vehicle_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 204

    async def test_vehicle_not_found(self, client: AsyncClient, admin_token: str):
        """Test getting a nonexistent vehicle returns 404."""
        response = await client.get(
            f"/api/v1/vehicles/{uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404


@pytest.mark.asyncio
class TestVehicleConstraints:
    """Test database constraints on vehicles."""

    async def test_duplicate_registration(self, client: AsyncClient, admin_token: str):
        """Test that duplicate registration plate is rejected."""
        vehicle = {**SAMPLE_VEHICLE, "registration": "DUP-REG-01", "vin": "WVWZZZ3CZWEDUPLR1"}
        await client.post(
            "/api/v1/vehicles/",
            json=vehicle,
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Try to create another with same registration
        vehicle2 = {**SAMPLE_VEHICLE, "registration": "DUP-REG-01", "vin": "WVWZZZ3CZWEDUPLR2"}
        response = await client.post(
            "/api/v1/vehicles/",
            json=vehicle2,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code in (400, 409)

    async def test_duplicate_vin(self, client: AsyncClient, admin_token: str):
        """Test that duplicate VIN is rejected."""
        vehicle = {**SAMPLE_VEHICLE, "registration": "DUP-VIN-01", "vin": "WVWZZZ3CZWEDUPLV1"}
        await client.post(
            "/api/v1/vehicles/",
            json=vehicle,
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        vehicle2 = {**SAMPLE_VEHICLE, "registration": "DUP-VIN-02", "vin": "WVWZZZ3CZWEDUPLV1"}
        response = await client.post(
            "/api/v1/vehicles/",
            json=vehicle2,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code in (400, 409)

    async def test_invalid_fuel_type(self, client: AsyncClient, admin_token: str):
        """Test that invalid fuel type fails validation."""
        vehicle = {**SAMPLE_VEHICLE, "registration": "FUEL-01", "vin": "WVWZZZ3CZWEFUEL01", "fuel_type": "NUCLEAR"}
        response = await client.post(
            "/api/v1/vehicles/",
            json=vehicle,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Either Pydantic or database should reject this
        assert response.status_code >= 400

    async def test_negative_mileage(self, client: AsyncClient, admin_token: str):
        """Test that negative mileage is rejected."""
        vehicle = {**SAMPLE_VEHICLE, "registration": "NEG-KM-01", "vin": "WVWZZZ3CZWENEGKM1", "current_mileage": -100}
        response = await client.post(
            "/api/v1/vehicles/",
            json=vehicle,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422  # Pydantic validation

    async def test_vin_wrong_length(self, client: AsyncClient, admin_token: str):
        """Test that VIN with wrong length is rejected."""
        vehicle = {**SAMPLE_VEHICLE, "registration": "VIN-LEN-01", "vin": "SHORT"}
        response = await client.post(
            "/api/v1/vehicles/",
            json=vehicle,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422  # Pydantic validation


@pytest.mark.asyncio
class TestVehicleStatusTransitions:
    """Test vehicle status transition rules."""

    async def test_valid_transition_available_to_reserved(
        self, client: AsyncClient, admin_token: str
    ):
        """Test valid transition: AVAILABLE -> RESERVED."""
        create_resp = await client.post(
            "/api/v1/vehicles/",
            json={**SAMPLE_VEHICLE, "registration": "STAT-01", "vin": "WVWZZZ3CZWESTAT01"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        vehicle_id = create_resp.json()["id"]

        response = await client.patch(
            f"/api/v1/vehicles/{vehicle_id}/status",
            json={"status": "RESERVED"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "RESERVED"

    async def test_invalid_transition_rented_to_sold(
        self, client: AsyncClient, admin_token: str
    ):
        """Test invalid transition: RENTED -> SOLD should fail."""
        create_resp = await client.post(
            "/api/v1/vehicles/",
            json={**SAMPLE_VEHICLE, "registration": "STAT-02", "vin": "WVWZZZ3CZWESTAT02"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        vehicle_id = create_resp.json()["id"]

        # First transition to RENTED
        await client.patch(
            f"/api/v1/vehicles/{vehicle_id}/status",
            json={"status": "RENTED"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Try invalid transition to SOLD
        response = await client.patch(
            f"/api/v1/vehicles/{vehicle_id}/status",
            json={"status": "SOLD"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 400
