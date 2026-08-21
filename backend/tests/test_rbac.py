"""
Tests for RBAC — verifying that permissions are enforced server-side.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestRBAC:
    async def test_employee_cannot_create_vehicle(self, client: AsyncClient, employee_token: str):
        response = await client.post(
            "/api/v1/vehicles/",
            json={
                "registration": "RBAC-01", "vin": "WVWZZZ3CZWERBAC01",
                "brand": "Renault", "model": "Clio", "year": 2023,
                "color": "Noir", "fuel_type": "GASOLINE",
                "transmission": "MANUAL", "current_mileage": 5000,
                "purchase_mileage": 0, "purchase_price": 95000,
                "daily_rental_price": 250,
            },
            headers={"Authorization": f"Bearer {employee_token}"},
        )
        assert response.status_code == 403

    async def test_employee_can_read_vehicles(self, client: AsyncClient, employee_token: str):
        response = await client.get(
            "/api/v1/vehicles/",
            headers={"Authorization": f"Bearer {employee_token}"},
        )
        assert response.status_code == 200

    async def test_employee_cannot_delete_vehicle(self, client: AsyncClient, admin_token: str, employee_token: str):
        create_resp = await client.post(
            "/api/v1/vehicles/",
            json={
                "registration": "RBAC-DEL", "vin": "WVWZZZ3CZWERBADEL",
                "brand": "Test", "model": "Car", "year": 2024,
                "color": "Red", "fuel_type": "DIESEL",
                "transmission": "MANUAL", "current_mileage": 0,
                "purchase_mileage": 0, "purchase_price": 0,
                "daily_rental_price": 0,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        vehicle_id = create_resp.json()["id"]
        response = await client.delete(
            f"/api/v1/vehicles/{vehicle_id}",
            headers={"Authorization": f"Bearer {employee_token}"},
        )
        assert response.status_code == 403

    async def test_employee_cannot_create_users(self, client: AsyncClient, employee_token: str):
        response = await client.post(
            "/api/v1/users/",
            json={
                "email": "newuser@test.com", "username": "newuser",
                "password": "NewUser123!", "full_name": "New User",
                "role": "EMPLOYEE",
            },
            headers={"Authorization": f"Bearer {employee_token}"},
        )
        assert response.status_code == 403

    async def test_admin_can_create_users(self, client: AsyncClient, admin_token: str):
        response = await client.post(
            "/api/v1/users/",
            json={
                "email": "adminmade@test.com", "username": "adminmade",
                "password": "NewUser123!", "full_name": "Admin Made",
                "role": "EMPLOYEE",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 201
