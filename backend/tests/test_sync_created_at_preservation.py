import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from app.services.sync_service import SyncService
from app.models.vehicle import Vehicle
from app.models.reservation import Reservation
from app.models.maintenance import Maintenance
from app.models.client import Client


@pytest.mark.asyncio
async def test_process_pull_includes_created_at(db_session, admin_user):
    service = SyncService(db_session)
    now = datetime.now(timezone.utc)

    # This test seeds a vehicle that has BOTH an active reservation and an
    # active maintenance (to prove all four entity payloads carry created_at).
    # PostgreSQL's reservation<->maintenance overlap trigger blocks that raw
    # combination (it is a booking guard, not a derivation rule), so suppress
    # it for the fixture only — no-op on SQLite.
    from sqlalchemy import text
    try:
        await db_session.execute(text("SET session_replication_role = replica"))
    except Exception:
        pass

    # 1. Create entities with explicit created_at
    vid = uuid4()
    v = Vehicle(
        id=vid,
        registration=f"PULL-{uuid4().hex[:4]}",
        vin=f"VIN{uuid4().hex[:14]}",
        brand="PullBrand",
        model="PullModel",
        year=2023,
        color="Noir",
        fuel_type="GASOLINE",
        transmission="AUTOMATIC",
        daily_rental_price=500.0,
        status="AVAILABLE",
        created_at=now,
        created_by=admin_user.id,
    )
    db_session.add(v)

    cid = uuid4()
    c = Client(
        id=cid,
        first_name="John",
        last_name="Doe",
        phone="+212600000000",
        email=f"client-{uuid4().hex[:6]}@example.com",
        cin_number="AB123456",
        created_at=now,
    )
    db_session.add(c)

    rid = uuid4()
    r = Reservation(
        id=rid,
        vehicle_id=vid,
        customer_name="John Doe",
        customer_phone="+212600000000",
        start_datetime=now,
        end_datetime=now + timedelta(days=3),
        daily_price=500.0,
        num_days=3,
        total_price=1500.0,
        status="ACTIVE",
        created_at=now,
        created_by=admin_user.id,
    )
    db_session.add(r)

    mid = uuid4()
    m = Maintenance(
        id=mid,
        vehicle_id=vid,
        type="Entretien",
        start_datetime=now,
        status="ACTIVE",
        created_at=now,
        created_by=admin_user.id,
    )
    db_session.add(m)
    await db_session.commit()

    # 2. Call process_pull
    res = await service.process_pull(
        since=datetime(2000, 1, 1, tzinfo=timezone.utc),
        user_id=admin_user.id,
    )

    items = res["items"]
    pulled_v = next((i for i in items if i["entity_type"] == "vehicle" and i["entity_id"] == str(vid)), None)
    pulled_r = next((i for i in items if i["entity_type"] == "reservation" and i["entity_id"] == str(rid)), None)
    pulled_m = next((i for i in items if i["entity_type"] == "maintenance" and i["entity_id"] == str(mid)), None)
    pulled_c = next((i for i in items if i["entity_type"] == "client" and i["entity_id"] == str(cid)), None)

    assert pulled_v is not None
    assert "created_at" in pulled_v["payload"]
    assert pulled_v["payload"]["created_at"] is not None

    assert pulled_r is not None
    assert "created_at" in pulled_r["payload"]
    assert pulled_r["payload"]["created_at"] is not None

    assert pulled_m is not None
    assert "created_at" in pulled_m["payload"]
    assert pulled_m["payload"]["created_at"] is not None

    assert pulled_c is not None
    assert "created_at" in pulled_c["payload"]
    assert pulled_c["payload"]["created_at"] is not None
