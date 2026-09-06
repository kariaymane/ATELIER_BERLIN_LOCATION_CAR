"""
Client profile edition + relation-aware deletion.

Canonical rules verified here:

EDITION (UPDATE, never re-create)
  - A PUT updates the SAME client_id; the row count never grows.
  - A field the caller never mentions is left untouched.
  - A field explicitly sent as null — or as an empty string — is CLEARED.
    Emptying an optional field is a legitimate business edit.
  - first_name / last_name / status are NOT NULL columns and refuse to be
    emptied; the rest of the same update still applies.
  - address and contract_image are first-class client columns.

DELETION (respects existing relations, never breaks PostgreSQL integrity)
  - A client with linked reservations is DEACTIVATED (status=INACTIVE): its
    rental history, revenue and audit trail survive.
  - A client with no reservation at all is physically DELETED.
"""
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select, func

from app.models.client import Client
from app.models.reservation import Reservation
from app.models.vehicle import Vehicle


AUTH = lambda tok: {"Authorization": f"Bearer {tok}"}


async def _make_client(client: AsyncClient, token, **over):
    body = {
        "first_name": "Sami", "last_name": "Alami",
        "phone": "0600000000", "email": "sami@example.test",
        "address": "12 Rue des Orangers, Casablanca",
        "cin_number": "AB123456", "license_number": "L-99",
        "identity_card_image": "/static/uploads/clients/cin_r.jpg",
        "identity_card_image_back": "/static/uploads/clients/cin_v.jpg",
        "driving_license_image": "/static/uploads/clients/lic_r.jpg",
        "driving_license_image_back": "/static/uploads/clients/lic_v.jpg",
        "contract_image": "/static/uploads/clients/contrat.pdf",
        "notes": "Client fidèle",
    }
    body.update(over)
    resp = await client.post("/api/v1/clients/", headers=AUTH(token), json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _vehicle(db_session, reg="CED-1-A-1"):
    v = Vehicle(
        registration=reg, vin="1M8GDM9AXKP042799", brand="BMW", model="320d",
        year=2024, color="Noir", fuel_type="DIESEL", transmission="AUTOMATIC",
        current_mileage=1000, daily_rental_price=400.0, status="AVAILABLE",
    )
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)
    return v


@pytest.mark.asyncio
class TestClientProfileFields:
    async def test_address_and_contract_persist_on_create(self, client, admin_token):
        body = await _make_client(client, admin_token)
        assert body["address"] == "12 Rue des Orangers, Casablanca"
        assert body["contract_image"] == "/static/uploads/clients/contrat.pdf"

    async def test_address_and_contract_survive_a_read_back(self, client, admin_token):
        created = await _make_client(client, admin_token)
        got = await client.get(f"/api/v1/clients/{created['id']}", headers=AUTH(admin_token))
        assert got.status_code == 200
        assert got.json()["address"] == "12 Rue des Orangers, Casablanca"
        assert got.json()["contract_image"] == "/static/uploads/clients/contrat.pdf"


@pytest.mark.asyncio
class TestClientUpdateIsARealUpdate:
    async def test_update_keeps_same_client_id_and_creates_no_duplicate(
        self, client, admin_token, db_session
    ):
        created = await _make_client(client, admin_token)
        before = (await db_session.execute(select(func.count(Client.id)))).scalar()

        upd = await client.put(
            f"/api/v1/clients/{created['id']}",
            headers=AUTH(admin_token),
            json={"phone": "0611111111"},
        )
        assert upd.status_code == 200, upd.text
        assert upd.json()["id"] == created["id"], "the client_id must never change"
        assert upd.json()["phone"] == "0611111111"

        after = (await db_session.execute(select(func.count(Client.id)))).scalar()
        assert after == before, "an edit must UPDATE, never create a second client"

    async def test_unmentioned_fields_are_left_untouched(self, client, admin_token):
        created = await _make_client(client, admin_token)
        upd = await client.put(
            f"/api/v1/clients/{created['id']}",
            headers=AUTH(admin_token),
            json={"phone": "0611111111"},
        )
        body = upd.json()
        assert body["email"] == "sami@example.test"
        assert body["address"] == "12 Rue des Orangers, Casablanca"
        assert body["identity_card_image"] == "/static/uploads/clients/cin_r.jpg"

    @pytest.mark.parametrize("cleared", ["", None])
    async def test_optional_field_can_be_emptied(self, client, admin_token, cleared):
        created = await _make_client(client, admin_token)
        upd = await client.put(
            f"/api/v1/clients/{created['id']}",
            headers=AUTH(admin_token),
            json={"email": cleared},
        )
        assert upd.status_code == 200, upd.text
        assert upd.json()["email"] is None, "an emptied optional field must clear"
        # and nothing else was touched
        assert upd.json()["phone"] == "0600000000"

    async def test_a_document_can_be_removed(self, client, admin_token):
        created = await _make_client(client, admin_token)
        upd = await client.put(
            f"/api/v1/clients/{created['id']}",
            headers=AUTH(admin_token),
            json={"identity_card_image_back": None},
        )
        assert upd.status_code == 200
        assert upd.json()["identity_card_image_back"] is None
        assert upd.json()["identity_card_image"] == "/static/uploads/clients/cin_r.jpg", \
            "removing the verso must never remove the recto"

    async def test_a_document_can_be_replaced(self, client, admin_token):
        created = await _make_client(client, admin_token)
        upd = await client.put(
            f"/api/v1/clients/{created['id']}",
            headers=AUTH(admin_token),
            json={"contract_image": "/static/uploads/clients/contrat_v2.pdf"},
        )
        assert upd.json()["contract_image"] == "/static/uploads/clients/contrat_v2.pdf"

    async def test_empty_first_name_is_rejected_outright(self, client, admin_token):
        """An empty required name never reaches the DB: the schema rejects it,
        so no partial write can leave a nameless client behind."""
        created = await _make_client(client, admin_token)
        upd = await client.put(
            f"/api/v1/clients/{created['id']}",
            headers=AUTH(admin_token),
            json={"first_name": ""},
        )
        assert upd.status_code == 422
        unchanged = await client.get(
            f"/api/v1/clients/{created['id']}", headers=AUTH(admin_token))
        assert unchanged.json()["first_name"] == "Sami"

    async def test_null_on_a_not_null_column_is_ignored_rest_still_applies(
        self, client, admin_token
    ):
        created = await _make_client(client, admin_token)
        upd = await client.put(
            f"/api/v1/clients/{created['id']}",
            headers=AUTH(admin_token),
            json={"first_name": None, "notes": ""},
        )
        assert upd.status_code == 200, upd.text
        assert upd.json()["first_name"] == "Sami", "NOT NULL column must not be cleared"
        assert upd.json()["notes"] is None, "the rest of the update still applies"


@pytest.mark.asyncio
class TestRelationAwareDeletion:
    async def test_client_without_relations_is_physically_deleted(
        self, client, admin_token, db_session
    ):
        created = await _make_client(client, admin_token, cin_number="ZZ0001")
        resp = await client.delete(
            f"/api/v1/clients/{created['id']}", headers=AUTH(admin_token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["strategy"] == "DELETED"

        gone = await client.get(
            f"/api/v1/clients/{created['id']}", headers=AUTH(admin_token))
        assert gone.status_code == 404

    async def test_client_with_reservations_is_deactivated_not_destroyed(
        self, client, admin_token, db_session
    ):
        created = await _make_client(client, admin_token, cin_number="ZZ0002")
        v = await _vehicle(db_session, reg="CED-2-B-2")
        start = datetime.now() + timedelta(days=10)
        res = await client.post(
            "/api/v1/rentals/",
            headers=AUTH(admin_token),
            json={
                "vehicle_id": str(v.id),
                "customer_id": created["id"],
                "customer_name": "Sami Alami",
                "customer_phone": "0600000000",
                "start_datetime": start.isoformat(),
                "end_datetime": (start + timedelta(days=3)).isoformat(),
                "daily_price": 400.0, "num_days": 3, "total_price": 1200.0,
                "deposit": 0, "payment_status": "PENDING",
            },
        )
        assert res.status_code == 201, res.text

        resp = await client.delete(
            f"/api/v1/clients/{created['id']}", headers=AUTH(admin_token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["strategy"] == "DEACTIVATED"
        assert resp.json()["linked_reservations"] == 1

        # The client row survives, deactivated — history is never destroyed.
        still = await client.get(
            f"/api/v1/clients/{created['id']}", headers=AUTH(admin_token))
        assert still.status_code == 200
        assert still.json()["status"] == "INACTIVE"

        # And the reservation keeps its link: integrity is intact.
        link = (await db_session.execute(
            select(Reservation).where(Reservation.customer_id == UUID(created["id"]))
        )).scalars().all()
        assert len(link) == 1
        assert str(link[0].customer_id) == created["id"]
