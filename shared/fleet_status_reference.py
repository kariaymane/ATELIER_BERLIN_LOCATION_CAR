"""
NORMATIVE SPECIFICATION — vehicle effective-status derivation.

This is the single authoritative definition of "what state is a vehicle in
right now". It is a pure function over primitive dicts (no ORM, no DB, no
network) so that every runtime can be tested against it byte-for-byte:

    backend/app/services/fleet_status.py   (async SQLAlchemy)   -> must match
    desktop/app/utils/fleet_status.py      (sync SQLAlchemy)    -> must match
    mobile .../data/... effective status   (Kotlin)             -> must match

If any runtime's output diverges from this reference for any case in
``shared/fleet_status_cases.json`` the corresponding cross-runtime parity
test fails. That converts "the three screens disagree" from a production
incident into a red build.

------------------------------------------------------------------------
PRECEDENCE  (mutually exclusive — a vehicle is in exactly one bucket)

    SOLD / INACTIVE   structural, taken verbatim from vehicle.status
    MAINTENANCE       an active maintenance period covers `now`
    RENTED            a blocking reservation COVERS `now` (start <= now < end)
    RESERVED          a blocking reservation is UPCOMING (now < start)
    AVAILABLE         none of the above

RENTED is time-derived, not status-derived: this business hands the vehicle
over at the reservation start and has no separate "pickup" step, so a
reservation whose window contains `now` means the car is physically out —
whether its stored status is RESERVED or ACTIVE. The stored ACTIVE status is
an optional refinement, never a precondition for "en location".

INTERVAL RULE: half-open [start, end). Adjacent intervals do not overlap.

MAINTENANCE is "active" when status NOT IN (COMPLETED, CANCELLED) and
    start <= now < COALESCE(actual_end, expected_end, +infinity)

RESERVATION is "blocking" when status IN (RESERVED, ACTIVE); it is
    RENTED   when start <= now < end
    RESERVED when now < start   (a future booking — surfaced so staff see it)
------------------------------------------------------------------------
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# ONE naive-datetime policy across the whole product: a datetime that lost its
# tzinfo (e.g. a SQLite round-trip) is read as business-local wall time, exactly
# as shared.money_time.to_business does. Previously this module read a naive
# value as UTC while the revenue engine read it as Casablanca — a latent ~1 h
# split (v1.1.0 audit P2-4 / earlier forensics). Now unified.
_BUSINESS_TZ = ZoneInfo("Africa/Casablanca")

STRUCTURAL_STATUSES = ("SOLD", "INACTIVE")
BLOCKING_RESERVATION_STATUSES = ("RESERVED", "ACTIVE")
TERMINAL_MAINTENANCE_STATUSES = ("COMPLETED", "CANCELLED")

EFFECTIVE_AVAILABLE = "AVAILABLE"
EFFECTIVE_RESERVED = "RESERVED"
EFFECTIVE_RENTED = "RENTED"
EFFECTIVE_MAINTENANCE = "MAINTENANCE"

_FAR_FUTURE = datetime(9999, 12, 31, tzinfo=timezone.utc)


def _parse(value):
    """ISO-8601 / naive / datetime -> aware UTC datetime, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip().replace("Z", "+00:00").replace("z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_BUSINESS_TZ)   # unified: naive == business-local
    return dt.astimezone(timezone.utc)


def _norm(s):
    return (s or "").strip().upper()


def _maintenance_end(m):
    return (
        _parse(m.get("actual_end") or m.get("actual_end_datetime"))
        or _parse(m.get("expected_end") or m.get("expected_end_datetime"))
        or _FAR_FUTURE
    )


def effective_statuses(vehicles, reservations, maintenances, now):
    """Return {vehicle_id: effective_status} for every vehicle.

    vehicles      : [{"id": str, "status": str}]
    reservations  : [{"vehicle_id": str, "status": str, "start": iso, "end": iso}]
    maintenances  : [{"vehicle_id": str, "status": str, "start": iso,
                      "expected_end": iso|None, "actual_end": iso|None}]
    now           : datetime | iso str
    """
    now = _parse(now)
    if now is None:
        raise ValueError("now is required and must be a valid datetime")

    result: dict[str, str] = {}
    structural: set[str] = set()
    for v in vehicles:
        vid = str(v["id"])
        st = _norm(v.get("status"))
        if st in STRUCTURAL_STATUSES:
            result[vid] = st
            structural.add(vid)
        else:
            result[vid] = EFFECTIVE_AVAILABLE

    maint_vids: set[str] = set()
    for m in maintenances:
        vid = str(m["vehicle_id"])
        if vid in structural or vid not in result:
            continue
        if _norm(m.get("status")) in TERMINAL_MAINTENANCE_STATUSES:
            continue
        start = _parse(m.get("start") or m.get("start_datetime"))
        if start is not None and start <= now < _maintenance_end(m):
            maint_vids.add(vid)

    rented_vids: set[str] = set()
    reserved_vids: set[str] = set()
    for r in reservations:
        vid = str(r["vehicle_id"])
        if vid in structural or vid in maint_vids or vid not in result:
            continue
        if _norm(r.get("status")) not in BLOCKING_RESERVATION_STATUSES:
            continue
        start = _parse(r.get("start") or r.get("start_datetime"))
        end = _parse(r.get("end") or r.get("end_datetime"))
        if start is None or end is None:
            continue
        if start <= now < end:
            # Window contains now -> the car is out, regardless of RESERVED/ACTIVE.
            rented_vids.add(vid)
        elif now < start:
            # Upcoming booking -> surface it so staff see committed demand.
            reserved_vids.add(vid)
    reserved_vids -= rented_vids

    for vid in result:
        if vid in structural:
            continue
        if vid in maint_vids:
            result[vid] = EFFECTIVE_MAINTENANCE
        elif vid in rented_vids:
            result[vid] = EFFECTIVE_RENTED
        elif vid in reserved_vids:
            result[vid] = EFFECTIVE_RESERVED
        else:
            result[vid] = EFFECTIVE_AVAILABLE
    return result


def fleet_counts(vehicles, reservations, maintenances, now):
    """Canonical breakdown; the four operational buckets are mutually
    exclusive and always sum to total_vehicles (non-structural vehicles)."""
    statuses = effective_statuses(vehicles, reservations, maintenances, now)
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


def next_boundary(reservations, maintenances, now):
    """The earliest future instant at which any vehicle's effective status
    can change with no user action — used to arm a single wake-up timer
    instead of polling. Returns a datetime or None (nothing pending)."""
    now = _parse(now)
    cands = []
    for r in reservations:
        if _norm(r.get("status")) not in BLOCKING_RESERVATION_STATUSES:
            continue
        for key in ("start", "end", "start_datetime", "end_datetime"):
            dt = _parse(r.get(key))
            if dt is not None and dt > now:
                cands.append(dt)
    for m in maintenances:
        if _norm(m.get("status")) in TERMINAL_MAINTENANCE_STATUSES:
            continue
        start = _parse(m.get("start") or m.get("start_datetime"))
        if start is not None and start > now:
            cands.append(start)
        end = _maintenance_end(m)
        if end != _FAR_FUTURE and end > now:
            cands.append(end)
    return min(cands) if cands else None
