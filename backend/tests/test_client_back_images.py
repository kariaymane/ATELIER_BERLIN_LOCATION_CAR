"""Two-sided identity documents: CIN + driving licence each have a recto
(front, legacy column) and a verso (back, new *_back column). The two sides
must persist independently; uploading a back must never overwrite the front;
legacy clients with only a front image keep working.
"""
import pytest
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client


@pytest.mark.asyncio
async def test_create_client_with_both_sides(client, admin_token):
    resp = await client.post(
        "/api/v1/clients/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "first_name": "Sara", "last_name": "B",
            "identity_card_image": "/static/uploads/clients/cin_front.jpg",
            "identity_card_image_back": "/static/uploads/clients/cin_back.jpg",
            "driving_license_image": "/static/uploads/clients/lic_front.jpg",
            "driving_license_image_back": "/static/uploads/clients/lic_back.jpg",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["identity_card_image"] == "/static/uploads/clients/cin_front.jpg"
    assert body["identity_card_image_back"] == "/static/uploads/clients/cin_back.jpg"
    assert body["driving_license_image_back"] == "/static/uploads/clients/lic_back.jpg"
    assert body["identity_card_image"] != body["identity_card_image_back"]


@pytest.mark.asyncio
async def test_update_back_only_keeps_front(client, admin_token):
    created = await client.post(
        "/api/v1/clients/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "first_name": "Omar", "last_name": "K",
            "identity_card_image": "/static/uploads/clients/front_original.jpg",
        },
    )
    cid = created.json()["id"]

    upd = await client.put(
        f"/api/v1/clients/{cid}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"identity_card_image_back": "/static/uploads/clients/back_new.jpg"},
    )
    assert upd.status_code == 200, upd.text
    body = upd.json()
    assert body["identity_card_image"] == "/static/uploads/clients/front_original.jpg"
    assert body["identity_card_image_back"] == "/static/uploads/clients/back_new.jpg"


@pytest.mark.asyncio
async def test_legacy_client_front_only_serializes(client, db_session: AsyncSession, admin_token):
    c = Client(
        id=uuid4(), first_name="Legacy", last_name="User",
        identity_card_image="/static/uploads/clients/legacy.jpg",
    )
    db_session.add(c)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/clients/{c.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["identity_card_image"] == "/static/uploads/clients/legacy.jpg"
    assert body["identity_card_image_back"] is None
    assert body["driving_license_image_back"] is None


@pytest.mark.asyncio
async def test_sync_bootstrap_and_pull_include_back_fields(db_session: AsyncSession, admin_user):
    from app.services.sync_service import SyncService
    from datetime import datetime, timezone, timedelta

    c = Client(
        id=uuid4(), first_name="Sync", last_name="Client",
        identity_card_image="f.jpg", identity_card_image_back="b.jpg",
        driving_license_image="lf.jpg", driving_license_image_back="lb.jpg",
    )
    db_session.add(c)
    await db_session.commit()

    boot = await SyncService(db_session).get_bootstrap(admin_user.id)
    payload = next(cl for cl in boot["clients"] if str(cl.id) == str(c.id))
    assert payload.identity_card_image_back == "b.jpg"
    assert payload.driving_license_image_back == "lb.jpg"

    pull = await SyncService(db_session).process_pull(
        since=datetime.now(timezone.utc) - timedelta(days=1),
        entity_types=["client"], user_id=admin_user.id,
    )
    cpayload = next(i["payload"] for i in pull["items"] if i["entity_id"] == str(c.id))
    assert cpayload["identity_card_image_back"] == "b.jpg"
    assert cpayload["driving_license_image_back"] == "lb.jpg"
