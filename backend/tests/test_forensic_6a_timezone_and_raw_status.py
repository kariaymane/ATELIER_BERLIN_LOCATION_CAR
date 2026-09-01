"""INCREMENT 6A — forensic P0 regression guards (backend).

P0-B: a maintenance ticket must never make the RAW ``vehicle.status`` column
disagree with the CANONICAL effective status. Only a maintenance whose window
is open RIGHT NOW may set the raw MAINTENANCE hold; a future-dated ticket must
leave the raw column alone and rely on the interval derivation.

Covers the brief's Test B / C / D / E.
"""
import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.models.maintenance import Maintenance
from app.services.fleet_status import compute_effective_statuses


async def _mk_vehicle(db, status="AVAILABLE"):
    v_id = uuid4()
    db.add(Vehicle(
        id=v_id, brand="T", model="A", registration=f"6A-{v_id.hex[:5]}",
        vin=f"VIN{v_id.hex[:14]}", year=2026, color="Noir",
        fuel_type="GASOLINE", transmission="AUTOMATIC", daily_rental_price=10,
        status=status,
    ))
    await db.flush()
    return v_id


# ── Test B — future maintenance -> effective AVAILABLE, raw NOT stuck ──────────
@pytest.mark.asyncio
async def test_future_maintenance_keeps_vehicle_available(client, db_session, admin_token):
    v_id = await _mk_vehicle(db_session)
    await db_session.commit()

    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = start + timedelta(days=2)
    resp = await client.post(
        "/api/v1/maintenance/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "vehicle_id": str(v_id), "type": "Entretien", "description": "future",
            "start_datetime": start.isoformat(),
            "expected_end_datetime": end.isoformat(),
            "status": "ACTIVE",
        },
    )
    assert resp.status_code == 201, resp.text
    db_session.expire_all()

    # raw column must NOT have been flipped
    raw = (await db_session.execute(
        select(Vehicle.status).where(Vehicle.id == v_id))).scalar_one()
    assert raw != "MAINTENANCE", "future maintenance stuck the raw vehicle.status"

    # canonical effective status is AVAILABLE until the window opens
    eff = await compute_effective_statuses(db_session, [v_id], now=datetime.now(timezone.utc))
    assert eff[str(v_id)] == "AVAILABLE"

    # Test E — the two authorities must not contradict
    assert not (raw == "MAINTENANCE" and eff[str(v_id)] == "AVAILABLE")


# ── Test C — active maintenance -> effective MAINTENANCE ──────────────────────
@pytest.mark.asyncio
async def test_active_maintenance_marks_vehicle_maintenance(client, db_session, admin_token):
    v_id = await _mk_vehicle(db_session)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    resp = await client.post(
        "/api/v1/maintenance/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "vehicle_id": str(v_id), "type": "Panne", "description": "now",
            "start_datetime": (now - timedelta(hours=1)).isoformat(),
            "expected_end_datetime": (now + timedelta(hours=2)).isoformat(),
            "status": "ACTIVE",
        },
    )
    assert resp.status_code == 201, resp.text
    db_session.expire_all()

    eff = await compute_effective_statuses(db_session, [v_id], now=datetime.now(timezone.utc))
    assert eff[str(v_id)] == "MAINTENANCE"

    raw = (await db_session.execute(
        select(Vehicle.status).where(Vehicle.id == v_id))).scalar_one()
    assert raw == "MAINTENANCE"  # currently-active window may hold the raw flag


# ── Test D — half-open [start, end): exactly at end -> not MAINTENANCE ────────
@pytest.mark.asyncio
async def test_maintenance_end_frees_vehicle_half_open(db_session: AsyncSession):
    v_id = await _mk_vehicle(db_session)
    end = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    db_session.add(Maintenance(
        id=uuid4(), vehicle_id=v_id, status="ACTIVE", type="Entretien",
        start_datetime=end - timedelta(hours=4),
        expected_end_datetime=end,
    ))
    await db_session.commit()

    at_end = await compute_effective_statuses(db_session, [v_id], now=end)
    assert at_end[str(v_id)] != "MAINTENANCE"

    just_before = await compute_effective_statuses(
        db_session, [v_id], now=end - timedelta(minutes=1))
    assert just_before[str(v_id)] == "MAINTENANCE"


# ── Test E (explicit) — future maintenance never contradicts ─────────────────
@pytest.mark.asyncio
async def test_raw_and_effective_never_contradict_for_future_ticket(client, db_session, admin_token):
    v_id = await _mk_vehicle(db_session)
    await db_session.commit()
    start = datetime.now(timezone.utc) + timedelta(days=3)
    resp = await client.post(
        "/api/v1/maintenance/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "vehicle_id": str(v_id), "type": "Entretien", "description": "far future",
            "start_datetime": start.isoformat(),
            "expected_end_datetime": (start + timedelta(days=1)).isoformat(),
            "status": "ACTIVE",
        },
    )
    assert resp.status_code == 201, resp.text
    db_session.expire_all()

    raw = (await db_session.execute(
        select(Vehicle.status).where(Vehicle.id == v_id))).scalar_one()
    eff = (await compute_effective_statuses(
        db_session, [v_id], now=datetime.now(timezone.utc)))[str(v_id)]
    # neither "raw says MAINTENANCE while effective says AVAILABLE" nor vice-versa
    assert (raw == "MAINTENANCE") == (eff == "MAINTENANCE")
