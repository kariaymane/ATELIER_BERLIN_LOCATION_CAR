"""
BoundaryClock — the ONE temporal mechanism that makes the desktop app
time-reactive (Increment 3 of the 100%-live program).

PROBLEM IT SOLVES
-----------------
`DomainStore` only republishes on a mutation, a sync, or a manual refresh.
A reservation that ends at 18:00, with no other activity, would keep showing
`RENTED` after 18:00. Time itself is a valid state-transition source and must
drive a recompute — automatically, with no user action.

DESIGN (single canonical clock — never a per-widget timer)
---------------------------------------------------------
1. read the CURRENT canonical snapshot's reservation + maintenance rows
2. ask `app.utils.fleet_status.next_boundary_rows(...)` for the earliest
   FUTURE instant (strictly > now) at which some vehicle's effective status
   could change purely because time advanced
3. sleep exactly until that instant (ONE single-shot timer — no polling)
4. on fire: `DomainStore.recompute_effective(now)` — re-derive against the
   new `now` with NO SQLite read and NO network. The store publishes a new
   monotonic revision ONLY if the canonical state actually changed.
5. compute the next boundary and reschedule.

It subscribes to the store, so any mutation / sync / manual reload that
changes the row set immediately reschedules the clock to the new earliest
boundary. Every reschedule bumps a generation counter, so a timer that was
already in flight for an obsolete boundary is ignored when it fires.

The scheduler and the clock source are both injectable for deterministic
tests (no real waiting, no leaked threads).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _QtTimerHandle:
    def __init__(self, timer):
        self._timer = timer

    def cancel(self) -> None:
        try:
            self._timer.stop()
            self._timer.deleteLater()
        except Exception:
            pass


def _qt_schedule(delay_seconds: float, callback: Callable[[], None]):
    """Production scheduler: a single-shot QTimer on the UI thread."""
    from PySide6.QtCore import QTimer
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(callback)
    timer.start(max(0, int(round(delay_seconds * 1000))))
    return _QtTimerHandle(timer)


class BoundaryClock:
    def __init__(
        self,
        store,
        *,
        now_fn: Optional[Callable[[], datetime]] = None,
        schedule_fn: Optional[Callable[[float, Callable[[], None]], object]] = None,
        max_delay_seconds: float = 24 * 3600.0,
        min_delay_seconds: float = 0.0,
        slack_seconds: float = 0.05,
    ) -> None:
        self._store = store
        self._now = now_fn or _utcnow
        self._schedule = schedule_fn or _qt_schedule
        self._max_delay = float(max_delay_seconds)
        self._min_delay = float(min_delay_seconds)
        # fire a hair AFTER the boundary so `now >= boundary` at fire time and
        # the half-open recompute reliably sees the transition (real timers
        # can wake a few ms early).
        self._slack = float(slack_seconds)

        self._running = False
        self._handle = None
        self._generation = 0
        self._scheduled_for: Optional[datetime] = None
        self._unsub: Optional[Callable[[], None]] = None
        self._fire_count = 0          # diagnostics / tests
        self._publish_count = 0       # temporal transitions that changed state

    # ── introspection ──────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return self._running

    @property
    def next_boundary(self) -> Optional[datetime]:
        return self._scheduled_for

    @property
    def fire_count(self) -> int:
        return self._fire_count

    @property
    def publish_count(self) -> int:
        return self._publish_count

    # ── lifecycle ──────────────────────────────────────────────────────
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        # any snapshot change reschedules us to the new earliest boundary
        self._unsub = self._store.subscribe(self._on_store_published)
        self.reschedule()

    def stop(self) -> None:
        self._running = False
        self._generation += 1          # invalidate any in-flight timer
        self._cancel_handle()
        self._scheduled_for = None
        if self._unsub is not None:
            try:
                self._unsub()
            except Exception:
                pass
            self._unsub = None

    def _cancel_handle(self) -> None:
        if self._handle is not None:
            try:
                self._handle.cancel()
            except Exception:
                pass
            self._handle = None

    # ── scheduling ─────────────────────────────────────────────────────
    def _target_boundary(self, now: datetime) -> Optional[datetime]:
        from app.utils.fleet_status import next_boundary_rows
        snap = self._store.snapshot
        # include local midnight so the dashboard period cards roll at 00:00
        return next_boundary_rows(
            list(snap.reservations), list(snap.maintenances), now, include_midnight=True)

    def _on_store_published(self, snapshot, revision) -> None:
        # tolerant: this is a store subscriber; reschedule to the new boundary
        self.reschedule()

    def reschedule(self) -> None:
        """(Re)arm the single timer for the current earliest boundary.

        Bumps the generation so any timer already scheduled for a now-obsolete
        boundary is ignored when it fires. Safe to call re-entrantly from a
        store notification."""
        self._generation += 1
        gen = self._generation
        self._cancel_handle()
        if not self._running:
            self._scheduled_for = None
            return
        now = self._now()
        target = self._target_boundary(now)
        self._scheduled_for = target
        if target is None:
            return  # nothing pending — sleep forever (until the next mutation)
        delay = (target - now).total_seconds() + self._slack
        delay = max(self._min_delay, min(delay, self._max_delay))
        self._handle = self._schedule(delay, lambda g=gen: self._fire(g))

    def _fire(self, generation: int) -> None:
        if generation != self._generation or not self._running:
            return  # obsolete schedule — a newer reschedule superseded it
        self._handle = None
        self._fire_count += 1
        try:
            published = self._store.recompute_effective(now=self._now())
            if published:
                self._publish_count += 1
        except Exception:
            logger.error("BoundaryClock temporal recompute failed", exc_info=True)
        # If the store published, our store subscription already rescheduled us;
        # if it did not, we still need to move past the edge we just serviced.
        self.reschedule()
