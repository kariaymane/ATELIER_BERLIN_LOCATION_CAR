"""
Canonical fleet effective-status derivation for the desktop (offline mirror of
backend/app/services/fleet_status.py and the normative
shared/fleet_status_reference.py).

ONE core decides "what state is this vehicle in right now" — used by:
  * the DomainStore snapshot build (`compute_fleet_sets`, session adapter)
  * the DomainStore temporal recompute (`compute_fleet_sets_rows`, pure)
  * the Dashboard offline overview (`compute_fleet_counts`)
so the Vehicles page, the Dashboard and the BoundaryClock can never disagree.

Precedence (mutually exclusive):
    SOLD / INACTIVE  (structural)  >  MAINTENANCE  >  RENTED  >  RESERVED  >  AVAILABLE

RENTED is time-derived: a blocking reservation (RESERVED or ACTIVE) whose
window contains ``now`` means the car is physically out — this business has no
separate "pickup" step. RESERVED means a blocking reservation is still
UPCOMING (``now < start``), surfaced so staff see committed demand.

Interval rule: half-open [start, end). A vehicle is occupied for
``start <= now < end``; exactly at ``end`` it is free again. An active
maintenance ticket (status NOT IN COMPLETED/CANCELLED) with no explicit end
occupies its vehicle from start until it is closed (effective_end = +infinity).
"""
from datetime import datetime, timedelta, timezone

from app.utils.datetime_utils import parse_datetime_utc

STRUCTURAL_STATUSES = ("SOLD", "INACTIVE")
TERMINAL_MAINTENANCE_STATUSES = ("COMPLETED", "CANCELLED")
BLOCKING_RESERVATION_STATUSES = ("ACTIVE", "RESERVED")
FAR_FUTURE = datetime(9999, 12, 31, tzinfo=timezone.utc)

EFFECTIVE_AVAILABLE = "AVAILABLE"
EFFECTIVE_RESERVED = "RESERVED"
EFFECTIVE_RENTED = "RENTED"
EFFECTIVE_MAINTENANCE = "MAINTENANCE"


def _get(obj, name, default=None):
    """Read ``name`` from a dict or an ORM object."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _maintenance_end(m):
    end = parse_datetime_utc(
        _get(m, "actual_end_datetime") or _get(m, "expected_end_datetime")
    )
    return end or FAR_FUTURE


# ── pure core (row dicts / ORM objects, explicit `now`) ─────────────────────
def compute_fleet_sets_rows(vehicles, reservations, maintenances, now=None):
    """Return (rented_vids, reserved_vids, maintenance_vids, total_vehicles).

    Works on any iterable of dicts or ORM rows exposing ``id``/``status`` for
    vehicles and ``vehicle_id``/``status``/``start_datetime``/``end_datetime``
    (reservations) resp. ``expected_end_datetime``/``actual_end_datetime``
    (maintenances). This is THE derivation — the session variant below is a
    thin adapter over it.
    """
    now = now or datetime.now(timezone.utc)

    structural = {
        _get(v, "id") for v in vehicles
        if (_get(v, "status") or "").upper() in STRUCTURAL_STATUSES
    }
    total_vehicles = sum(
        1 for v in vehicles
        if (_get(v, "status") or "").upper() not in STRUCTURAL_STATUSES
    )

    maintenance_vids = set()
    for m in maintenances:
        if (_get(m, "status") or "").upper() in TERMINAL_MAINTENANCE_STATUSES:
            continue
        vid = _get(m, "vehicle_id")
        if vid in structural:
            continue
        m_start = parse_datetime_utc(_get(m, "start_datetime"))
        if m_start and m_start <= now < _maintenance_end(m):
            maintenance_vids.add(vid)

    rented_vids = set()
    reserved_vids = set()
    for r in reservations:
        st = (_get(r, "status") or "").upper()
        if st not in BLOCKING_RESERVATION_STATUSES:
            continue
        vid = _get(r, "vehicle_id")
        if vid in structural or vid in maintenance_vids:
            continue
        r_start = parse_datetime_utc(_get(r, "start_datetime"))
        r_end = parse_datetime_utc(_get(r, "end_datetime"))
        if not r_start or not r_end:
            continue
        if r_start <= now < r_end:
            # Window contains now -> car is out (no separate pickup step).
            rented_vids.add(vid)
        elif now < r_start:
            # Upcoming booking -> surfaced as RESERVED.
            reserved_vids.add(vid)

    reserved_vids -= rented_vids
    return rented_vids, reserved_vids, maintenance_vids, total_vehicles


def compute_fleet_counts_rows(vehicles, reservations, maintenances, now=None):
    rented, reserved, maint, total = compute_fleet_sets_rows(
        vehicles, reservations, maintenances, now)
    return {
        "total_vehicles": total,
        "available": max(0, total - len(rented) - len(reserved) - len(maint)),
        "reserved": len(reserved),
        "rented": len(rented),
        "maintenance": len(maint),
    }


def effective_statuses_rows(vehicles, reservations, maintenances, now=None):
    """{vehicle_id: effective status} for every vehicle."""
    rented, reserved, maint, _total = compute_fleet_sets_rows(
        vehicles, reservations, maintenances, now)
    out = {}
    for v in vehicles:
        vid = _get(v, "id")
        out[str(vid)] = effective_status(_get(v, "status"), vid, rented, reserved, maint)
    return out


def next_local_midnight(now=None, tz_name="Africa/Casablanca"):
    """The next local-midnight in ``tz_name`` strictly after ``now`` (aware UTC).
    Used for dashboard period (today/week/month) rollover."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(tz_name)
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    local_midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc)


def next_boundary_rows(reservations, maintenances, now=None,
                       include_midnight=False, tz_name="Africa/Casablanca"):
    """The earliest FUTURE instant (strictly ``> now``) at which some vehicle's
    effective status — or (when ``include_midnight``) a dashboard period card —
    can change with no user action: the reservation/maintenance interval edges,
    plus the next local midnight. Returns an aware-UTC datetime, or None when
    nothing is pending. Half-open semantics: an edge at exactly ``now`` has
    already taken effect and is not returned.
    """
    now = now or datetime.now(timezone.utc)
    cands = []

    for r in reservations:
        if (_get(r, "status") or "").upper() not in BLOCKING_RESERVATION_STATUSES:
            continue
        for key in ("start_datetime", "end_datetime"):
            dt = parse_datetime_utc(_get(r, key))
            if dt is not None and dt > now:
                cands.append(dt)

    for m in maintenances:
        if (_get(m, "status") or "").upper() in TERMINAL_MAINTENANCE_STATUSES:
            continue
        start = parse_datetime_utc(_get(m, "start_datetime"))
        if start is not None and start > now:
            cands.append(start)
        end = _maintenance_end(m)
        if end != FAR_FUTURE and end > now:
            cands.append(end)

    if include_midnight:
        cands.append(next_local_midnight(now, tz_name))

    return min(cands) if cands else None


# ── session adapters (unchanged public API) ────────────────────────────────
def _rows_from_session(session):
    from app.models.vehicle import LocalVehicle
    from app.models.reservation import LocalReservation
    from app.models.maintenance import LocalMaintenance
    return (
        session.query(LocalVehicle).all(),
        session.query(LocalReservation).all(),
        session.query(LocalMaintenance).all(),
    )


def compute_fleet_sets(session, now=None):
    """Return (rented_vids, reserved_vids, maintenance_vids, total_vehicles)
    from the local SQLite session (thin adapter over the pure core)."""
    vehicles, reservations, maintenances = _rows_from_session(session)
    return compute_fleet_sets_rows(vehicles, reservations, maintenances, now)


def compute_fleet_counts(session, now=None):
    """Canonical fleet breakdown — mutually exclusive, sums to total_vehicles."""
    vehicles, reservations, maintenances = _rows_from_session(session)
    return compute_fleet_counts_rows(vehicles, reservations, maintenances, now)


def effective_status(v_status, vehicle_id, rented_vids, reserved_vids, maintenance_vids):
    """Resolve one vehicle's effective status given the disjoint sets."""
    if (v_status or "").upper() in STRUCTURAL_STATUSES:
        return v_status
    if vehicle_id in maintenance_vids:
        return EFFECTIVE_MAINTENANCE
    if vehicle_id in rented_vids:
        return EFFECTIVE_RENTED
    if vehicle_id in reserved_vids:
        return EFFECTIVE_RESERVED
    return EFFECTIVE_AVAILABLE
