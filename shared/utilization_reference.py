"""
Canonical reference for vehicle utilization rate calculation.
ATELIER BERLIN LOCATION CAR.

The utilization rate represents the actual physical fleet occupancy over the
vehicle's operational lifetime, without double-counting overlapping rental
intervals.

Formula:
    utilization_rate = (occupied_union_days / operational_days) * 100.0
where:
    operational_days = max(1, (now.date() - created_at.date()).days + 1)
    occupied_union_days = | U [s_i, s_i + realised_days_i) cap [created_at, now] |
"""
from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Sequence, Any, Optional
from decimal import Decimal
from zoneinfo import ZoneInfo

from shared.money_time import BUSINESS_TZ, to_business, now_business


def calculate_vehicle_utilization(
    vehicle_created_at: datetime | str | None,
    reservations: Sequence[Any],
    now: Optional[datetime] = None,
) -> tuple[int, int, float, float]:
    """Calculate overlap-safe physical vehicle utilization rate.

    Args:
        vehicle_created_at: When the vehicle entered the operational fleet.
        reservations: Iterable of Reservation models or dicts.
        now: Optional evaluation timestamp (defaults to now_business()).

    Returns:
        (operational_days, occupied_union_days, raw_percentage, final_percentage)
    """
    now = to_business(now) if now is not None else now_business()

    if vehicle_created_at is None:
        return 0, 0, 0.0, 0.0

    if isinstance(vehicle_created_at, str):
        try:
            vehicle_created_at = datetime.fromisoformat(vehicle_created_at)
        except Exception:
            return 0, 0, 0.0, 0.0

    created_biz = to_business(vehicle_created_at)
    created_d = created_biz.date()
    now_d = now.date()

    if created_d > now_d:
        return 1, 0, 0.0, 0.0

    operational_days = max(1, (now_d - created_d).days + 1)

    occupied_dates: set[date] = set()

    for r in reservations:
        st = (r.get("status") if isinstance(r, dict) else getattr(r, "status", "")) or ""
        st = st.strip().upper()
        if st == "CANCELLED":
            continue

        raw_s = r.get("start_datetime") if isinstance(r, dict) else getattr(r, "start_datetime", None)
        if raw_s is None:
            continue
        if isinstance(raw_s, str):
            try:
                s_dt = datetime.fromisoformat(raw_s)
            except Exception:
                continue
        else:
            s_dt = raw_s

        s_dt = to_business(s_dt)
        if s_dt > now:
            # Future unstarted reservations do not count toward historical/current utilization
            continue

        raw_nd = r.get("num_days") if isinstance(r, dict) else getattr(r, "num_days", 0)
        try:
            nd = int(raw_nd or 0)
        except (ValueError, TypeError):
            nd = 0

        if nd <= 0:
            continue

        if st == "COMPLETED":
            realised_d = nd
        else:
            elapsed_sec = (now - s_dt).total_seconds()
            realised_d = max(0, min(nd, int(elapsed_sec / 86400.0) + 1))

        sd = s_dt.date()
        for i in range(realised_d):
            day = sd + timedelta(days=i)
            # Clip to vehicle operational lifetime and up to now
            if created_d <= day <= now_d:
                occupied_dates.add(day)

    occupied_union_days = len(occupied_dates)
    raw_percentage = round((occupied_union_days / operational_days) * 100.0, 4)
    final_percentage = min(100.0, round((occupied_union_days / operational_days) * 100.0, 1))

    return operational_days, occupied_union_days, raw_percentage, final_percentage
