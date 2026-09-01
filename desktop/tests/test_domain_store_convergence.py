"""Increment 2 — whole-window convergence through the DomainStore.

One committed mutation → the store publishes ONE new revision → every main
view (Dashboard, Vehicles, Reservations, Maintenance) reflects the same truth,
with NO tab switch, NO refresh-button click, NO sync round-trip, and NO
competing per-view state derivation surviving.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from PySide6.QtWidgets import QApplication, QMessageBox

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.state.domain_store import get_domain_store
from app.sync.dashboard_cache import compute_local_overview

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def window(qapp, request):
    from app.ui.main_window import MainWindow
    w = MainWindow(user_data={"user_id": "u1", "role": "ADMIN", "full_name": "A",
                              "access_token": "", "refresh_token": "", "offline": True})
    w._run_sync = lambda *a, **k: None
    w._clients_page.refresh_data = lambda *a, **k: None
    if hasattr(w, "_sync_timer"):
        w._sync_timer.stop()
    if hasattr(w, "_realtime_client"):
        try:
            w._realtime_client.stop()
        except Exception:
            pass
    request.addfinalizer(lambda: (w.close(), w.deleteLater(), qapp.processEvents()))
    return w


def _iso(days, hour=9):
    return (NOW + timedelta(days=days)).replace(hour=hour, minute=0, second=0,
                                                microsecond=0).isoformat()


# ── view-state readers (what the widgets actually hold) ──────────────────
def _vehicles_view(window):
    return {v["id"]: v["status"] for v in window._vehicle_list._vehicles_data}


def _dashboard_view(window):
    return dict(window._dashboard._overview_data)


def _reservation_rows_seen(window, monkeypatch):
    seen = {}
    real = window._reservations.refresh_data

    def spy():
        real()
    # the reservation widget renders from a fresh DB read; assert on the DB
    s = get_local_session()
    try:
        return {r.id: r.status for r in s.query(LocalReservation).all()}
    finally:
        s.close()


def _maintenance_rows(window):
    s = get_local_session()
    try:
        return {m.id: m.status for m in s.query(LocalMaintenance).all()}
    finally:
        s.close()


def test_vehicle_create_converges_across_all_views_without_tab_switch(window):
    store = get_domain_store()
    rev0 = store.revision

    window._create_vehicle({
        "registration": "CV-1", "brand": "T", "model": "C", "vin": "VINCV1",
        "fuel_type": "Diesel", "transmission": "Auto", "status": "AVAILABLE",
    })

    # exactly one new revision for one mutation
    assert store.revision == rev0 + 1

    s = get_local_session()
    vid = s.query(LocalVehicle).filter_by(registration="CV-1").first().id
    s.close()

    # Vehicles view + Dashboard view both updated, no tab switch / refresh click
    assert _vehicles_view(window).get(vid) == "AVAILABLE"
    dv = _dashboard_view(window)
    assert dv["available"] >= 1
    # NO competing state: dashboard view == store snapshot == standalone canonical
    assert dv["available"] == store.snapshot.fleet_counts["available"] == compute_local_overview()["available"]
    assert dv["total_vehicles"] == store.snapshot.fleet_counts["total_vehicles"]


def test_maintenance_creation_cancels_reservation_and_propagates_everywhere(window):
    s = get_local_session()
    s.add(LocalVehicle(id="veh-mw", registration="MW-1", vin="MW1xxxxxxxxxxxxxx",
                       brand="P", model="208", year=2024, color="N", fuel_type="D",
                       transmission="M", status="AVAILABLE", daily_rental_price=250,
                       created_at=NOW.isoformat(), updated_at=NOW.isoformat(), version=1))
    s.add(LocalReservation(id="res-mw", vehicle_id="veh-mw", customer_name="C",
                           start_datetime=_iso(-1), end_datetime=_iso(5),
                           daily_price=250, num_days=6, total_price=1500, deposit=0,
                           status="ACTIVE", created_at=NOW.isoformat(),
                           updated_at=NOW.isoformat(), version=1))
    s.commit(); s.close()

    store = get_domain_store()
    store.reload()
    assert store.snapshot.effective_status("veh-mw") == "RENTED"

    window._create_maintenance_record({
        "vehicle_id": "veh-mw", "type": "Panne",
        "start_datetime": _iso(-1, 8), "expected_end_datetime": _iso(3),
        "status": "ACTIVE", "parts": [],
    })

    # reservation cancelled (maintenance wins), vehicle now MAINTENANCE everywhere
    assert _maintenance_rows(window)  # a maintenance row exists
    s = get_local_session()
    r = s.query(LocalReservation).filter_by(id="res-mw").first()
    assert r.status == "CANCELLED" and r.cancellation_reason == "MAINTENANCE"
    s.close()

    assert _vehicles_view(window)["veh-mw"] == "MAINTENANCE"
    dv = _dashboard_view(window)
    assert dv["maintenance"] == 1 and dv["rented"] == 0
    assert dv["maintenance"] == store.snapshot.fleet_counts["maintenance"]


def test_maintenance_completion_frees_vehicle_everywhere(window):
    s = get_local_session()
    s.add(LocalVehicle(id="veh-fin", registration="F-1", vin="F1xxxxxxxxxxxxxxx",
                       brand="P", model="Clio", year=2024, color="N", fuel_type="D",
                       transmission="M", status="AVAILABLE", daily_rental_price=200,
                       created_at=NOW.isoformat(), updated_at=NOW.isoformat(), version=1))
    s.commit(); s.close()

    window._create_maintenance_record({
        "vehicle_id": "veh-fin", "type": "Entretien",
        "start_datetime": _iso(-1), "expected_end_datetime": _iso(3),
        "status": "ACTIVE", "parts": [],
    })
    assert _vehicles_view(window)["veh-fin"] == "MAINTENANCE"

    s = get_local_session()
    mid = s.query(LocalMaintenance).filter_by(vehicle_id="veh-fin").first().id
    s.close()

    store = get_domain_store()
    rev = store.revision
    window._maintenance._finish_maintenance(mid)  # real UI path -> maintenance_updated signal

    assert store.revision > rev
    assert _vehicles_view(window)["veh-fin"] == "AVAILABLE"
    assert _dashboard_view(window)["maintenance"] == 0
    assert _dashboard_view(window)["available"] >= 1


def test_sync_applied_change_propagates_through_the_same_path(window):
    """A pull that mutates SQLite off-thread converges once _on_sync_finished
    triggers the store (simulated here by apply_pulled_items + the pulse)."""
    from app.services.event_bus import get_event_bus
    from app.sync.engine import SyncEngine

    s = get_local_session()
    s.add(LocalVehicle(id="veh-sync", registration="S-1", vin="S1xxxxxxxxxxxxxxx",
                       brand="P", model="Megane", year=2024, color="N", fuel_type="D",
                       transmission="M", status="AVAILABLE", daily_rental_price=200,
                       created_at=NOW.isoformat(), updated_at=NOW.isoformat(), version=1))
    s.commit(); s.close()
    get_event_bus().data_refreshed.emit()
    assert _vehicles_view(window)["veh-sync"] == "AVAILABLE"

    # server pushes a maintenance for that vehicle
    eng = SyncEngine("dev-test", "tok")
    eng.apply_pulled_items([{
        "entity_type": "maintenance", "entity_id": "m-sync", "operation": "CREATE",
        "version": 1,
        "payload": {
            "id": "m-sync", "vehicle_id": "veh-sync", "type": "Panne",
            "status": "ACTIVE", "step": "DIAGNOSTIC",
            "start_datetime": _iso(-1), "expected_end_datetime": _iso(4),
        },
    }])
    # _on_sync_finished would fire data_refreshed after a real pull:
    get_event_bus().data_refreshed.emit()

    store = get_domain_store()
    assert _vehicles_view(window)["veh-sync"] == "MAINTENANCE"
    assert _dashboard_view(window)["maintenance"] == store.snapshot.fleet_counts["maintenance"] == 1


def test_no_refresh_button_and_no_tab_switch_needed(window, monkeypatch):
    # forbid the manual escape hatches for the duration of the test
    monkeypatch.setattr(window, "_on_refresh_clicked",
                        lambda *a, **k: pytest.fail("refresh button must not be needed"))
    monkeypatch.setattr(window, "_switch_page",
                        lambda *a, **k: pytest.fail("tab switch must not be needed"))

    window._create_vehicle({
        "registration": "NR-1", "brand": "T", "model": "X", "vin": "VINNR1",
        "fuel_type": "Diesel", "transmission": "Auto", "status": "AVAILABLE",
    })
    s = get_local_session()
    vid = s.query(LocalVehicle).filter_by(registration="NR-1").first().id
    s.close()
    assert _vehicles_view(window)[vid] == "AVAILABLE"
    assert _dashboard_view(window)["total_vehicles"] == 1


def test_one_broken_view_does_not_freeze_the_rest_and_self_heals(window, monkeypatch):
    store = get_domain_store()

    # reservations view is broken for the first publish
    broken = {"n": 0}
    real_refresh = window._reservations.refresh_data

    def flaky():
        broken["n"] += 1
        if broken["n"] == 1:
            raise RuntimeError("bad row")
        return real_refresh()

    monkeypatch.setattr(window._reservations, "refresh_data", flaky)

    window._create_vehicle({
        "registration": "BK-1", "brand": "T", "model": "Y", "vin": "VINBK1",
        "fuel_type": "Diesel", "transmission": "Auto", "status": "AVAILABLE",
    })
    s = get_local_session()
    vid = s.query(LocalVehicle).filter_by(registration="BK-1").first().id
    s.close()

    # other views still converged despite the reservations view raising
    assert _vehicles_view(window)[vid] == "AVAILABLE"
    assert _dashboard_view(window)["total_vehicles"] == 1
    assert broken["n"] == 1

    # self-heal: next revision (any further mutation) retries the broken view
    window._update_vehicle({"id": vid, "registration": "BK-1B", "brand": "T",
                            "model": "Y", "year": 2024, "daily_rental_price": 1.0,
                            "status": "AVAILABLE"})
    assert broken["n"] == 2  # retried, no longer raising


def test_dashboard_and_vehicles_never_disagree_after_any_mutation(window):
    store = get_domain_store()
    ops = []

    def check():
        dv = _dashboard_view(window)
        vv = _vehicles_view(window)
        tally = {"AVAILABLE": 0, "RESERVED": 0, "RENTED": 0, "MAINTENANCE": 0}
        for st in vv.values():
            if st in tally:
                tally[st] += 1
        assert dv["available"] == tally["AVAILABLE"] == store.snapshot.fleet_counts["available"]
        assert dv["rented"] == tally["RENTED"] == store.snapshot.fleet_counts["rented"]
        assert dv["maintenance"] == tally["MAINTENANCE"] == store.snapshot.fleet_counts["maintenance"]
        assert dv["reserved"] == tally["RESERVED"] == store.snapshot.fleet_counts["reserved"]

    window._create_vehicle({"registration": "D-1", "brand": "T", "model": "A",
                            "vin": "VD1", "fuel_type": "D", "transmission": "A",
                            "status": "AVAILABLE"})
    check()
    s = get_local_session()
    vid = s.query(LocalVehicle).filter_by(registration="D-1").first().id
    s.close()

    window._create_maintenance_record({
        "vehicle_id": vid, "type": "X", "start_datetime": _iso(-1),
        "expected_end_datetime": _iso(2), "status": "ACTIVE", "parts": [],
    })
    check()
