"""
Cross-application contract consistency regression tests.

The desktop UI and the Android model treat customer phone/email as optional
(DB column is nullable). RentalCreate must accept reservations without a
phone number — this pins that contract so it cannot regress.
"""
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient

from app.models.vehicle import Vehicle


@pytest.mark.asyncio
async def test_reservation_without_customer_phone_accepted(
    client: AsyncClient, admin_token, db_session
):
    v = Vehicle(
        registration="CON-1-A-11", vin="1M8GDM9AXKP042788",
        brand="Dacia", model="Logan", year=2024, color="Blanc",
        fuel_type="DIESEL", transmission="MANUAL", current_mileage=100,
        daily_rental_price=250.0, status="AVAILABLE",
    )
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    start = datetime.now() + timedelta(days=5)
    payload = {
        "vehicle_id": str(v.id),
        "customer_name": "No Phone Client",
        "start_datetime": start.isoformat(),
        "end_datetime": (start + timedelta(days=2)).isoformat(),
        "daily_price": 250.0,
        "num_days": 2,
        "total_price": 500.0,
        "deposit": 0,
        "status": "RESERVED",
        "payment_status": "PENDING",
    }
    resp = await client.post(
        "/api/v1/rentals/", json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["customer_name"] == "No Phone Client"
    assert body["customer_phone"] is None


@pytest.mark.asyncio
async def test_reservation_with_short_phone_rejected(
    client: AsyncClient, admin_token, db_session
):
    """Length validation still applies when a phone IS provided."""
    v = Vehicle(
        registration="CON-1-A-12", vin="1M8GDM9AXKP042789",
        brand="Dacia", model="Logan", year=2024, color="Blanc",
        fuel_type="DIESEL", transmission="MANUAL", current_mileage=100,
        daily_rental_price=250.0, status="AVAILABLE",
    )
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    start = datetime.now() + timedelta(days=7)
    payload = {
        "vehicle_id": str(v.id),
        "customer_name": "Short Phone",
        "customer_phone": "123",  # below min_length=5
        "start_datetime": start.isoformat(),
        "end_datetime": (start + timedelta(days=2)).isoformat(),
        "daily_price": 250.0,
        "num_days": 2,
        "total_price": 500.0,
    }
    resp = await client.post(
        "/api/v1/rentals/", json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422
