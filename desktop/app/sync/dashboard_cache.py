"""
Offline dashboard cache computation — mirrors the backend canonical rule.

CANONICAL RULE (identical to backend/app/repositories/rental_repository.py
and backend/app/services/dashboard_service.py):

    Revenue(period) = SUM(total_price)
                      WHERE status IN ('ACTIVE', 'COMPLETED')
                        AND start_datetime >= period_start
                        AND start_datetime <  period_end
    Period boundaries: Africa/Casablanca local midnight;
    week starts Monday; month = calendar month.

This module is used ONLY for the desktop offline snapshot from the SQLite
cache. When online, the canonical API result always overrides it.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import logging

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Africa/Casablanca")
REVENUE_STATUSES = ("ACTIVE", "COMPLETED")


def _parse_dt(value):
    if not value:
        return None
    from app.utils.datetime_utils import parse_datetime_utc
    return parse_datetime_utc(value)


def _period_bounds(now=None):
    now = now or datetime.now(TZ)
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


def compute_local_overview(session=None):
    """Compute the dashboard overview from the local SQLite cache.

    Returns the same key structure as the backend /dashboard/stats mapping
    used by the UI. Revenue values are None when no cached reservations
    exist for that period (caller may fall back to last server value).
    """
    from app.database import get_local_session
    from app.models.vehicle import LocalVehicle
    from app.models.reservation import LocalReservation
    from app.models.maintenance import LocalMaintenance

    own_session = session is None
    if own_session:
        session = get_local_session()
    try:
        (t0, t1), (w0, w1), (m0, m1) = _period_bounds()

        def in_period(dt, start, end):
            return dt is not None and start <= dt < end

        totals = {"today": [0, 0.0], "week": [0, 0.0], "month": [0, 0.0]}
        bounds = {"today": (t0, t1), "week": (w0, w1), "month": (m0, m1)}

        reservations = session.query(LocalReservation).all()
        for r in reservations:
            status = (r.status or "").upper()
            if status not in REVENUE_STATUSES:
                continue
            start_dt = _parse_dt(r.start_datetime)
            for period, (p0, p1) in bounds.items():
                if in_period(start_dt, p0, p1):
                    totals[period][0] += 1
                    totals[period][1] += float(r.total_price or 0)

        active_maintenances = (
            session.query(LocalMaintenance)
            .filter(LocalMaintenance.status == "ACTIVE")
            .count()
        )

        def count_status(status):
            return session.query(LocalVehicle).filter_by(status=status).count()

        available = count_status("AVAILABLE")
        rented = count_status("RENTED")
        reserved = count_status("RESERVED")
        maintenance = count_status("MAINTENANCE")

        return {
            "total_vehicles": available + rented + reserved + maintenance,
            "available": available,
            "rented": rented,
            "reserved": reserved,
            "maintenance": maintenance,
            "active_maintenances": active_maintenances,
            "today_rentals": totals["today"][0],
            "today_revenue": round(totals["today"][1], 2) if reservations else None,
            "week_rentals": totals["week"][0],
            "week_revenue": round(totals["week"][1], 2) if reservations else None,
            "month_rentals": totals["month"][0],
            "month_revenue": round(totals["month"][1], 2) if reservations else None,
        }
    finally:
        if own_session:
            session.close()
