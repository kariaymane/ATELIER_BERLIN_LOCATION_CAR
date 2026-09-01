"""Canonical rule: an ACTIVE maintenance period WINS over an overlapping
reservation. The reservation is atomically moved to CANCELLED with a
machine-readable ``cancellation_reason = 'MAINTENANCE'``; it is preserved for
history, never deleted or hidden.

These tests exercise the application/service layer (SQLite in-memory) — the
Postgres trigger is not involved.
"""
import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.models.reservation import Reservation
from app.models.maintenance import Maintenance
from app.repositories.rental_repository import RentalRepository


async def _mk_vehicle(db, status="AVAILABLE"):
    v_id = uuid4()
    db.add(Vehicle(
        id=v_id, brand="T", model="A", registration=f"MW-{v_id.hex[:5]}",
        vin=f"VIN{v_id.hex[:14]}", year=2026, color="Noir",
        fuel_type="GASOLINE", transmission="AUTOMATIC", daily_rental_price=10,
        status=status,
    ))
    await db.flush()
    return v_id


async def _mk_reservation(db, v_id, status, start, end):
    r = Reservation(
        id=uuid4(), vehicle_id=v_id, status=status,
        start_datetime=start, end_datetime=end,
        customer_name="Test", customer_phone="12345", customer_email="t@t.com",
        daily_price=10, num_days=1, total_price=10, deposit=0,
    )
    db.add(r)
    await db.flush()
    return r


async def _mk_maintenance(db, v_id, start, end, status="ACTIVE"):
    m = Maintenance(
        id=uuid4(), vehicle_id=v_id, type="PREVENTIVE", status=status,
        start_datetime=start, expected_end_datetime=end,
    )
    db.add(m)
    await db.flush()
    return m


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_active_maintenance_cancels_reserved(db_session: AsyncSession):
    v = await _mk_vehicle(db_session)
    r = await _mk_reservation(db_session, v, "RESERVED", NOW + timedelta(days=2), NOW + timedelta(days=6))
    m = await _mk_maintenance(db_session, v, NOW + timedelta(days=3), NOW + timedelta(days=5))

    cancelled = await RentalRepository(db_session).cancel_overlapping_reservations(
        v, m.start_datetime, m.expected_end_datetime
    )
    assert [c.id for c in cancelled] == [r.id]
    await db_session.refresh(r)
    assert r.status == "CANCELLED"
    assert r.cancellation_reason == "MAINTENANCE"  # machine value, not translated


@pytest.mark.asyncio
async def test_active_maintenance_cancels_active_rental(db_session: AsyncSession):
    v = await _mk_vehicle(db_session)
    r = await _mk_reservation(db_session, v, "ACTIVE", NOW, NOW + timedelta(days=10))
    m = await _mk_maintenance(db_session, v, NOW + timedelta(days=1), NOW + timedelta(days=2))

    await RentalRepository(db_session).cancel_overlapping_reservations(
        v, m.start_datetime, m.expected_end_datetime
    )
    await db_session.refresh(r)
    assert r.status == "CANCELLED"
    assert r.cancellation_reason == "MAINTENANCE"


@pytest.mark.asyncio
async def test_completed_and_cancelled_reservations_untouched(db_session: AsyncSession):
    v = await _mk_vehicle(db_session)
    done = await _mk_reservation(db_session, v, "COMPLETED", NOW, NOW + timedelta(days=10))
    void = await _mk_reservation(db_session, v, "CANCELLED", NOW, NOW + timedelta(days=10))
    void_ver, done_ver = void.version, done.version
    m = await _mk_maintenance(db_session, v, NOW + timedelta(days=1), NOW + timedelta(days=2))

    cancelled = await RentalRepository(db_session).cancel_overlapping_reservations(
        v, m.start_datetime, m.expected_end_datetime
    )
    assert cancelled == []
    await db_session.refresh(done)
    await db_session.refresh(void)
    assert done.status == "COMPLETED" and done.version == done_ver
    assert void.status == "CANCELLED" and void.version == void_ver
    assert void.cancellation_reason is None  # not overwritten


@pytest.mark.asyncio
async def test_boundary_equality_does_not_overlap(db_session: AsyncSession):
    v = await _mk_vehicle(db_session)
    # reservation ends exactly when maintenance starts
    before = await _mk_reservation(db_session, v, "RESERVED", NOW, NOW + timedelta(days=3))
    # reservation starts exactly when maintenance ends
    after = await _mk_reservation(db_session, v, "RESERVED", NOW + timedelta(days=5), NOW + timedelta(days=9))
    m_start = NOW + timedelta(days=3)
    m_end = NOW + timedelta(days=5)

    cancelled = await RentalRepository(db_session).cancel_overlapping_reservations(v, m_start, m_end)
    assert cancelled == []
    await db_session.refresh(before)
    await db_session.refresh(after)
    assert before.status == "RESERVED"
    assert after.status == "RESERVED"


@pytest.mark.asyncio
async def test_open_ended_maintenance_occupies_until_closed(db_session: AsyncSession):
    """CANONICAL: an active maintenance with no explicit end is open-ended —
    it occupies the vehicle (and cancels overlapping reservations) until it is
    closed. maint_end=None => FAR_FUTURE."""
    v = await _mk_vehicle(db_session)
    r = await _mk_reservation(db_session, v, "RESERVED", NOW, NOW + timedelta(days=10))
    cancelled = await RentalRepository(db_session).cancel_overlapping_reservations(
        v, NOW + timedelta(days=1), None
    )
    assert [c.id for c in cancelled] == [r.id]
    await db_session.refresh(r)
    assert r.status == "CANCELLED"
    assert r.cancellation_reason == "MAINTENANCE"
    # a reservation entirely BEFORE the maintenance start is untouched
    before = await _mk_reservation(
        db_session, v, "RESERVED", NOW - timedelta(days=5), NOW - timedelta(days=1)
    )
    cancelled2 = await RentalRepository(db_session).cancel_overlapping_reservations(
        v, NOW + timedelta(days=1), None
    )
    assert cancelled2 == []
    await db_session.refresh(before)
    assert before.status == "RESERVED"


@pytest.mark.asyncio
async def test_create_maintenance_api_no_longer_409_and_cancels(client, db_session, admin_token):
    v = await _mk_vehicle(db_session)
    r = await _mk_reservation(db_session, v, "RESERVED", NOW + timedelta(days=1), NOW + timedelta(days=9))
    r_id, v_id = r.id, v
    await db_session.commit()
    db_session.expunge_all()

    resp = await client.post(
        "/api/v1/maintenance/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "vehicle_id": str(v_id),
            "type": "Panne",
            "description": "moteur",
            "start_datetime": (NOW + timedelta(days=2)).isoformat(),
            "expected_end_datetime": (NOW + timedelta(days=4)).isoformat(),
            "status": "ACTIVE",
        },
    )
    assert resp.status_code == 201, resp.text

    row = (await db_session.execute(select(Reservation).where(Reservation.id == r_id))).scalar_one()
    assert row.status == "CANCELLED"
    assert row.cancellation_reason == "MAINTENANCE"

    # FORENSIC P0-B: a FUTURE-dated maintenance (start = NOW + 2 days) must NOT
    # stick the raw vehicle.status to MAINTENANCE. "Maintenance wins" still
    # cancels the overlapping reservation above (interval rule), but the raw
    # column stays AVAILABLE so it cannot contradict the canonical effective
    # status, which is also AVAILABLE until the window opens.
    v_row = await db_session.execute(select(Vehicle.status).where(Vehicle.id == v_id))
    assert v_row.scalar_one() != "MAINTENANCE"


@pytest.mark.asyncio
async def test_availability_before_and_after_maintenance(client, db_session, admin_token):
    v = await _mk_vehicle(db_session)
    await db_session.commit()
    repo = RentalRepository(db_session)

    resp = await client.post(
        "/api/v1/maintenance/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "vehicle_id": str(v), "type": "Entretien",
            "start_datetime": (NOW).isoformat(),
            "expected_end_datetime": (NOW + timedelta(days=3)).isoformat(),
            "status": "ACTIVE",
        },
    )
    assert resp.status_code == 201, resp.text
    m_id = resp.json()["id"]

    db_session.expire_all()
    avail, reason = await repo.check_availability(v, NOW + timedelta(days=1), NOW + timedelta(days=2))
    assert avail is False and reason == "MAINTENANCE"

    done = await client.post(
        f"/api/v1/maintenance/{m_id}/complete",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert done.status_code == 200, done.text

    db_session.expire_all()
    avail, reason = await repo.check_availability(v, NOW + timedelta(days=1), NOW + timedelta(days=2))
    assert avail is True and reason is None


@pytest.mark.asyncio
async def test_dashboard_excludes_maintenance_cancelled_reservation(db_session: AsyncSession):
    from app.services.dashboard_service import DashboardService
    v = await _mk_vehicle(db_session)
    # a reservation overlapping "now" that will be cancelled by maintenance
    real_now = datetime.now(timezone.utc)
    r = await _mk_reservation(db_session, v, "RESERVED", real_now - timedelta(days=1), real_now + timedelta(days=5))
    m = await _mk_maintenance(db_session, v, real_now - timedelta(hours=1), real_now + timedelta(days=2))
    await RentalRepository(db_session).cancel_overlapping_reservations(v, m.start_datetime, m.expected_end_datetime)
    await db_session.commit()

    overview = await DashboardService(db_session).get_overview()
    assert overview["reserved"] == 0
    assert overview["reserved_rentals"] == 0
    assert overview["active_maintenance_tickets"] == 1


@pytest.mark.asyncio
async def test_atomicity_maintenance_not_persisted_if_cancel_fails(client, db_session, admin_token, monkeypatch):
    v = await _mk_vehicle(db_session)
    r = await _mk_reservation(db_session, v, "RESERVED", NOW + timedelta(days=1), NOW + timedelta(days=9))
    r_id, v_id = r.id, v
    await db_session.commit()
    db_session.expunge_all()

    async def boom(*a, **k):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(RentalRepository, "cancel_overlapping_reservations", boom)

    with pytest.raises(RuntimeError, match="injected failure"):
        await client.post(
            "/api/v1/maintenance/",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "vehicle_id": str(v_id), "type": "Panne",
                "start_datetime": (NOW + timedelta(days=2)).isoformat(),
                "expected_end_datetime": (NOW + timedelta(days=4)).isoformat(),
                "status": "ACTIVE",
            },
        )

    row = (await db_session.execute(select(Reservation).where(Reservation.id == r_id))).scalar_one()
    assert row.status == "RESERVED"
    maint = (await db_session.execute(select(Maintenance).where(Maintenance.vehicle_id == v_id))).scalars().all()
    assert maint == []
    vs = (await db_session.execute(select(Vehicle.status).where(Vehicle.id == v_id))).scalar_one()
    assert vs == "AVAILABLE"


@pytest.mark.asyncio
async def test_sync_push_maintenance_cancels_reservation(db_session: AsyncSession, admin_user):
    from app.services.sync_service import SyncService
    from types import SimpleNamespace

    v = await _mk_vehicle(db_session)
    r = await _mk_reservation(db_session, v, "RESERVED", NOW + timedelta(days=1), NOW + timedelta(days=9))
    r_id = r.id
    await db_session.commit()
    db_session.expunge_all()

    svc = SyncService(db_session)
    item = SimpleNamespace(
        idempotency_key=str(uuid4()), entity_type="maintenance", entity_id=str(uuid4()),
        operation="CREATE", version=1, device_id="dev1",
        payload={
            "id": str(uuid4()), "vehicle_id": str(v), "type": "Panne",
            "start_datetime": (NOW + timedelta(days=2)).isoformat(),
            "expected_end_datetime": (NOW + timedelta(days=4)).isoformat(),
            "status": "ACTIVE",
        },
    )
    results = await svc.process_push([item], admin_user.id)
    await db_session.commit()
    assert results[0]["status"] == "ok"
    assert str(r_id) in results[0]["cancelled_reservation_ids"]

    row = (await db_session.execute(select(Reservation).where(Reservation.id == r_id))).scalar_one()
    assert row.status == "CANCELLED" and row.cancellation_reason == "MAINTENANCE"
