"""Increment 2 — DomainStore unit contract.

Proves: initial state, subscription, monotonic revision, multi-subscriber
convergence, exception isolation, the mutate() transaction path (commit ->
reload; failure -> rollback, no reload, no revision bump), and that the
snapshot's effective status matches the Increment-1 normative spec.
"""
import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CAR_RENTAL_DB_RESET", "1")

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.state.domain_store import DomainStore, get_domain_store, reset_domain_store

_SHARED = pathlib.Path(__file__).resolve().parents[2] / "shared"
sys.path.insert(0, str(_SHARED))
from fleet_status_reference import effective_statuses as ref_effective  # noqa: E402

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _db():
    init_local_db()


@pytest.fixture
def store():
    return reset_domain_store()


def _v(session, vid, status="AVAILABLE"):
    session.add(LocalVehicle(
        id=vid, registration=f"R-{vid}", vin=f"{vid}vvvvvvvvvvvvvvvv"[:17],
        brand="B", model="M", year=2024, color="N", fuel_type="D",
        transmission="M", status=status, daily_rental_price=1,
        created_at=NOW.isoformat(), updated_at=NOW.isoformat(), version=1))


def _r(session, rid, vid, status, start, end):
    session.add(LocalReservation(
        id=rid, vehicle_id=vid, customer_name="X",
        start_datetime=start.isoformat(), end_datetime=end.isoformat(),
        daily_price=1, num_days=1, total_price=1, deposit=0, status=status,
        created_at=NOW.isoformat(), updated_at=NOW.isoformat(), version=1))


def _m(session, mid, vid, status, start, end):
    session.add(LocalMaintenance(
        id=mid, vehicle_id=vid, type="X", status=status,
        start_datetime=start.isoformat(),
        expected_end_datetime=end.isoformat() if end else None,
        created_at=NOW.isoformat(), updated_at=NOW.isoformat(), version=1))


def test_initial_state(store):
    assert store.revision == 0
    assert store.snapshot.vehicles == ()
    assert store.snapshot.reservations == ()
    assert store.snapshot.maintenances == ()
    assert store.snapshot.fleet_counts == {}


def test_reload_builds_snapshot_and_bumps_revision(store):
    s = get_local_session()
    _v(s, "v1"); _r(s, "r1", "v1", "ACTIVE", NOW - timedelta(hours=1), NOW + timedelta(days=1))
    s.commit(); s.close()

    store.reload()
    assert store.revision == 1
    assert len(store.snapshot.vehicles) == 1
    assert store.snapshot.effective_status("v1") == "RENTED"
    assert store.snapshot.fleet_counts["rented"] == 1

    store.reload()
    assert store.revision == 2  # monotonic even with identical data


def test_subscription_receives_snapshot_and_revision(store):
    seen = []
    unsub = store.subscribe(lambda snap, rev: seen.append((rev, len(snap.vehicles))))
    s = get_local_session(); _v(s, "v1"); s.commit(); s.close()
    store.reload()
    assert seen == [(1, 1)]
    unsub()
    store.reload()
    assert seen == [(1, 1)], "unsubscribed callback must not be called again"


def test_multiple_subscribers_all_converge_on_same_revision(store):
    a, b, c = [], [], []
    store.subscribe(lambda snap, rev: a.append(rev))
    store.subscribe(lambda snap, rev: b.append(rev))
    store.subscribe(lambda snap, rev: c.append((rev, dict(snap.fleet_counts))))
    store.reload()
    store.reload()
    assert a == b == [1, 2]
    assert [r for r, _ in c] == [1, 2]


def test_one_failing_subscriber_does_not_block_the_others(store):
    order = []

    def boom(snap, rev):
        order.append("boom")
        raise RuntimeError("bad subscriber")

    store.subscribe(lambda snap, rev: order.append("a"))
    store.subscribe(boom)
    store.subscribe(lambda snap, rev: order.append("b"))

    store.reload()  # must NOT raise
    assert order == ["a", "boom", "b"]

    store.reload()  # still fully functional afterwards
    assert order == ["a", "boom", "b", "a", "boom", "b"]
    assert store.revision == 2


def test_mutate_commits_then_reloads(store):
    seen = []
    store.subscribe(lambda snap, rev: seen.append(rev))

    def _work(session):
        _v(session, "v1")
        _m(session, "m1", "v1", "ACTIVE", NOW - timedelta(hours=1), NOW + timedelta(days=2))

    store.mutate(_work)
    assert store.revision == 1
    assert seen == [1]
    assert store.snapshot.effective_status("v1") == "MAINTENANCE"

    s = get_local_session()
    assert s.query(LocalMaintenance).count() == 1
    s.close()


def test_mutate_failure_rolls_back_and_does_not_publish(store):
    s = get_local_session(); _v(s, "v1"); s.commit(); s.close()
    store.reload()
    rev = store.revision
    seen = []
    store.subscribe(lambda snap, r: seen.append(r))

    def _bad(session):
        _v(session, "v2")               # staged...
        raise ValueError("boom mid-mutation")

    with pytest.raises(ValueError):
        store.mutate(_bad)

    assert store.revision == rev, "failed mutation must not bump revision"
    assert seen == [], "failed mutation must not notify subscribers"
    s = get_local_session()
    assert s.query(LocalVehicle).filter_by(id="v2").first() is None, "must roll back"
    s.close()


def test_snapshot_effective_status_matches_normative_spec(store):
    s = get_local_session()
    _v(s, "av")
    _v(s, "rs"); _r(s, "r-rs", "rs", "RESERVED", NOW - timedelta(hours=1), NOW + timedelta(days=2))
    _v(s, "rt"); _r(s, "r-rt", "rt", "ACTIVE", NOW - timedelta(hours=1), NOW + timedelta(days=2))
    _v(s, "mt"); _m(s, "m-mt", "mt", "ACTIVE", NOW - timedelta(hours=1), NOW + timedelta(days=2))
    _v(s, "both")
    _r(s, "r-both", "both", "ACTIVE", NOW - timedelta(hours=1), NOW + timedelta(days=2))
    _m(s, "m-both", "both", "ACTIVE", NOW - timedelta(hours=1), NOW + timedelta(days=2))
    _v(s, "sold", status="SOLD")
    s.commit(); s.close()

    store.reload()

    vehicles = [{"id": vid, "status": ("SOLD" if vid == "sold" else "AVAILABLE")}
                for vid in ("av", "rs", "rt", "mt", "both", "sold")]
    reservations = [
        {"vehicle_id": "rs", "status": "RESERVED",
         "start": (NOW - timedelta(hours=1)).isoformat(), "end": (NOW + timedelta(days=2)).isoformat()},
        {"vehicle_id": "rt", "status": "ACTIVE",
         "start": (NOW - timedelta(hours=1)).isoformat(), "end": (NOW + timedelta(days=2)).isoformat()},
        {"vehicle_id": "both", "status": "ACTIVE",
         "start": (NOW - timedelta(hours=1)).isoformat(), "end": (NOW + timedelta(days=2)).isoformat()},
    ]
    maintenances = [
        {"vehicle_id": "mt", "status": "ACTIVE",
         "start": (NOW - timedelta(hours=1)).isoformat(), "expected_end": (NOW + timedelta(days=2)).isoformat()},
        {"vehicle_id": "both", "status": "ACTIVE",
         "start": (NOW - timedelta(hours=1)).isoformat(), "expected_end": (NOW + timedelta(days=2)).isoformat()},
    ]
    want = ref_effective(vehicles, reservations, maintenances, NOW)
    got = {vid: store.snapshot.effective_status(vid) for vid in want}
    assert got == want


def test_singleton_and_reset(store):
    assert get_domain_store() is store
    fresh = reset_domain_store()
    assert fresh is not store
    assert get_domain_store() is fresh
