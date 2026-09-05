"""
Dashboard snapshot — the OFFLINE (DomainStore) port of
``shared/dashboard_reference.py``.

This module reads rows out of the local mirror and hands them to the SAME
normative spec the FastAPI backend uses. It contains no business arithmetic,
so the offline figure and the server figure are computed by identical code and
can only differ if the mirror itself is behind.

STRICT SOURCE-OF-TRUTH RULE
---------------------------
This path is a FALLBACK, never an authority. It runs only when the server is
unreachable (or has not answered yet), and every DTO it produces is stamped
``source="local"`` so the UI can label it "Hors ligne — cache" instead of
passing it off as live truth. Local figures are NEVER merged key-by-key into a
server DTO: the previous design did exactly that (server revenue + locally
re-derived fleet counts) and produced dashboards where the cards contradicted
both each other and the database.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from shared.dashboard_reference import (
    SCHEMA_VERSION,
    TOP_VEHICLES_LIMIT,
    build_snapshot,
    resolve_period,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SCHEMA_VERSION",
    "TOP_VEHICLES_LIMIT",
    "build_local_snapshot",
    "resolve_period",
    "rows_from_domain_snapshot",
]


def _v(row, key, default=None):
    """Read a key from a dict row or an ORM row indifferently."""
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def rows_from_domain_snapshot(snap) -> tuple[list[dict], list[dict], list[dict]]:
    """Project a ``DomainSnapshot`` onto the shared spec's row contract.

    NOTE the vehicle ``status``: a DomainStore vehicle dict carries the
    canonical *effective* status in ``status`` and the persisted column in
    ``raw_status``. The spec derives the effective status itself and must be
    given the PERSISTED value — feeding it the already-derived one would make
    a RENTED car look like a structurally unknown status and quietly change
    the buckets.
    """
    vehicles = [
        {
            "id": str(_v(v, "id") or ""),
            "status": _v(v, "raw_status") or _v(v, "status"),
            "registration": _v(v, "registration") or "",
            "brand": _v(v, "brand") or "",
            "model": _v(v, "model") or "",
        }
        for v in (snap.vehicles or ())
    ]
    reservations = [
        {
            "id": str(_v(r, "id") or ""),
            "vehicle_id": str(_v(r, "vehicle_id") or ""),
            "status": _v(r, "status"),
            "cancellation_reason": _v(r, "cancellation_reason"),
            "cancelled_at": _v(r, "cancelled_at"),
            "start_datetime": _v(r, "start_datetime"),
            "end_datetime": _v(r, "end_datetime"),
            "num_days": int(_v(r, "num_days") or 0),
            "total_price": _v(r, "total_price"),
            "daily_price": _v(r, "daily_price"),
        }
        for r in (snap.reservations or ())
    ]
    maintenances = [
        {
            "id": str(_v(m, "id") or ""),
            "vehicle_id": str(_v(m, "vehicle_id") or ""),
            "status": _v(m, "status"),
            "start_datetime": _v(m, "start_datetime"),
            "expected_end_datetime": _v(m, "expected_end_datetime"),
            "actual_end_datetime": _v(m, "actual_end_datetime"),
        }
        for m in (snap.maintenances or ())
    ]
    return vehicles, reservations, maintenances


def build_local_snapshot(
    snap,
    period: str = "month",
    custom_from: Optional[date] = None,
    custom_to_inclusive: Optional[date] = None,
    now: Optional[datetime] = None,
    top_limit: int = TOP_VEHICLES_LIMIT,
) -> dict:
    """The full dashboard DTO from the local mirror, stamped ``source="local"``."""
    vehicles, reservations, maintenances = rows_from_domain_snapshot(snap)
    return build_snapshot(
        vehicles, reservations, maintenances,
        period=period, custom_from=custom_from,
        custom_to_inclusive=custom_to_inclusive, now=now, top_limit=top_limit,
        source="local",
    )
