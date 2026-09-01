"""Increment 3 — temporal DomainStore + the forensic proof.

The decisive proof: THE STATE CHANGES BECAUSE TIME PASSED, with no user action,
no refresh, no tab switch, no sync, and no database mutation.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.state.domain_store import DomainStore, reset_domain_store
from app.state.boundary_clock import BoundaryClock

_SHARED_T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _v(s, vid, status="AVAILABLE"):
    s.add(LocalVehicle(id=vid, registration=f"R-{vid}", vin=f"{vid}xxxxxxxxxxxxxxxx"[:17],
                       brand="B", model="M", year=2024, color="N", fuel_type="D",
                       transmission="M", status=status, daily_rental_price=100,
                       created_at=_SHARED_T0.isoformat(), updated_at=_SHARED_T0.isoformat(),
                       version=1))


def _r(s, rid, vid, start, end, status="ACTIVE"):
    s.add(LocalReservation(id=rid, vehicle_id=vid, customer_name="X",
                           start_datetime=start.isoformat(), end_datetime=end.isoformat(),
                           daily_price=100, num_days=1, total_price=100, deposit=0, status=status,
                           created_at=_SHARED_T0.isoformat(), updated_at=_SHARED_T0.isoformat(),
                           version=1))


def _m(s, mid, vid, start, end):
    s.add(LocalMaintenance(id=mid, vehicle_id=vid, type="X", status="ACTIVE",
                           start_datetime=start.isoformat(),
                           expected_end_datetime=end.isoformat() if end else None,
                           created_at=_SHARED_T0.isoformat(), updated_at=_SHARED_T0.isoformat(),
                           version=1))


# ── pure temporal-recompute tests (no waiting) ─────────────────────────
def test_recompute_at_snapshot_time_is_a_noop():
    """Parity guard: the SQL snapshot build and the in-memory recompute at the
    SAME instant must agree, so a recompute at t == generated_at changes
    nothing (and never bumps the revision)."""
    T0 = _SHARED_T0
    s = get_local_session()
    _v(s, "v1"); _r(s, "r1", "v1", T0 - timedelta(hours=1), T0 + timedelta(hours=2))
    _v(s, "v2"); _m(s, "m2", "v2", T0 - timedelta(hours=1), T0 + timedelta(hours=1))
    _v(s, "v3")
    s.commit(); s.close()

    store = DomainStore(now_fn=lambda: T0)
    store.reload()
    rev = store.revision
    assert store.recompute_effective(now=T0) is False
    assert store.revision == rev


def test_reservation_end_frees_vehicle_via_recompute():
    T0 = _SHARED_T0
    end = T0 + timedelta(minutes=30)
    s = get_local_session()
    _v(s, "v1"); _r(s, "r1", "v1", T0 - timedelta(hours=1), end)
    s.commit(); s.close()

    store = DomainStore(now_fn=lambda: T0)
    store.reload()
    assert store.snapshot.effective_status("v1") == "RENTED"
    rev = store.revision

    assert store.recompute_effective(now=end - timedelta(seconds=1)) is False
    assert store.snapshot.effective_status("v1") == "RENTED"

    assert store.recompute_effective(now=end) is True          # half-open: free AT end
    assert store.snapshot.effective_status("v1") == "AVAILABLE"
    assert store.revision == rev + 1
    assert store.snapshot.fleet_counts["rented"] == 0
    assert store.snapshot.fleet_counts["available"] == 1
    assert store.snapshot.overview["rented"] == 0
    assert store.snapshot.overview["available"] == 1


def test_maintenance_end_frees_vehicle_via_recompute():
    T0 = _SHARED_T0
    m_end = T0 + timedelta(minutes=20)
    s = get_local_session()
    _v(s, "v1"); _m(s, "m1", "v1", T0 - timedelta(hours=1), m_end)
    s.commit(); s.close()

    store = DomainStore(now_fn=lambda: T0)
    store.reload()
    assert store.snapshot.effective_status("v1") == "MAINTENANCE"

    assert store.recompute_effective(now=m_end) is True
    assert store.snapshot.effective_status("v1") == "AVAILABLE"
    assert store.snapshot.overview["maintenance"] == 0
    assert store.snapshot.overview["active_maintenances"] == 0


def test_recompute_notifies_subscribers_once_and_isolates_failures():
    T0 = _SHARED_T0
    end = T0 + timedelta(minutes=10)
    s = get_local_session()
    _v(s, "v1"); _r(s, "r1", "v1", T0 - timedelta(hours=1), end)
    s.commit(); s.close()

    store = DomainStore(now_fn=lambda: T0)
    store.reload()

    hits = []
    store.subscribe(lambda snap, rev: hits.append(("a", rev, snap.effective_status("v1"))))
    store.subscribe(lambda snap, rev: (_ for _ in ()).throw(RuntimeError("bad view")))
    store.subscribe(lambda snap, rev: hits.append(("b", rev, snap.effective_status("v1"))))

    store.recompute_effective(now=end)  # must not raise

    assert [h[0] for h in hits] == ["a", "b"]
    assert {h[2] for h in hits} == {"AVAILABLE"}
    assert hits[0][1] == hits[1][1] == store.revision


def test_multi_boundary_only_the_reached_edge_transitions():
    T0 = _SHARED_T0
    ea, eb = T0 + timedelta(minutes=5), T0 + timedelta(minutes=10)
    s = get_local_session()
    _v(s, "a"); _r(s, "ra", "a", T0 - timedelta(hours=1), ea)
    _v(s, "b"); _r(s, "rb", "b", T0 - timedelta(hours=1), eb)
    s.commit(); s.close()

    store = DomainStore(now_fn=lambda: T0)
    store.reload()
    assert store.snapshot.fleet_counts["rented"] == 2

    store.recompute_effective(now=ea)
    assert store.snapshot.effective_status("a") == "AVAILABLE"
    assert store.snapshot.effective_status("b") == "RENTED"      # b's edge not reached
    assert store.snapshot.next_boundary == eb

    store.recompute_effective(now=eb)
    assert store.snapshot.effective_status("b") == "AVAILABLE"
    # both interval edges serviced — the remaining boundary is the daily
    # midnight period rollover.
    from app.utils.fleet_status import next_local_midnight
    assert store.snapshot.next_boundary == next_local_midnight(eb)


# ── MIDNIGHT — dashboard period rollover as a temporal boundary ────────
def test_local_midnight_rolls_the_dashboard_period_cards():
    from zoneinfo import ZoneInfo
    from app.utils.fleet_status import next_local_midnight
    TZ = ZoneInfo("Africa/Casablanca")

    # Wed 26 Aug -> Thu 27 Aug: only the *day* rolls (same week, same month).
    before_midnight = datetime(2026, 8, 26, 23, 59, 59, tzinfo=TZ)
    after_midnight = datetime(2026, 8, 27, 0, 0, 1, tzinfo=TZ)
    res_start = datetime(2026, 8, 26, 12, 0, 0, tzinfo=TZ)  # "today" on Aug 26

    s = get_local_session()
    _v(s, "v1")
    s.add(LocalReservation(
        id="r1", vehicle_id="v1", customer_name="X",
        start_datetime=res_start.astimezone(timezone.utc).isoformat(),
        end_datetime=(res_start + timedelta(days=5)).astimezone(timezone.utc).isoformat(),
        daily_price=100, num_days=5, total_price=500, deposit=0, status="ACTIVE",
        created_at=res_start.isoformat(), updated_at=res_start.isoformat(), version=1))
    s.commit(); s.close()

    holder = {"now": before_midnight.astimezone(timezone.utc)}
    store = DomainStore(now_fn=lambda: holder["now"])
    store.reload()

    assert store.snapshot.overview["today_revenue"] == 500.0
    assert store.snapshot.overview["today_rentals"] == 1
    assert store.snapshot.overview["week_revenue"] == 500.0
    # the store armed the next boundary at local midnight
    assert store.snapshot.next_boundary == next_local_midnight(holder["now"])
    rev = store.revision

    # ── advance past local midnight, recompute — NO DB read, NO network ──
    holder["now"] = after_midnight.astimezone(timezone.utc)
    published = store.recompute_effective()
    assert published is True
    assert store.revision == rev + 1

    assert store.snapshot.overview["today_revenue"] == 0.0   # new day, no rentals started today
    assert store.snapshot.overview["today_rentals"] == 0
    assert store.snapshot.overview["week_revenue"] == 500.0  # still the same week
    assert store.snapshot.overview["month_revenue"] == 500.0

    # a second recompute at the same instant changes nothing
    assert store.recompute_effective() is False


def test_midnight_recompute_that_changes_nothing_is_silent():
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Africa/Casablanca")
    s = get_local_session()
    _v(s, "v1")  # no reservations at all
    s.commit(); s.close()

    holder = {"now": datetime(2026, 8, 30, 23, 59, 30, tzinfo=TZ).astimezone(timezone.utc)}
    store = DomainStore(now_fn=lambda: holder["now"])
    store.reload()
    rev = store.revision

    holder["now"] = datetime(2026, 8, 31, 0, 0, 30, tzinfo=TZ).astimezone(timezone.utc)
    assert store.recompute_effective() is False   # no vehicles busy, no revenue → nothing changed
    assert store.revision == rev


# ── THE FORENSIC PROOF — real clock, real QTimer, nothing touched ──────
def test_forensic_state_changes_because_time_passed(qapp, request):
    """Seed a reservation ending in ~4 seconds. Observe RENTED. Do NOTHING —
    no refresh, no tab switch, no sync, no mutation, no UI interaction. Wait.
    Observe AVAILABLE. Exactly one revision, exactly one notification, every
    subscribed view converged."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(seconds=4)

    s = get_local_session()
    _v(s, "veh-forensic")
    _r(s, "res-forensic", "veh-forensic", now - timedelta(hours=1), end)
    s.commit(); s.close()

    reset_domain_store()  # real wall-clock now_fn (default)

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

    store = w._store
    # Let the deferred _initial_load (QTimer.singleShot(100)) fire and settle,
    # so nothing but the BoundaryClock can bump the revision afterwards.
    QTest.qWait(400)

    # ── T-before ──────────────────────────────────────────────────────
    old_revision = store.revision
    assert store.snapshot.effective_status("veh-forensic") == "RENTED"
    assert {v["id"]: v["status"] for v in w._vehicle_list._vehicles_data}["veh-forensic"] == "RENTED"
    assert w._dashboard._overview_data["rented"] == 1
    boundary = store.snapshot.next_boundary
    assert boundary == end
    assert w._boundary_clock.running and w._boundary_clock.next_boundary == end

    notifications = []
    store.subscribe(lambda snap, rev: notifications.append(rev))

    # ── DO NOTHING. Just let the Qt event loop run past the boundary. ──
    import time as _time
    _t0 = _time.monotonic()
    while (_time.monotonic() - _t0 < 10.0
           and store.snapshot.effective_status("veh-forensic") != "AVAILABLE"):
        QTest.qWait(100)
    print(f"waited              : {_time.monotonic() - _t0:.1f}s")

    # ── T-after ───────────────────────────────────────────────────────
    new_revision = store.revision
    new_status = store.snapshot.effective_status("veh-forensic")

    print("\n=== FORENSIC TEMPORAL TRANSITION ===")
    print(f"old revision       : {old_revision}")
    print(f"boundary timestamp : {boundary.isoformat()}")
    print(f"new revision       : {new_revision}")
    print(f"new status         : {new_status}")
    print(f"notification count : {len(notifications)}")
    print(f"clock fire_count   : {w._boundary_clock.fire_count}")
    print(f"clock publish_count: {w._boundary_clock.publish_count}")

    assert new_status == "AVAILABLE", "vehicle must free itself because time passed"
    assert new_revision == old_revision + 1, "exactly one temporal revision"
    assert notifications == [new_revision], "exactly one notification"

    # every subscribed view converged on the SAME truth, with no user action
    assert {v["id"]: v["status"] for v in w._vehicle_list._vehicles_data}["veh-forensic"] == "AVAILABLE"
    assert w._dashboard._overview_data["rented"] == 0
    assert w._dashboard._overview_data["available"] == 1
    assert w._dashboard._overview_data == dict(w._dashboard._overview_data) | {
        k: store.snapshot.fleet_counts[k] for k in ("rented", "available", "maintenance", "reserved")
    }
    # the DB row was never touched
    s = get_local_session()
    try:
        assert s.query(LocalReservation).filter_by(id="res-forensic").one().status == "ACTIVE"
    finally:
        s.close()
