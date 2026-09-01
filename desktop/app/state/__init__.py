"""Canonical local domain-state layer for the desktop app.

`DomainStore` is the single reactive in-memory projection of the offline
SQLite database. Views subscribe to it; they never derive a competing global
state. `BoundaryClock` makes it time-reactive. See
`MASTER_100_PERCENT_LIVE_ARCHITECTURE_REPORT.md` (Increments 2 & 3).
"""
from app.state.domain_store import (
    DomainStore,
    DomainSnapshot,
    get_domain_store,
    reset_domain_store,
)
from app.state.boundary_clock import BoundaryClock

__all__ = [
    "DomainStore",
    "DomainSnapshot",
    "get_domain_store",
    "reset_domain_store",
    "BoundaryClock",
]
