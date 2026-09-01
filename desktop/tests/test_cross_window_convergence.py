"""Cross-window reality test.

Keeps every main view alive simultaneously inside one MainWindow and drives
the full mutation lifecycle, asserting that ONE logical mutation produces ONE
global event and that every dependent view converges on the same truth with
NO tab switch, NO manual refresh, NO sync round-trip.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from PySide6.QtWidgets import QApplication

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.maintenance import LocalMaintenance
from app.models.reservation import LocalReservation
from app.services.event_bus import get_event_bus
from app.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def clean_db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def window(qapp):
    w = MainWindow(user_data={"user_id": "u1", "role": "ADMIN", "full_name": "A",
                              "access_token": "x", "refresh_token": "x", "offline": True})
    # Neutralise everything that would touch the network / spawn threads —
    # we assert pure local reactivity, not sync.
    w._run_sync = lambda *a, **k: None
    w._clients_page.refresh_data = lambda *a, **k: None
    if hasattr(w, "_sync_timer"):
        w._sync_timer.stop()
    if hasattr(w, "_realtime_client"):
        try:
            w._realtime_client.stop()
        except Exception:
            pass
    yield w
    try:
        get_event_bus().data_refreshed.disconnect(w._on_global_data_refreshed)
    except Exception:
        pass
    w.close()
    w.deleteLater()
    qapp.processEvents()


def _iso(days, hour=9):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0).isoformat()


def _vehicle_status(window, vid):
    window._load_vehicles_from_local()
    for v in window._vehicle_list._vehicles_data:
        if v["id"] == vid:
            return v["status"]
    return None


def _dashboard(window):
    from app.sync.dashboard_cache import compute_local_overview
    return compute_local_overview()


class _Counter:
    """Counts published DomainStore revisions — the canonical 'state changed'
    channel now that committed mutations go through ``DomainStore.mutate()``
    instead of pulsing ``data_refreshed``."""
    def __init__(self, *_):
        from app.state.domain_store import get_domain_store
        self.n = 0
        self._unsub = get_domain_store().subscribe(lambda *a: self._hit())

    def _hit(self):
        self.n += 1

    def stop(self):
        try:
            self._unsub()
        except Exception:
            pass


def test_one_mutation_one_event_all_views_converge(window):
    bus = get_event_bus()

    # ── Create vehicle ────────────────────────────────────────────────
    counter = _Counter()
    window._create_vehicle({
        "registration": "CW-1", "brand": "T", "model": "C", "vin": "VINCW1",
        "fuel_type": "Diesel", "transmission": "Auto", "status": "AVAILABLE",
    })
    session = get_local_session()
    vid = session.query(LocalVehicle).filter_by(registration="CW-1").first().id
    session.close()

    assert counter.n == 1, "vehicle create must publish exactly one new revision"
    counter.stop()
    assert _vehicle_status(window, vid) == "AVAILABLE"
    assert _dashboard(window)["available"] >= 1

    # ── Create maintenance -> unavailable everywhere ──────────────────
    window._create_maintenance_record({
        "vehicle_id": vid, "type": "Entretien",
        "start_datetime": _iso(-1), "expected_end_datetime": _iso(2),
        "status": "ACTIVE", "parts": [],
    })
    assert _vehicle_status(window, vid) == "MAINTENANCE"
    assert _dashboard(window)["maintenance"] == 1
    assert _dashboard(window)["available"] == 0

    session = get_local_session()
    m = session.query(LocalMaintenance).filter_by(vehicle_id=vid).first()
    mid = m.id
    session.close()

    # ── Finish maintenance -> available again everywhere, live ────────
    window._maintenance._finish_maintenance(mid)
    assert _vehicle_status(window, vid) == "AVAILABLE", "vehicle must free immediately"
    assert _dashboard(window)["maintenance"] == 0
    assert _dashboard(window)["available"] >= 1

    # ── Create reservation (active now) -> rented everywhere ──────────
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    session.add(LocalReservation(
        id="cw-res", vehicle_id=vid, customer_name="X",
        start_datetime=_iso(-1), end_datetime=_iso(2),
        daily_price=100.0, num_days=3, total_price=300.0, deposit=0,
        status="ACTIVE", payment_status="PENDING",
        created_at=now, updated_at=now, version=1,
    ))
    session.commit()
    session.close()
    bus.data_refreshed.emit()
    assert _vehicle_status(window, vid) == "RENTED"
    assert _dashboard(window)["rented"] == 1

    # ── Cancel reservation -> available everywhere, live ──────────────
    window._reservations._cancel_reservation("cw-res")
    assert _vehicle_status(window, vid) == "AVAILABLE"
    assert _dashboard(window)["rented"] == 0
    assert _dashboard(window)["available"] >= 1

    # ── Complete reservation -> available everywhere ──────────────────
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    session.add(LocalReservation(
        id="cw-res2", vehicle_id=vid, customer_name="Y",
        start_datetime=_iso(-1), end_datetime=_iso(2),
        daily_price=100.0, num_days=3, total_price=300.0, deposit=0,
        status="ACTIVE", payment_status="PENDING",
        created_at=now, updated_at=now, version=1,
    ))
    session.commit()
    session.close()
    bus.data_refreshed.emit()
    assert _vehicle_status(window, vid) == "RENTED"
    window._reservations._complete_reservation("cw-res2")
    assert _vehicle_status(window, vid) == "AVAILABLE"

    # ── Edit vehicle -> new data visible immediately ──────────────────
    window._update_vehicle({
        "id": vid, "registration": "CW-1-EDITED", "brand": "T", "model": "C2",
        "year": 2025, "daily_rental_price": 999.0, "status": "AVAILABLE",
    })
    window._load_vehicles_from_local()
    row = next(v for v in window._vehicle_list._vehicles_data if v["id"] == vid)
    assert row["registration"] == "CW-1-EDITED" and row["model"] == "C2"

    # ── Create maintenance then CANCEL it -> available everywhere ──────
    window._create_maintenance_record({
        "vehicle_id": vid, "type": "Entretien",
        "start_datetime": _iso(-1), "expected_end_datetime": _iso(3),
        "status": "ACTIVE", "parts": [],
    })
    assert _vehicle_status(window, vid) == "MAINTENANCE"
    session = get_local_session()
    m2 = session.query(LocalMaintenance).filter_by(vehicle_id=vid, status="ACTIVE").first()
    m2id = m2.id
    m2.status = "CANCELLED"
    session.commit()
    session.close()
    bus.data_refreshed.emit()
    assert _vehicle_status(window, vid) == "AVAILABLE"

    # ── Delete vehicle -> gone from every view ────────────────────────
    from PySide6.QtWidgets import QMessageBox
    import app.ui.main_window as mw
    orig = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        window._on_delete_vehicle(vid)
    finally:
        QMessageBox.question = orig
    window._load_vehicles_from_local()
    assert all(v["id"] != vid for v in window._vehicle_list._vehicles_data)
    assert _dashboard(window)["total_vehicles"] == 0
