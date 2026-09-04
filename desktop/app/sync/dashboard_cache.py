"""
Offline dashboard cache computation — desktop port of the normative revenue
spec `shared/revenue_reference.py` (PRO-RATA BY DAY).

    Revenue(from, to) = for every non-CANCELLED reservation, split its
    total_price evenly over its num_days; a day counts once it has begun
    (now >= start + i days); sum the per-day rate over the rental's realised
    days whose calendar date is in [from, to).  Period bounds:
    Africa/Casablanca local midnight, week starts Monday.

Parity with the backend + mobile engines is enforced by
`desktop/tests/test_revenue_crossruntime_desktop.py` against
`shared/revenue_cases.json`. Used ONLY for the offline snapshot; the online
API result always wins.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
import math

import logging

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Africa/Casablanca")
NON_REVENUE_STATUSES = ("CANCELLED",)


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return _to_biz(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=TZ)
    s = str(value).strip().replace("Z", "+00:00").replace("z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        return _to_biz(dt)
    except Exception:
        from app.utils.datetime_utils import parse_datetime_utc
        res = parse_datetime_utc(value)
        return _to_biz(res) if res is not None else None


def _to_biz(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def _realised_days(start_dt: datetime, num_days: int, now: datetime) -> int:
    n = math.floor((now - start_dt).total_seconds() / 86400.0) + 1
    return max(0, min(num_days, n))


def _is_revenue_eligible(status: str, reason: str) -> bool:
    """Mirror of shared.revenue_reference.is_revenue_eligible: CANCELLED never
    contributes EXCEPT a rental interrupted after it started (maintenance) —
    then the days realised before the interruption are preserved."""
    status = (status or "").strip().upper()
    if not status:
        return False
    if status == "CANCELLED":
        return (reason or "").strip().upper() == "MAINTENANCE"
    return True


def _realised_for_row(r_get, start_dt: datetime, num_days: int, now: datetime) -> int:
    """Realised day count for a row, honouring COMPLETED (full) and
    maintenance-interrupted (capped at `cancelled_at`) — mirror of the spec."""
    status = str(r_get("status") or "").strip().upper()
    reason = str(r_get("cancellation_reason") or "").strip().upper()
    if status == "CANCELLED" and reason == "MAINTENANCE":
        cap_src = r_get("cancelled_at") or r_get("end_datetime")
        cap = _parse_dt(cap_src) if cap_src else None
        effective_now = min(now, _to_biz(cap)) if cap is not None else now
        return _realised_days(start_dt, num_days, effective_now)
    if status == "COMPLETED":
        return num_days
    return _realised_days(start_dt, num_days, now)


def _reservation_revenue(r_get, start_dt, from_d: date, to_d: date, now: datetime) -> Decimal:
    """Pro-rata Decimal contribution of ONE reservation to [from_d, to_d)."""
    num_days = int(r_get("num_days") or 0)
    if num_days <= 0 or start_dt is None:
        return Decimal("0")
    if not _is_revenue_eligible(r_get("status"), r_get("cancellation_reason")):
        return Decimal("0")
    start_dt = _to_biz(start_dt)
    realised = _realised_for_row(r_get, start_dt, num_days, now)
    if realised <= 0:
        return Decimal("0")
    total_price = r_get("total_price")
    if total_price is not None:
        per_day = Decimal(str(total_price)) / Decimal(num_days)
    else:
        per_day = Decimal(str(r_get("daily_price") or 0))
    sd = start_dt.date()
    lo = max(sd, from_d)
    hi = min(sd + timedelta(days=realised), to_d)
    days = (hi - lo).days
    return per_day * Decimal(days) if days > 0 else Decimal("0")


def _q2(d: Decimal) -> float:
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _now_biz(now=None) -> datetime:
    now = now or datetime.now(TZ)
    return now.astimezone(TZ) if now.tzinfo is not None else now.replace(tzinfo=TZ)


def _named_period_date_bounds(name: str, now: datetime):
    """(from_date, to_date) — to_date EXCLUSIVE — for a named preset, mirroring
    shared.money_time.period_bounds. Week starts Monday."""
    today = now.date()
    if name == "today":
        return today, today + timedelta(days=1)
    if name == "yesterday":
        return today - timedelta(days=1), today
    if name == "week":
        s = today - timedelta(days=today.weekday())
        return s, s + timedelta(days=7)
    if name == "last_week":
        tw = today - timedelta(days=today.weekday())
        return tw - timedelta(days=7), tw
    if name == "month":
        s = today.replace(day=1)
        e = date(s.year + 1, 1, 1) if s.month == 12 else date(s.year, s.month + 1, 1)
        return s, e
    if name == "last_month":
        tm = today.replace(day=1)
        return (tm - timedelta(days=1)).replace(day=1), tm
    if name == "year":
        return date(today.year, 1, 1), date(today.year + 1, 1, 1)
    if name == "last_year":
        return date(today.year - 1, 1, 1), date(today.year, 1, 1)
    raise ValueError(name)


def revenue_between_rows(reservation_rows, from_d: date, to_d: date, now=None):
    """PURE pro-rata revenue + realised rental-days for [from_d, to_d) (to
    exclusive). The ONE desktop revenue function — every card and the custom
    range call this."""
    from app.utils.fleet_status import _get

    now = _now_biz(now)
    acc = Decimal("0")
    days_total = 0
    for r in (reservation_rows or []):
        g = lambda k, _r=r: _get(_r, k)
        if not _is_revenue_eligible(g("status"), g("cancellation_reason")):
            continue
        start_dt = _parse_dt(_get(r, "start_datetime"))
        contrib = _reservation_revenue(g, start_dt, from_d, to_d, now)
        acc += contrib
        if start_dt is not None:
            sd = _to_biz(start_dt).date()
            nd = int(_get(r, "num_days") or 0)
            realised = _realised_for_row(g, _to_biz(start_dt), nd, now) if nd else 0
            lo = max(sd, from_d)
            hi = min(sd + timedelta(days=realised), to_d)
            days_total += max(0, (hi - lo).days)
    return _q2(acc), days_total


def _rentals_started(reservation_rows, from_d: date, to_d: date):
    from app.utils.fleet_status import _get
    n = 0
    for r in (reservation_rows or []):
        # Mirror shared.revenue_reference.rentals_started_between: a
        # maintenance-interrupted rental still "started" and still counts.
        if not _is_revenue_eligible(_get(r, "status"), _get(r, "cancellation_reason")):
            continue
        sdt = _parse_dt(_get(r, "start_datetime"))
        if sdt is not None and from_d <= _to_biz(sdt).date() < to_d:
            n += 1
    return n


def compute_overview_rows(reservation_rows, fleet_counts, maintenances=None, now=None):
    """PURE — dashboard overview (pro-rata revenue) from loaded reservation
    rows + a canonical fleet_counts dict. Recompute after local midnight
    rolls the cards with no SQLite read and no network."""
    from app.utils.fleet_status import _get
    now = _now_biz(now)
    rows = list(reservation_rows or [])
    maint_rows = list(maintenances or [])

    open_tickets = 0
    for m in maint_rows:
        mst = (_get(m, "status") or "").strip().upper()
        if mst not in ("COMPLETED", "CANCELLED"):
            open_tickets += 1

    today_start, today_end = _named_period_date_bounds("today", now)
    returns_today = 0
    for r in rows:
        rst = (_get(r, "status") or "").strip().upper()
        if rst in ("ACTIVE", "RESERVED"):
            end_dt = _parse_dt(_get(r, "end_datetime"))
            if end_dt:
                end_biz = _to_biz(end_dt)
                if today_start <= end_biz.date() < today_end:
                    returns_today += 1

    active_rentals = 0
    reserved_rentals = 0
    for r in rows:
        rst = (_get(r, "status") or "").strip().upper()
        s_dt = _parse_dt(_get(r, "start_datetime"))
        e_dt = _parse_dt(_get(r, "end_datetime"))
        if rst == "ACTIVE":
            active_rentals += 1
        elif rst == "RESERVED":
            if s_dt and e_dt:
                s_biz = _to_biz(s_dt)
                e_biz = _to_biz(e_dt)
                if s_biz <= now < e_biz:
                    active_rentals += 1
                elif s_biz > now:
                    reserved_rentals += 1
            elif s_dt and _to_biz(s_dt) > now:
                reserved_rentals += 1

    out = {
        "total_vehicles": fleet_counts["total_vehicles"],
        "available": fleet_counts["available"],
        "rented": fleet_counts["rented"],
        "reserved": fleet_counts["reserved"],
        "maintenance": fleet_counts["maintenance"],
        "active_maintenances": fleet_counts["maintenance"],
        "active_maintenance_tickets": open_tickets if maint_rows else fleet_counts["maintenance"],
        "active_rentals": active_rentals,
        "reserved_rentals": reserved_rentals,
        "today_returns": returns_today,
    }
    for key, name in (("today", "today"), ("week", "week"),
                      ("month", "month"), ("year", "year")):
        fd, td = _named_period_date_bounds(name, now)
        rev, _days = revenue_between_rows(rows, fd, td, now)
        out[f"{key}_rentals"] = _rentals_started(rows, fd, td)
        out[f"{key}_revenue"] = float(rev) if rev is not None else 0.0
    return out


def compute_top_vehicles_rows(reservation_rows, vehicle_rows, now=None, limit=5):
    """PURE — "Top N véhicules les plus loués" from already-loaded rows.

    CANONICAL — identical eligibility and ranking to backend
    ``RentalRepository.get_vehicle_stats``:
    1) rental_count DESC (most rented = rental count)
    2) realised_revenue DESC (pro-rata realised revenue)
    3) vehicle_id ASC (deterministic tiebreaker)
    """
    from app.utils.fleet_status import _get

    now = now or datetime.now(TZ)
    now = now.astimezone(TZ) if now.tzinfo is not None else now.replace(tzinfo=TZ)

    vmeta = {}
    for v in (vehicle_rows or []):
        vid = str(_get(v, "id") or _get(v, "vehicle_id") or "")
        if vid:
            vmeta[vid] = {
                "registration": _get(v, "registration") or "",
                "brand": _get(v, "brand") or "",
                "model": _get(v, "model") or "",
                "created_at": _get(v, "created_at"),
            }

    all_time_start = date(2000, 1, 1)
    all_time_end = date(9999, 12, 31)

    agg: dict[str, dict] = {}
    for r in (reservation_rows or []):
        if (_get(r, "status") or "").upper() == "CANCELLED":
            continue
        start_dt = _parse_dt(_get(r, "start_datetime"))
        if start_dt is None or start_dt > now:
            continue
        vid = str(_get(r, "vehicle_id") or "")
        if not vid:
            continue
        a = agg.setdefault(vid, {"vehicle_id": vid, "rental_count": 0,
                                 "total_days": 0, "total_revenue": 0.0,
                                 "last_rental": None, "reservations": []})
        a["rental_count"] += 1
        a["reservations"].append(r)
        
        # Realised revenue for this reservation:
        g = lambda k, _r=r: _get(_r, k)
        contrib = _reservation_revenue(g, start_dt, all_time_start, all_time_end, now)
        a["total_revenue"] += float(contrib)
        
        # Realised rental days:
        rst = (_get(r, "status") or "").strip().upper()
        if rst == "COMPLETED":
            a["total_days"] += int(_get(r, "num_days") or 0)
        else:
            nd = int(_get(r, "num_days") or 0)
            a["total_days"] += _realised_days(_to_biz(start_dt), nd, now) if nd else 0

        iso = start_dt.isoformat()
        if a["last_rental"] is None or iso > a["last_rental"]:
            a["last_rental"] = iso

    # Sort strictly by rental_count DESC, total_revenue DESC, vehicle_id ASC
    ranked = sorted(
        agg.values(),
        key=lambda x: (-x["rental_count"], -round(x["total_revenue"], 2), str(x["vehicle_id"]))
    )[:limit]
    from shared.utilization_reference import calculate_vehicle_utilization
    for a in ranked:
        a["total_revenue"] = round(a["total_revenue"], 2)
        meta = vmeta.get(a["vehicle_id"], {"registration": "", "brand": "", "model": "", "created_at": None})
        a["registration"] = meta.get("registration", "")
        a["brand"] = meta.get("brand", "")
        a["model"] = meta.get("model", "")
        c_at = meta.get("created_at")
        v_res = a.get("reservations", [])
        if c_at:
            _, _, _, util = calculate_vehicle_utilization(c_at, v_res, now)
            a["utilization_rate"] = util
        else:
            a["utilization_rate"] = 0.0
        a.pop("reservations", None)
    return ranked


def compute_local_top_vehicles(session=None, now=None, limit=5):
    """``compute_top_vehicles_rows`` fed from the local SQLite cache."""
    from app.database import get_local_session
    from app.models.reservation import LocalReservation
    from app.models.vehicle import LocalVehicle

    own_session = session is None
    if own_session:
        session = get_local_session()
    try:
        return compute_top_vehicles_rows(
            session.query(LocalReservation).all(),
            session.query(LocalVehicle).all(),
            now=now, limit=limit,
        )
    finally:
        if own_session:
            session.close()


def compute_local_overview(session=None, now=None):
    """Compute the dashboard overview from the local SQLite cache.

    Returns the same key structure as the backend /dashboard/stats mapping
    used by the UI. Revenue values are None when no cached reservations
    exist for that period (caller may fall back to last server value).
    """
    from app.database import get_local_session
    from app.models.reservation import LocalReservation
    from app.models.maintenance import LocalMaintenance
    from app.utils.fleet_status import compute_fleet_counts

    own_session = session is None
    if own_session:
        session = get_local_session()
    try:
        reservations = session.query(LocalReservation).all()
        maintenances = session.query(LocalMaintenance).all()
        fleet = compute_fleet_counts(session, now=now)
        return compute_overview_rows(reservations, fleet, maintenances=maintenances, now=now)
    finally:
        if own_session:
            session.close()
