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

WHY THE TIME PREDICATE IS EVALUATED IN PYTHON, NOT IN SQL
---------------------------------------------------------
SQL is used to select CANDIDATE ROWS BY STATUS only; every `start <= now < end`
comparison happens in Python via `_coerce`. Pushing the range comparison into
SQL made the backend disagree with itself across dialects:

  * PostgreSQL stores TIMESTAMPTZ, so a row is always aware and SQL is correct.
  * SQLite has no zone type. SQLAlchemy writes the *wall-clock digits* and
    silently DISCARDS the offset, so an aware `13:00+01:00` and a naive `13:00`
    become the identical text `'2026-08-30 13:00:00.000000'`. The bound `now`
    is then compared lexically, and `ts > now` returned rows where
    `ts == now` — a half-open-interval violation.

Evaluating in Python under the ONE naive policy (`shared.money_time`: a value
with no offset is business-local wall time) makes PostgreSQL, SQLite, the
desktop mirror and `shared/fleet_status_reference` produce byte-identical
buckets. The `naive_*` vectors in `shared/fleet_status_cases.json` pin it.

Cost: the open-row scan is bounded by the STATUS filter (non-terminal
reservations / maintenance), i.e. by live business volume, not by history.
"""
from datetime import datetime, timezone
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.models.reservation import Reservation
from app.models.maintenance import Maintenance
from shared.money_time import BUSINESS_TZ

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


def _coerce(dt: Optional[datetime]) -> Optional[datetime]:
    """THE naive-datetime policy, product-wide: a datetime with no offset is
    business-local wall time (Africa/Casablanca), never UTC. Mirrors
    ``shared.money_time.to_business`` / ``shared.fleet_status_reference._parse``
    / ``desktop.app.utils.datetime_utils.parse_datetime_utc``. Output is
    always aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BUSINESS_TZ)
    return dt.astimezone(timezone.utc)


def _maintenance_effective_end(actual_end, expected_end) -> datetime:
    """COALESCE(actual_end, expected_end, +infinity), coerced. An open ticket
    occupies its vehicle until it is closed."""
    return _coerce(actual_end) or _coerce(expected_end) or FAR_FUTURE


async def compute_effective_statuses(
    session: AsyncSession,
    vehicle_ids: Optional[Iterable[UUID]] = None,
    now: Optional[datetime] = None,
) -> dict[str, str]:
    """Return {str(vehicle_id): effective_status} for the requested vehicles
    (or all vehicles when ``vehicle_ids`` is None)."""
    now = _coerce(now or datetime.now(timezone.utc))

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
    # SQL selects by STATUS only; the interval test is done in Python under the
    # single naive policy (see module docstring). Use bare typed columns (not
    # func.distinct) so the UUID type decorator still normalises values —
    # otherwise SQLite returns dash-less hex that would not match str(Vehicle.id).
    m_query = select(
        Maintenance.vehicle_id,
        Maintenance.start_datetime,
        Maintenance.actual_end_datetime,
        Maintenance.expected_end_datetime,
    ).where(Maintenance.status.notin_(TERMINAL_MAINTENANCE_STATUSES))
    if vehicle_ids is not None:
        m_query = m_query.where(Maintenance.vehicle_id.in_(vehicle_ids))
    maint_vids: set[str] = set()
    for vid, m_start, m_actual_end, m_expected_end in (await session.execute(m_query)).all():
        m_start = _coerce(m_start)
        if m_start is not None and m_start <= now < _maintenance_effective_end(
            m_actual_end, m_expected_end
        ):
            maint_vids.add(str(vid))

    # Reservation occupancy. A blocking reservation (RESERVED or ACTIVE) whose
    # window contains `now` means the car is physically out -> RENTED (this
    # business has no separate pickup step). A blocking reservation that is
    # still upcoming (`now < start`) -> RESERVED. A window that has already
    # closed (`now >= end`) blocks nothing — half-open [start, end).
    r_query = select(
        Reservation.vehicle_id,
        Reservation.start_datetime,
        Reservation.end_datetime,
    ).where(Reservation.status.in_(BLOCKING_RESERVATION_STATUSES))
    if vehicle_ids is not None:
        r_query = r_query.where(Reservation.vehicle_id.in_(vehicle_ids))
    rented_vids: set[str] = set()
    reserved_vids: set[str] = set()
    for vid, r_start, r_end in (await session.execute(r_query)).all():
        r_start = _coerce(r_start)
        r_end = _coerce(r_end)
        if r_start is None or r_end is None:
            continue
        if r_start <= now < r_end:
            rented_vids.add(str(vid))
        elif now < r_start:
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
