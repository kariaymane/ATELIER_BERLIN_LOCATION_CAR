"""Single source of truth for fleet status.

`/vehicles` (effective_status), `/vehicles/stats` and `/dashboard/stats` are all
derived from app.services.fleet_status and must never disagree:

  * the four operational buckets are mutually exclusive and sum to total_vehicles
  * every vehicle's effective_status equals its dashboard bucket
  * active_maintenance_tickets == maintenance (one maintenance number)
  * an open-ended active maintenance still occupies its vehicle
"""
import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.models.reservation import Reservation
from app.models.maintenance import Maintenance
from app.services.fleet_status import compute_fleet_counts, compute_effective_statuses

NOW = datetime.now(timezone.utc)


async def _v(db, status="AVAILABLE"):
    vid = uuid4()
    db.add(Vehicle(
        id=vid, brand="T", model="A", registration=f"FS-{vid.hex[:6]}",
        vin=f"VIN{vid.hex[:14]}", year=2026, color="Noir",
        fuel_type="GASOLINE", transmission="AUTOMATIC", daily_rental_price=10,
        status=status,
    ))
    await db.flush()
    return vid


async def _res(db, vid, status, start, end):
    db.add(Reservation(
        id=uuid4(), vehicle_id=vid, status=status,
        start_datetime=start, end_datetime=end, customer_name="X",
        customer_phone="123", daily_price=10, num_days=1, total_price=10, deposit=0,
    ))
    await db.flush()


async def _maint(db, vid, start, end, status="ACTIVE"):
    db.add(Maintenance(
        id=uuid4(), vehicle_id=vid, type="X", status=status,
        start_datetime=start, expected_end_datetime=end,
    ))
    await db.flush()


@pytest.mark.asyncio
async def test_buckets_are_exclusive_and_sum_to_total(db_session: AsyncSession):
    av = await _v(db_session)                                   # AVAILABLE
    rs = await _v(db_session)
    await _res(db_session, rs, "RESERVED", NOW - timedelta(hours=1), NOW + timedelta(days=3))
    rt = await _v(db_session)
    await _res(db_session, rt, "ACTIVE", NOW - timedelta(hours=1), NOW + timedelta(days=3))
    mt = await _v(db_session)
    await _maint(db_session, mt, NOW - timedelta(hours=1), NOW + timedelta(days=2))
    endless = await _v(db_session)
    await _maint(db_session, endless, NOW - timedelta(hours=1), None)
    future_res = await _v(db_session)                           # RESERVED (upcoming booking)
    await _res(db_session, future_res, "RESERVED", NOW + timedelta(days=10), NOW + timedelta(days=12))
    sold = await _v(db_session, status="SOLD")                  # excluded from total
    await db_session.commit()

    counts = await compute_fleet_counts(db_session)
    assert counts["total_vehicles"] == 6  # 7 minus SOLD
    assert counts["available"] + counts["reserved"] + counts["rented"] + counts["maintenance"] == counts["total_vehicles"]
    assert counts["available"] == 1       # av
    assert counts["reserved"] == 1       # future_res (upcoming)
    assert counts["rented"] == 2         # rs (RESERVED status, started) + rt (ACTIVE)
    assert counts["maintenance"] == 2     # mt + endless

    eff = await compute_effective_statuses(db_session)
    assert eff[str(av)] == "AVAILABLE"
    # rs has a RESERVED-status reservation that STARTED an hour ago -> the car
    # is out -> RENTED (time-derived, no pickup step).
    assert eff[str(rs)] == "RENTED"
    assert eff[str(rt)] == "RENTED"
    assert eff[str(mt)] == "MAINTENANCE"
    assert eff[str(endless)] == "MAINTENANCE"
    # future_res starts in 10 days -> surfaced as an upcoming RESERVED.
    assert eff[str(future_res)] == "RESERVED"
    assert eff[str(sold)] == "SOLD"


@pytest.mark.asyncio
async def test_maintenance_wins_in_effective_status(db_session: AsyncSession):
    """A vehicle with BOTH an active reservation and active maintenance counts
    once, as MAINTENANCE (not double-counted)."""
    v = await _v(db_session)
    await _res(db_session, v, "ACTIVE", NOW - timedelta(hours=1), NOW + timedelta(days=3))
    await _maint(db_session, v, NOW - timedelta(hours=1), NOW + timedelta(days=2))
    await db_session.commit()
    counts = await compute_fleet_counts(db_session)
    assert counts["maintenance"] == 1
    assert counts["rented"] == 0
    assert counts["available"] + counts["reserved"] + counts["rented"] + counts["maintenance"] == counts["total_vehicles"] == 1


@pytest.mark.asyncio
async def test_dashboard_vehicles_and_stats_endpoints_agree(client, db_session: AsyncSession, admin_token):
    av = await _v(db_session)
    rt = await _v(db_session)
    await _res(db_session, rt, "ACTIVE", NOW - timedelta(hours=1), NOW + timedelta(days=3))
    mt = await _v(db_session)
    await _maint(db_session, mt, NOW - timedelta(hours=1), None)  # open-ended
    await db_session.commit()

    h = {"Authorization": f"Bearer {admin_token}"}
    dash = (await client.get("/api/v1/dashboard/stats", headers=h)).json()
    vlist = (await client.get("/api/v1/vehicles/?page_size=500", headers=h)).json()
    vstats = (await client.get("/api/v1/vehicles/stats", headers=h)).json()["status_counts"]

    # dashboard internal consistency
    assert dash["available"] + dash["reserved"] + dash["rented"] + dash["maintenance"] == dash["total_vehicles"] == 3
    assert dash["active_maintenance_tickets"] == dash["maintenance"] == 1
    assert dash["rented"] == 1

    # /vehicles effective_status tally == dashboard buckets
    tally = {"AVAILABLE": 0, "RESERVED": 0, "RENTED": 0, "MAINTENANCE": 0}
    by_id = {}
    for v in vlist["vehicles"]:
        tally[v["effective_status"]] = tally.get(v["effective_status"], 0) + 1
        by_id[v["id"]] = v["effective_status"]
    assert tally["AVAILABLE"] == dash["available"]
    assert tally["RENTED"] == dash["rented"]
    assert tally["MAINTENANCE"] == dash["maintenance"]
    assert by_id[str(mt)] == "MAINTENANCE"
    assert by_id[str(rt)] == "RENTED"
    assert by_id[str(av)] == "AVAILABLE"

    # /vehicles/stats == dashboard
    assert vstats.get("MAINTENANCE", 0) == dash["maintenance"]
    assert vstats.get("RENTED", 0) == dash["rented"]
    assert vstats.get("AVAILABLE", 0) == dash["available"]
