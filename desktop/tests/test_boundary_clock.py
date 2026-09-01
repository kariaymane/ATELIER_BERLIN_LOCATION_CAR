"""Increment 3 — BoundaryClock unit contract (deterministic, no real waiting).

A fake scheduler captures the single pending job; a mutable holder is the
injected clock. Proves: no boundary, one boundary, multiple boundaries in
order, exact-boundary semantics, stop / restart / reschedule, obsolete-
schedule invalidation, subscriber isolation, and shutdown safety.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CAR_RENTAL_DB_RESET", "1")

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.state.domain_store import DomainStore
from app.state.boundary_clock import BoundaryClock

T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _db():
    init_local_db()


class FakeJob:
    def __init__(self, delay, cb):
        self.delay = delay
        self.cb = cb
        self.cancelled = False
        self.fired = False

    def cancel(self):
        self.cancelled = True

    def fire(self):
        assert not self.cancelled, "fired a cancelled (obsolete) job"
        self.fired = True
        self.cb()


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def __call__(self, delay, cb):
        j = FakeJob(delay, cb)
        self.jobs.append(j)
        return j

    @property
    def live(self):
        """Jobs still armed (not cancelled, not yet fired)."""
        return [j for j in self.jobs if not j.cancelled and not j.fired]

    @property
    def pending(self):
        """The single job that would fire next (the clock keeps exactly one)."""
        live = self.live
        assert len(live) <= 1, f"BoundaryClock armed {len(live)} timers at once"
        return live[0] if live else None


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def _v(s, vid, status="AVAILABLE"):
    s.add(LocalVehicle(id=vid, registration=f"R-{vid}", vin=f"{vid}xxxxxxxxxxxxxxxx"[:17],
                       brand="B", model="M", year=2024, color="N", fuel_type="D",
                       transmission="M", status=status, daily_rental_price=1,
                       created_at=T0.isoformat(), updated_at=T0.isoformat(), version=1))


def _r(s, rid, vid, start, end, status="ACTIVE"):
    s.add(LocalReservation(id=rid, vehicle_id=vid, customer_name="X",
                           start_datetime=start.isoformat(), end_datetime=end.isoformat(),
                           daily_price=1, num_days=1, total_price=1, deposit=0, status=status,
                           created_at=T0.isoformat(), updated_at=T0.isoformat(), version=1))


def _m(s, mid, vid, start, end, status="ACTIVE"):
    s.add(LocalMaintenance(id=mid, vehicle_id=vid, type="X", status=status,
                           start_datetime=start.isoformat(),
                           expected_end_datetime=end.isoformat() if end else None,
                           created_at=T0.isoformat(), updated_at=T0.isoformat(), version=1))


def _make(now, seed):
    s = get_local_session()
    seed(s)
    s.commit(); s.close()
    clock = Clock(now)
    store = DomainStore(now_fn=clock)
    store.reload()
    sched = FakeScheduler()
    # deterministic tests drive the fake scheduler directly — no wake-up slack
    bc = BoundaryClock(store, now_fn=clock, schedule_fn=sched, slack_seconds=0.0)
    return store, bc, sched, clock


def test_no_interval_boundary_arms_only_the_daily_midnight_rollover():
    from app.utils.fleet_status import next_local_midnight
    store, bc, sched, clock = _make(T0, lambda s: _v(s, "v1"))
    bc.start()
    assert bc.running is True
    # no reservation/maintenance edge, but the dashboard period cards still
    # roll at local midnight, so exactly ONE timer is armed for that.
    assert bc.next_boundary == next_local_midnight(T0)
    assert len(sched.live) == 1


def test_one_boundary_arms_one_timer_at_exact_delay():
    end = T0 + timedelta(hours=3)
    store, bc, sched, clock = _make(
        T0, lambda s: (_v(s, "v1"), _r(s, "r1", "v1", T0 - timedelta(hours=1), end)))
    assert store.snapshot.effective_status("v1") == "RENTED"
    bc.start()
    assert bc.next_boundary == end
    assert len(sched.live) == 1
    assert sched.pending.delay == 3 * 3600.0


def test_exact_boundary_half_open_semantics():
    end = T0 + timedelta(seconds=10)
    store, bc, sched, clock = _make(
        T0, lambda s: (_v(s, "v1"), _r(s, "r1", "v1", T0 - timedelta(hours=1), end)))
    bc.start()
    assert store.snapshot.effective_status("v1") == "RENTED"  # T0 < end

    clock.now = end - timedelta(seconds=1)      # still inside
    sched.pending.fire()
    assert store.snapshot.effective_status("v1") == "RENTED"

    clock.now = end                              # exactly at end -> free
    # a fresh job was armed by the previous fire's reschedule
    sched.pending.fire()
    assert store.snapshot.effective_status("v1") == "AVAILABLE"


def test_multiple_boundaries_fire_in_order_not_polling():
    e_a = T0 + timedelta(minutes=5)
    e_b = T0 + timedelta(minutes=10)
    e_c = T0 + timedelta(minutes=15)

    def seed(s):
        for vid, e in (("a", e_a), ("b", e_b), ("c", e_c)):
            _v(s, vid)
            _r(s, f"r-{vid}", vid, T0 - timedelta(hours=1), e)

    store, bc, sched, clock = _make(T0, seed)
    bc.start()
    # only ONE timer, for the EARLIEST boundary
    assert bc.next_boundary == e_a and len(sched.live) == 1 and sched.pending.delay == 300.0
    assert store.snapshot.fleet_counts["rented"] == 3

    clock.now = e_a
    sched.pending.fire()
    assert store.snapshot.effective_status("a") == "AVAILABLE"
    assert store.snapshot.fleet_counts["rented"] == 2
    assert bc.next_boundary == e_b and sched.pending.delay == 300.0  # 5 min from e_a

    clock.now = e_b
    sched.pending.fire()
    assert store.snapshot.effective_status("b") == "AVAILABLE"
    assert bc.next_boundary == e_c

    clock.now = e_c
    sched.pending.fire()
    assert store.snapshot.effective_status("c") == "AVAILABLE"
    # all 3 interval edges serviced — the only pending boundary now is the
    # daily midnight rollover.
    from app.utils.fleet_status import next_local_midnight
    assert bc.next_boundary == next_local_midnight(e_c)
    # 3 interval boundaries → exactly 3 fires (NOT one-per-second polling)
    assert bc.fire_count == 3 and bc.publish_count == 3


def test_stop_cancels_pending_timer_and_ignores_late_fire():
    end = T0 + timedelta(hours=1)
    store, bc, sched, clock = _make(
        T0, lambda s: (_v(s, "v1"), _r(s, "r1", "v1", T0 - timedelta(hours=1), end)))
    bc.start()
    job = sched.jobs[-1]
    bc.stop()
    assert bc.running is False and bc.next_boundary is None
    assert job.cancelled is True
    # even if a stale platform timer still fires, it is a no-op
    clock.now = end
    job.cancelled = False          # simulate the platform firing anyway
    job.fire()
    assert bc.fire_count == 0
    assert store.snapshot.effective_status("v1") == "RENTED"  # unchanged


def test_restart_rearms():
    end = T0 + timedelta(hours=1)
    store, bc, sched, clock = _make(
        T0, lambda s: (_v(s, "v1"), _r(s, "r1", "v1", T0 - timedelta(hours=1), end)))
    bc.start(); bc.stop()
    bc.start()
    assert bc.running and bc.next_boundary == end and len(sched.live) == 1


def test_reschedule_on_mutation_invalidates_old_schedule():
    e_late = T0 + timedelta(hours=5)
    store, bc, sched, clock = _make(
        T0, lambda s: (_v(s, "v1"), _r(s, "r1", "v1", T0 - timedelta(hours=1), e_late)))
    bc.start()
    old_job = sched.jobs[-1]
    assert bc.next_boundary == e_late

    # a NEW earlier reservation appears (mutation → store publishes → clock reschedules)
    def _add(session):
        _v(session, "v2")
        _r(session, "r2", "v2", T0 - timedelta(hours=1), T0 + timedelta(minutes=30))
    store.mutate(_add)

    assert old_job.cancelled is True, "obsolete schedule must be cancelled"
    assert bc.next_boundary == T0 + timedelta(minutes=30)
    assert sched.pending.delay == 1800.0

    # firing the OLD job now must do nothing (generation mismatch)
    old_job.cancelled = False
    prev_fire = bc.fire_count
    old_job.cb()
    assert bc.fire_count == prev_fire


def test_boundary_that_changes_nothing_is_a_silent_noop():
    # reservation for a SOLD vehicle: its end is a boundary candidate, but the
    # effective status is structural and never changes.
    end = T0 + timedelta(minutes=10)
    store, bc, sched, clock = _make(
        T0, lambda s: (_v(s, "v1", status="SOLD"),
                       _r(s, "r1", "v1", T0 - timedelta(hours=1), end)))
    bc.start()
    rev = store.revision
    clock.now = end
    sched.pending.fire()
    assert store.revision == rev, "no state change → no revision bump"
    assert bc.fire_count == 1 and bc.publish_count == 0


def test_subscriber_isolation_on_temporal_publish():
    end = T0 + timedelta(minutes=10)
    store, bc, sched, clock = _make(
        T0, lambda s: (_v(s, "v1"), _r(s, "r1", "v1", T0 - timedelta(hours=1), end)))

    order = []
    store.subscribe(lambda snap, rev: order.append("a"))
    store.subscribe(lambda snap, rev: (_ for _ in ()).throw(RuntimeError("bad view")))
    store.subscribe(lambda snap, rev: order.append("b"))

    bc.start()
    clock.now = end
    sched.pending.fire()  # must NOT raise
    assert order == ["a", "b"]
    assert store.snapshot.effective_status("v1") == "AVAILABLE"


def test_shutdown_safety_no_leaked_timer():
    end = T0 + timedelta(hours=1)
    store, bc, sched, clock = _make(
        T0, lambda s: (_v(s, "v1"), _r(s, "r1", "v1", T0 - timedelta(hours=1), end)))
    bc.start()
    bc.stop()
    bc.stop()  # idempotent
    assert all(j.cancelled for j in sched.jobs)
    # store no longer has the clock subscribed
    store.reload()
    assert bc.fire_count == 0


def test_maintenance_boundary():
    m_end = T0 + timedelta(minutes=20)
    store, bc, sched, clock = _make(
        T0, lambda s: (_v(s, "v1"), _m(s, "m1", "v1", T0 - timedelta(hours=1), m_end)))
    assert store.snapshot.effective_status("v1") == "MAINTENANCE"
    bc.start()
    assert bc.next_boundary == m_end

    clock.now = m_end
    sched.pending.fire()
    assert store.snapshot.effective_status("v1") == "AVAILABLE"
    assert store.snapshot.fleet_counts["maintenance"] == 0


def test_maintenance_wins_precedence_unchanged_at_boundary():
    # maintenance 12:00-12:20, reservation 12:00-13:00 (both cover T0)
    m_end = T0 + timedelta(minutes=20)
    r_end = T0 + timedelta(minutes=60)

    def seed(s):
        _v(s, "v1")
        _r(s, "r1", "v1", T0 - timedelta(minutes=1), r_end, status="ACTIVE")
        _m(s, "m1", "v1", T0 - timedelta(minutes=1), m_end)

    store, bc, sched, clock = _make(T0, seed)
    assert store.snapshot.effective_status("v1") == "MAINTENANCE"  # maintenance wins
    bc.start()
    assert bc.next_boundary == m_end

    clock.now = m_end
    sched.pending.fire()
    # maintenance over → reservation still active → RENTED (precedence intact)
    assert store.snapshot.effective_status("v1") == "RENTED"
    assert bc.next_boundary == r_end

    clock.now = r_end
    sched.pending.fire()
    assert store.snapshot.effective_status("v1") == "AVAILABLE"
