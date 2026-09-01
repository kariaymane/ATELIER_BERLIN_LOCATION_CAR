"""
Offline dashboard cache computation — mirrors the backend canonical rule.

CANONICAL RULE (identical to backend/app/repositories/rental_repository.py
and backend/app/services/dashboard_service.py):

    Revenue(period) = SUM(total_price)
                      WHERE status != 'CANCELLED'
                        AND start_datetime <= now           (rental has started)
                        AND start_datetime >= period_start
                        AND start_datetime <  period_end
    Period boundaries: Africa/Casablanca local midnight;
    week starts Monday; month = calendar month.

Revenue is recognised when a rental STARTS. A cancelled rental never counts;
a booking that has not started yet contributes nothing to current revenue but
is still counted under the "réservations" cards. This mirrors the fleet rule:
a car whose reservation window contains `now` is RENTED and its revenue is
recognised.

This module is used ONLY for the desktop offline snapshot from the SQLite
cache. When online, the canonical API result always overrides it.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import logging

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Africa/Casablanca")
# Revenue counts every reservation that is not CANCELLED (and has started).
NON_REVENUE_STATUSES = ("CANCELLED",)


def _parse_dt(value):
    if not value:
        return None
    from app.utils.datetime_utils import parse_datetime_utc
    return parse_datetime_utc(value)


def _period_bounds(now=None):
    now = now or datetime.now(TZ)
    now = now.astimezone(TZ) if now.tzinfo is not None else now.replace(tzinfo=TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(weeks=1)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        month_end = month_start.replace(year=now.year + 1, month=1)
    else:
        month_end = month_start.replace(month=now.month + 1)
    return (today_start, today_end), (week_start, week_end), (month_start, month_end)


def compute_overview_rows(reservation_rows, fleet_counts, now=None):
    """PURE — the dashboard overview from already-loaded reservation rows
    (dicts or ORM objects) + a canonical ``fleet_counts`` dict, evaluated
    against ``now``. The period (today/week/month) buckets use
    Africa/Casablanca local midnight, so a recompute after local midnight
    rolls the revenue / rental cards with NO SQLite read and NO network.
    """
    from app.utils.fleet_status import _get  # dict-or-ORM accessor

    now = now or datetime.now(TZ)
    now = now.astimezone(TZ) if now.tzinfo is not None else now.replace(tzinfo=TZ)
    (t0, t1), (w0, w1), (m0, m1) = _period_bounds(now)

    def in_period(dt, start, end):
        # all three are timezone-aware -> Python compares absolute instants
        return dt is not None and start <= dt < end

    totals_revenue = {"today": 0.0, "week": 0.0, "month": 0.0}
    totals_rentals = {"today": 0, "week": 0, "month": 0}
    bounds = {"today": (t0, t1), "week": (w0, w1), "month": (m0, m1)}

    rows = list(reservation_rows)
    for r in rows:
        status = (_get(r, "status") or "").upper()
        if status == "CANCELLED":
            continue
        start_dt = _parse_dt(_get(r, "start_datetime"))
        has_started = start_dt is not None and start_dt <= now
        for period, (p0, p1) in bounds.items():
            if in_period(start_dt, p0, p1):
                totals_rentals[period] += 1
                if has_started:
                    totals_revenue[period] += float(_get(r, "total_price") or 0)

    return {
        "total_vehicles": fleet_counts["total_vehicles"],
        "available": fleet_counts["available"],
        "rented": fleet_counts["rented"],
        "reserved": fleet_counts["reserved"],
        "maintenance": fleet_counts["maintenance"],
        "active_maintenances": fleet_counts["maintenance"],
        "today_rentals": totals_rentals["today"],
        "today_revenue": round(totals_revenue["today"], 2) if rows else None,
        "week_rentals": totals_rentals["week"],
        "week_revenue": round(totals_revenue["week"], 2) if rows else None,
        "month_rentals": totals_rentals["month"],
        "month_revenue": round(totals_revenue["month"], 2) if rows else None,
    }


def compute_local_overview(session=None, now=None):
    """Compute the dashboard overview from the local SQLite cache.

    Returns the same key structure as the backend /dashboard/stats mapping
    used by the UI. Revenue values are None when no cached reservations
    exist for that period (caller may fall back to last server value).
    """
    from app.database import get_local_session
    from app.models.reservation import LocalReservation
    from app.utils.fleet_status import compute_fleet_counts

    own_session = session is None
    if own_session:
        session = get_local_session()
    try:
        reservations = session.query(LocalReservation).all()
        fleet = compute_fleet_counts(session, now=now)
        return compute_overview_rows(reservations, fleet, now=now)
    finally:
        if own_session:
            session.close()
