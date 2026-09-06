"""Canonical local domain-state layer for the desktop app.

`DomainStore` is the single reactive in-memory projection of the offline
SQLite database. Views subscribe to it; they never derive a competing global
state. `BoundaryClock` schedules updates at time-derived boundaries.
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
