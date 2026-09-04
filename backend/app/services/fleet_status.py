"""
Canonical fleet effective-status derivation — the SINGLE source of truth for
"what state is this vehicle in right now".

`vehicle.status` (the persisted column) only carries STRUCTURAL state
(`SOLD`, `INACTIVE`) plus a `MAINTENANCE` hint. The state a user sees on every
list / dashboard / mobile screen is DERIVED here from the live reservation and
maintenance rows, so the Vehicles list, `/vehicles/stats` and the Dashboard can
never disagree.

Precedence (mutually exclusive — a vehicle is in exactly one bucket):

    SOLD / INACTIVE   (structural, from vehicle.status — never overridden)
    MAINTENANCE       (an active maintenance period occupies `now`)
    RENTED            (a blocking reservation COVERS `now`: start <= now < end)
    RESERVED          (a blocking reservation is UPCOMING: now < start)
    AVAILABLE         (none of the above)

A "blocking" reservation is one whose status is RESERVED or ACTIVE. RENTED is
time-derived, not status-derived: this business hands the car over at the
reservation start with no separate pickup step, so a RESERVED reservation
whose window contains `now` still means the car is out.

Interval rule: half-open `[start, end)`. An active maintenance ticket
(`status NOT IN (COMPLETED, CANCELLED)`) with no explicit end occupies its
vehicle from `start_datetime` until it is closed — `effective_end =
COALESCE(actual_end_datetime, expected_end_datetime, +infinity)`.
"""
from datetime import datetime, timezone
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import select, func, literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.models.reservation import Reservation
from app.models.maintenance import Maintenance

STRUCTURAL_STATUSES = ("SOLD", "INACTIVE")
BLOCKING_RESERVATION_STATUSES = ("RESERVED", "ACTIVE")
TERMINAL_MAINTENANCE_STATUSES = ("COMPLETED", "CANCELLED")

# Sentinel used wherever a maintenance ticket has no explicit end: it occupies
# the vehicle until it is closed.
FAR_FUTURE = datetime(9999, 12, 31, tzinfo=timezone.utc)

EFFECTIVE_AVAILABLE = "AVAILABLE"
EFFECTIVE_RESERVED = "RESERVED"
EFFECTIVE_RENTED = "RENTED"
EFFECTIVE_MAINTENANCE = "MAINTENANCE"


def _maintenance_effective_end():
    return func.coalesce(
        Maintenance.actual_end_datetime,
        Maintenance.expected_end_datetime,
        literal(FAR_FUTURE),
    )


async def compute_effective_statuses(
    session: AsyncSession,
    vehicle_ids: Optional[Iterable[UUID]] = None,
    now: Optional[datetime] = None,
) -> dict[str, str]:
    """Return {str(vehicle_id): effective_status} for the requested vehicles
    (or all vehicles when ``vehicle_ids`` is None)."""
    now = now or datetime.now(timezone.utc)

    v_query = select(Vehicle.id, Vehicle.status)
    if vehicle_ids is not None:
        ids = list(vehicle_ids)
        if not ids:
            return {}
        v_query = v_query.where(Vehicle.id.in_(ids))
    rows = (await session.execute(v_query)).all()
    result: dict[str, str] = {}
    structural: set[str] = set()
    for vid, vstatus in rows:
        if vstatus in STRUCTURAL_STATUSES:
            result[str(vid)] = vstatus
            structural.add(str(vid))
        else:
            result[str(vid)] = EFFECTIVE_AVAILABLE

    candidate_ids = [vid for vid in result if vid not in structural]
    if not candidate_ids:
        return result

    # Maintenance occupancy (highest precedence after structural).
    # Use bare typed columns (not func.distinct) so the UUID type decorator
    # still normalises values — otherwise SQLite returns dash-less hex that
    # would not match str(Vehicle.id).
    m_query = (
        select(Maintenance.vehicle_id)
        .where(
            Maintenance.status.notin_(TERMINAL_MAINTENANCE_STATUSES),
            Maintenance.start_datetime <= now,
            _maintenance_effective_end() > now,
        )
        .distinct()
    )
    if vehicle_ids is not None:
        m_query = m_query.where(Maintenance.vehicle_id.in_(vehicle_ids))
    maint_vids = {str(v) for (v,) in (await session.execute(m_query)).all()}

    # Reservation occupancy. A blocking reservation (RESERVED or ACTIVE) whose
    # window contains `now` means the car is physically out -> RENTED (this
    # business has no separate pickup step). A blocking reservation that is
    # still upcoming (`now < start`) -> RESERVED.
    r_query = (
        select(
            Reservation.vehicle_id,
            Reservation.start_datetime,
        )
        .where(
            Reservation.status.in_(BLOCKING_RESERVATION_STATUSES),
            Reservation.end_datetime > now,
        )
        .distinct()
    )
    if vehicle_ids is not None:
        r_query = r_query.where(Reservation.vehicle_id.in_(vehicle_ids))
    rented_vids: set[str] = set()
    reserved_vids: set[str] = set()
    for vid, r_start in (await session.execute(r_query)).all():
        if r_start is not None and r_start.tzinfo is None:
            # Unified naive-datetime policy: business-local wall time, as
            # shared.money_time / shared.fleet_status_reference (audit P2-4).
            from shared.money_time import BUSINESS_TZ
            r_start = r_start.replace(tzinfo=BUSINESS_TZ)
        if r_start is not None and r_start <= now:
            rented_vids.add(str(vid))
        else:
            reserved_vids.add(str(vid))
    reserved_vids -= rented_vids

    for vid in candidate_ids:
        if vid in maint_vids:
            result[vid] = EFFECTIVE_MAINTENANCE
        elif vid in rented_vids:
            result[vid] = EFFECTIVE_RENTED
        elif vid in reserved_vids:
            result[vid] = EFFECTIVE_RESERVED
        else:
            result[vid] = EFFECTIVE_AVAILABLE
    return result


async def compute_fleet_counts(
    session: AsyncSession, now: Optional[datetime] = None
) -> dict:
    """Canonical fleet breakdown. The four operational buckets are mutually
    exclusive and always sum to ``total_vehicles`` (vehicles that are neither
    SOLD nor INACTIVE)."""
    statuses = await compute_effective_statuses(session, vehicle_ids=None, now=now)
    counts = {
        EFFECTIVE_AVAILABLE: 0,
        EFFECTIVE_RESERVED: 0,
        EFFECTIVE_RENTED: 0,
        EFFECTIVE_MAINTENANCE: 0,
    }
    for st in statuses.values():
        if st in counts:
            counts[st] += 1
    total = sum(counts.values())
    return {
        "total_vehicles": total,
        "available": counts[EFFECTIVE_AVAILABLE],
        "reserved": counts[EFFECTIVE_RESERVED],
        "rented": counts[EFFECTIVE_RENTED],
        "maintenance": counts[EFFECTIVE_MAINTENANCE],
    }
