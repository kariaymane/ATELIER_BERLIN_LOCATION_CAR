"""
Dashboard snapshot — the PostgreSQL port of ``shared/dashboard_reference.py``.

This module does exactly two things: it reads the rows, and it hands them to
the normative spec. It contains no business arithmetic of its own, so the
server, the desktop offline path and the parity tests cannot diverge — they
all execute the same shared code.

WHY THIS EXISTS
---------------
Before the 2026-09-05 rebuild the Dashboard was assembled from three separate
HTTP round-trips (``/dashboard/stats``, ``/dashboard/vehicle-performance``,
``/dashboard/revenue``) taken at three different instants, and the desktop then
overwrote some of the returned fleet keys with numbers re-derived from its own
stale SQLite mirror. Cards could therefore contradict each other and contradict
the database. Now every figure comes from ONE read set against ONE ``now``.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance import Maintenance
from app.models.reservation import Reservation
from app.models.vehicle import Vehicle
from shared.dashboard_reference import (
    SCHEMA_VERSION,
    TOP_VEHICLES_LIMIT,
    build_snapshot,
    legacy_overview,
    resolve_period,
)
from shared.money_time import to_business

logger = logging.getLogger(__name__)

__all__ = [
    "SCHEMA_VERSION",
    "TOP_VEHICLES_LIMIT",
    "build_dashboard_snapshot",
    "build_legacy_overview",
    "resolve_period",
]


def _reservation_row(r: Reservation) -> dict:
    """One reservation as a plain dict carrying EVERY key the shared specs
    read, so the fleet derivation and the revenue engine are provably fed the
    same data."""
    return {
        "id": str(r.id),
        "vehicle_id": str(r.vehicle_id),
        "status": r.status,
        "cancellation_reason": r.cancellation_reason,
        "cancelled_at": to_business(r.cancelled_at) if r.cancelled_at else None,
        "start_datetime": to_business(r.start_datetime) if r.start_datetime else None,
        "end_datetime": to_business(r.end_datetime) if r.end_datetime else None,
        "num_days": int(r.num_days or 0),
        "total_price": r.total_price,   # Decimal from NUMERIC — exact
        "daily_price": r.daily_price,
    }


def _maintenance_row(m: Maintenance) -> dict:
    return {
        "id": str(m.id),
        "vehicle_id": str(m.vehicle_id),
        "status": m.status,
        "start_datetime": to_business(m.start_datetime) if m.start_datetime else None,
        "expected_end_datetime": (
            to_business(m.expected_end_datetime) if m.expected_end_datetime else None
        ),
        "actual_end_datetime": (
            to_business(m.actual_end_datetime) if m.actual_end_datetime else None
        ),
    }


def _vehicle_row(v: Vehicle) -> dict:
    return {
        "id": str(v.id),
        "status": v.status,
        "registration": v.registration or "",
        "brand": v.brand or "",
        "model": v.model or "",
    }


async def _load_rows(session: AsyncSession) -> tuple[list[dict], list[dict], list[dict]]:
    """The ONE read set behind every number on the dashboard.

    Reservations and maintenances are loaded in full because the dashboard
    genuinely needs all of history (Top-5 is all-time) and all of the live
    rows (fleet buckets). Slicing them per card is precisely what produced
    mutually inconsistent snapshots before; the volume is bounded by the
    agency's real business size.
    """
    vehicles = (await session.execute(select(Vehicle))).scalars().all()
    reservations = (await session.execute(select(Reservation))).scalars().all()
    maintenances = (await session.execute(select(Maintenance))).scalars().all()
    return (
        [_vehicle_row(v) for v in vehicles],
        [_reservation_row(r) for r in reservations],
        [_maintenance_row(m) for m in maintenances],
    )


async def build_dashboard_snapshot(
    session: AsyncSession,
    period: str = "month",
    custom_from: Optional[date] = None,
    custom_to_inclusive: Optional[date] = None,
    now: Optional[datetime] = None,
    top_limit: int = TOP_VEHICLES_LIMIT,
) -> dict:
    """THE dashboard DTO, computed from PostgreSQL. See the shared spec."""
    vehicles, reservations, maintenances = await _load_rows(session)
    return build_snapshot(
        vehicles, reservations, maintenances,
        period=period, custom_from=custom_from,
        custom_to_inclusive=custom_to_inclusive, now=now, top_limit=top_limit,
        source="server",
    )


async def build_legacy_overview(
    session: AsyncSession, now: Optional[datetime] = None
) -> dict:
    """The legacy ``/dashboard/stats`` flat payload — kept for mobile and
    older desktop builds, and derived from the same rows so it can never
    contradict ``/dashboard/summary``."""
    vehicles, reservations, maintenances = await _load_rows(session)
    return legacy_overview(vehicles, reservations, maintenances, now=now)
