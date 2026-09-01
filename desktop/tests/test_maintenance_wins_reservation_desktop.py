"""Desktop canonical rule: creating an ACTIVE maintenance that overlaps a
reservation atomically cancels that reservation (status CANCELLED +
cancellation_reason='MAINTENANCE') in the SAME DomainStore.mutate()
transaction, publishes exactly ONE new store revision, and enqueues a
reservation UPDATE for the server.
Boundary equality does not overlap. Finishing maintenance frees the vehicle
while the cancelled reservation stays cancelled.
"""
import os
import sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from datetime import datetime, timezone, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.sync.queue import SyncQueueItem
from app.services.event_bus import get_event_bus
from app.sync.dashboard_cache import compute_local_overview


@pytest.fixture(autouse=True)
def clean_db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


NOW = datetime.now(timezone.utc)


def _mk_vehicle(session, vid="veh-mw"):
    session.add(LocalVehicle(
        id=vid, brand="Peugeot", model="208", status="AVAILABLE",
        daily_rental_price=250, registration="MW-1", vin="12345678901234560",
        year=2024, color="Black", fuel_type="Diesel", transmission="Manual",
        created_at=NOW.isoformat(), updated_at=NOW.isoformat(),
    ))
    session.commit()
    return vid


def _mk_reservation(session, vid, start, end, status="RESERVED", rid="res-mw"):
    session.add(LocalReservation(
        id=rid, vehicle_id=vid, customer_name="Client Test",
        start_datetime=start.isoformat(), end_datetime=end.isoformat(),
        daily_price=250, num_days=3, total_price=750, deposit=0,
        status=status, created_at=NOW.isoformat(), updated_at=NOW.isoformat(),
        version=1,
    ))
    session.commit()
    return rid


def _make_window(qapp, request):
    from app.ui.main_window import MainWindow
    w = MainWindow(user_data={"user_id": "u-1", "access_token": "x", "offline": True})
    request.addfinalizer(lambda: (w.close(), w.deleteLater(), qapp.processEvents()))
    qapp.processEvents()
    return w


def _maint_payload(vid, start, end):
    return {
        "vehicle_id": vid, "type": "Panne", "description": "moteur",
        "start_datetime": start.isoformat(),
        "expected_end_datetime": end.isoformat(),
        "step": "DIAGNOSTIC", "status": "ACTIVE",
    }


@pytest.mark.parametrize("res_status", ["RESERVED", "ACTIVE"])
def test_overlapping_maintenance_cancels_reservation(qapp, request, monkeypatch, res_status):
    s = get_local_session()
    vid = _mk_vehicle(s)
    rid = _mk_reservation(s, vid, NOW + timedelta(days=2), NOW + timedelta(days=8), status=res_status)
    s.close()

    w = _make_window(qapp, request)
    monkeypatch.setattr(w, "_run_sync", lambda: None)

    # The whole "maintenance wins" operation (insert maintenance + cancel the
    # overlapping reservation) is ONE DomainStore.mutate() transaction and
    # publishes exactly ONE new revision.
    rev_before = w._store.revision

    w._create_maintenance_record(_maint_payload(vid, NOW + timedelta(days=3), NOW + timedelta(days=5)))

    s = get_local_session()
    r = s.query(LocalReservation).filter_by(id=rid).first()
    assert r.status == "CANCELLED"
    assert r.cancellation_reason == "MAINTENANCE"
    # one maintenance CREATE + one reservation UPDATE enqueued
    kinds = sorted((i.entity_type, i.operation) for i in s.query(SyncQueueItem).all())
    assert ("maintenance", "CREATE") in kinds
    assert ("reservation", "UPDATE") in kinds
    s.close()

    # exactly one published revision for the whole operation
    assert w._store.revision == rev_before + 1


def test_boundary_equality_does_not_cancel(qapp, request, monkeypatch):
    s = get_local_session()
    vid = _mk_vehicle(s)
    # reservation starts exactly when maintenance ends
    rid = _mk_reservation(s, vid, NOW + timedelta(days=5), NOW + timedelta(days=9))
    s.close()

    w = _make_window(qapp, request)
    monkeypatch.setattr(w, "_run_sync", lambda: None)
    w._create_maintenance_record(_maint_payload(vid, NOW + timedelta(days=2), NOW + timedelta(days=5)))

    s = get_local_session()
    r = s.query(LocalReservation).filter_by(id=rid).first()
    assert r.status == "RESERVED"
    assert r.cancellation_reason is None
    s.close()


def test_dashboard_and_effective_status_converge(qapp, request, monkeypatch):
    s = get_local_session()
    vid = _mk_vehicle(s)
    # RESERVED reservation whose window already contains "now" -> time-derived
    # RENTED (this business has no separate pickup step), not "reserved".
    _mk_reservation(s, vid, NOW - timedelta(days=1), NOW + timedelta(days=6))
    s.close()

    before = compute_local_overview()
    assert before["rented"] == 1
    assert before["reserved"] == 0

    w = _make_window(qapp, request)
    monkeypatch.setattr(w, "_run_sync", lambda: None)
    w._create_maintenance_record(_maint_payload(vid, NOW - timedelta(hours=1), NOW + timedelta(days=4)))

    after = compute_local_overview()
    assert after["rented"] == 0
    assert after["maintenance"] == 1

    # vehicle effective status seen by the vehicles view
    loaded = {}
    monkeypatch.setattr(w._vehicle_list, "load_vehicles", lambda vs: loaded.update({v["id"]: v for v in vs}))
    w._load_vehicles_from_local()
    assert loaded[vid]["status"] == "MAINTENANCE"


def test_finish_maintenance_frees_vehicle_reservation_stays_cancelled(qapp, request, monkeypatch):
    s = get_local_session()
    vid = _mk_vehicle(s)
    rid = _mk_reservation(s, vid, NOW - timedelta(days=1), NOW + timedelta(days=6))
    s.close()

    w = _make_window(qapp, request)
    monkeypatch.setattr(w, "_run_sync", lambda: None)
    w._create_maintenance_record(_maint_payload(vid, NOW - timedelta(hours=1), NOW + timedelta(days=4)))

    s = get_local_session()
    m = s.query(LocalMaintenance).filter_by(vehicle_id=vid).first()
    m.status = "COMPLETED"
    m.actual_end_datetime = datetime.now(timezone.utc).isoformat()
    s.commit()
    s.close()

    ov = compute_local_overview()
    assert ov["maintenance"] == 0

    s = get_local_session()
    r = s.query(LocalReservation).filter_by(id=rid).first()
    assert r.status == "CANCELLED" and r.cancellation_reason == "MAINTENANCE"
    s.close()

    loaded = {}
    monkeypatch.setattr(w._vehicle_list, "load_vehicles", lambda vs: loaded.update({v["id"]: v for v in vs}))
    w._load_vehicles_from_local()
    assert loaded[vid]["status"] == "AVAILABLE"
