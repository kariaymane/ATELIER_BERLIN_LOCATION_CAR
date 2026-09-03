"""Regression test for P1-1: Dashboard Time-Liveness under Online Server Authority.

Proves:
1. When online and holding authoritative server dashboard metrics:
   - Advancing the clock past a reservation boundary updates both the Vehicles list
     AND the Dashboard fleet cards (rented -> 0, available -> 1) without user action.
   - Vehicles and Dashboard strictly agree at all times.
2. Crossing local midnight rolls the period revenue / counters deterministically.
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
from app.models.reservation import LocalReservation
from app.state.domain_store import reset_domain_store
from app.state.boundary_clock import BoundaryClock

_T0 = datetime(2026, 8, 30, 23, 50, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _seed_vehicle(s, vid):
    s.add(LocalVehicle(
        id=vid, registration=f"R-{vid}", vin=f"{vid}1234567890123"[:17],
        brand="Brand", model="Model", year=2024, color="Noir", fuel_type="DIESEL",
        transmission="MANUAL", status="AVAILABLE", daily_rental_price=200,
        created_at=_T0.isoformat(), updated_at=_T0.isoformat(), version=1,
    ))


def _seed_reservation(s, rid, vid, start, end):
    days = max(1, (end.date() - start.date()).days)
    s.add(LocalReservation(
        id=rid, vehicle_id=vid, customer_name="Live Customer",
        start_datetime=start.isoformat(), end_datetime=end.isoformat(),
        daily_price=200, num_days=days, total_price=days * 200, deposit=0,
        status="ACTIVE", created_at=_T0.isoformat(), updated_at=_T0.isoformat(), version=1,
    ))


def test_online_server_dashboard_evolves_at_temporal_boundary(qapp, request):
    """P1-1 Regression: An online app holding live server dashboard metrics MUST
    still evolve its dashboard fleet counts when time passes a reservation boundary."""
    clock = {"now": _T0}
    now_fn = lambda: clock["now"]

    pending = []

    def fake_schedule(delay, cb):
        class _Handle:
            def cancel(self):
                if (delay, cb) in pending:
                    pending.remove((delay, cb))
        pending.append((delay, cb))
        return _Handle()

    end = _T0 + timedelta(minutes=5)  # reservation ends at 23:55:00

    s = get_local_session()
    _seed_vehicle(s, "v-live-01")
    _seed_reservation(s, "r-live-01", "v-live-01", _T0 - timedelta(hours=2), end)
    s.commit()
    s.close()

    reset_domain_store(now_fn=now_fn)

    from app.ui.main_window import MainWindow
    w = MainWindow(user_data={
        "user_id": "u1", "role": "ADMIN", "full_name": "Admin",
        "access_token": "dummy_token", "refresh_token": "dummy_refresh", "offline": False,
    })
    w._run_sync = lambda *a, **k: None
    w._clients_page.refresh_data = lambda *a, **k: None
    if hasattr(w, "_sync_timer"):
        w._sync_timer.stop()
    if hasattr(w, "_realtime_client"):
        try:
            w._realtime_client.stop()
        except Exception:
            pass

    w._boundary_clock.stop()
    w._boundary_clock = BoundaryClock(w._store, now_fn=now_fn, schedule_fn=fake_schedule)
    w._boundary_clock.start()

    request.addfinalizer(lambda: (w.close(), w.deleteLater(), qapp.processEvents()))

    w._initial_load()
    w._initial_load = lambda *a, **k: None
    qapp.processEvents()

    # 1. Simulate server delivering authoritative live stats
    w._on_dashboard_stats(
        overview={
            "total_vehicles": 1,
            "available": 0,
            "rented": 1,
            "reserved": 0,
            "maintenance": 0,
            "today_revenue": 200.0,
            "today_rentals": 1,
            "today_returns": 1,
        },
        top_vehicles=[],
        generation=1,
    )
    qapp.processEvents()

    # Pre-condition: online server stats active, vehicle is RENTED
    assert w._dashboard._overview_data["rented"] == 1
    assert w._dashboard._overview_data["available"] == 0
    assert {v["id"]: v["status"] for v in w._vehicle_list._vehicles_data}["v-live-01"] == "RENTED"
    assert w._store.snapshot.is_live is True

    # 2. Advance clock past the reservation end boundary (23:55:01)
    clock["now"] = end + timedelta(seconds=1)
    assert pending, "BoundaryClock must have armed a timer for reservation end"
    _delay, cb = pending.pop()
    cb()  # BoundaryClock._fire -> recompute_effective
    qapp.processEvents()

    # Post-condition 1: Both screens MUST update and agree!
    assert {v["id"]: v["status"] for v in w._vehicle_list._vehicles_data}["v-live-01"] == "AVAILABLE"
    assert w._dashboard._overview_data["rented"] == 0, "Dashboard rented count must evolve at boundary!"
    assert w._dashboard._overview_data["available"] == 1, "Dashboard available count must evolve at boundary!"
    assert w._store.snapshot.overview["rented"] == 0
    assert w._store.snapshot.overview["available"] == 1


def test_online_server_dashboard_rolls_at_midnight(qapp, request):
    """P1-1 Regression: When the clock crosses local midnight while online,
    today_revenue rolls over according to the canonical specification."""
    clock = {"now": _T0}  # 23:50:00 UTC
    now_fn = lambda: clock["now"]

    pending = []

    def fake_schedule(delay, cb):
        class _Handle:
            def cancel(self):
                if (delay, cb) in pending:
                    pending.remove((delay, cb))
        pending.append((delay, cb))
        return _Handle()

    s = get_local_session()
    _seed_vehicle(s, "v-mid-01")
    s.commit()
    s.close()

    reset_domain_store(now_fn=now_fn)

    from app.ui.main_window import MainWindow
    w = MainWindow(user_data={
        "user_id": "u1", "role": "ADMIN", "full_name": "Admin",
        "access_token": "dummy_token", "refresh_token": "dummy_refresh", "offline": False,
    })
    w._run_sync = lambda *a, **k: None
    w._clients_page.refresh_data = lambda *a, **k: None
    if hasattr(w, "_sync_timer"):
        w._sync_timer.stop()
    if hasattr(w, "_realtime_client"):
        try:
            w._realtime_client.stop()
        except Exception:
            pass

    w._boundary_clock.stop()
    w._boundary_clock = BoundaryClock(w._store, now_fn=now_fn, schedule_fn=fake_schedule)
    w._boundary_clock.start()

    request.addfinalizer(lambda: (w.close(), w.deleteLater(), qapp.processEvents()))

    w._initial_load()
    w._initial_load = lambda *a, **k: None
    qapp.processEvents()

    # Deliver server dashboard with today's revenue = 1500.0
    w._on_dashboard_stats(
        overview={
            "total_vehicles": 1,
            "available": 1,
            "rented": 0,
            "reserved": 0,
            "maintenance": 0,
            "today_revenue": 1500.0,
            "today_rentals": 3,
        },
        top_vehicles=[],
        generation=1,
    )
    qapp.processEvents()
    assert w._dashboard._overview_data["today_revenue"] == 1500.0

    # Advance clock past midnight (2026-08-31 00:00:05 UTC)
    midnight = datetime(2026, 8, 31, 0, 0, 5, tzinfo=timezone.utc)
    clock["now"] = midnight
    # Trigger boundary recompute
    w._store.recompute_effective(now=midnight)
    qapp.processEvents()

    # Post-condition: today_revenue rolled for the new calendar day
    assert w._dashboard._overview_data["today_revenue"] == 0.0, "Today's revenue must roll at midnight!"
    assert w._dashboard._overview_data["today_rentals"] == 0, "Today's rentals count must roll at midnight!"
