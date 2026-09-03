"""
NORMATIVE SPECIFICATION — revenue (chiffre d'affaires) recognition.

This is the single authoritative definition of "how much revenue did we make
in period [from, to)". It is a pure function over primitive dicts (no ORM, no
DB, no network) so every runtime is tested against it byte-for-byte:

    backend/app/services/revenue_service.py   (async SQLAlchemy / SQL)  -> must match
    desktop/app/sync/dashboard_cache.py       (offline, sync)           -> must match
    mobile .../data/fleet/RevenueEngine.kt    (Kotlin, offline)         -> must match

Any divergence on a case in `shared/revenue_cases.json` fails the
cross-runtime parity tests. "The two apps show different CA" becomes a red
build, not a client phone call.

--------------------------------------------------------------------------
BUSINESS RULE — PRO-RATA BY DAY  (chosen 2026-09-02, replaces recognition-at-start)

A rental of `num_days` days, starting at instant S (business-local), is made
of day-slices  day i = [S + i days, S + (i+1) days)  for i in 0..num_days-1.
Day i is *booked against the calendar date* date(S) + i and earns exactly
`total_price / num_days` of revenue (using total_price/num_days keeps the
full-rental sum EXACTLY equal to the stored total_price — no rounding drift).

Day i is REALISED once it has begun: now >= S + i days. The count of realised
days is  clamp( floor((now - S) / 1 day) + 1 , 0 , num_days ).  A rental that
has not started (now < S) has 0 realised days; a fully-elapsed rental has
num_days.

Revenue recognised in reporting period [from_date, to_date) is the sum, over
every non-CANCELLED reservation, of the per-day rate times the number of the
rental's REALISED days whose calendar date falls inside [from_date, to_date).

CANCELLED reservations never contribute. A future booking contributes 0. A
rental spanning a period boundary is split: each period gets exactly its
days. Summing one rental over all time (with now past its end) == total_price.

INTERVAL RULE: [from_date, to_date) half-open, both are dates. The dashboard
"Au" date is inclusive in the UI and is converted to an exclusive `to_date`
by the caller (see shared.money_time.custom_bounds).
--------------------------------------------------------------------------
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

CANCELLED = "CANCELLED"
_BIZ_TZ = ZoneInfo("Africa/Casablanca")


ELIGIBLE_STATUSES = ("PENDING", "CONFIRMED", "RESERVED", "ACTIVE", "COMPLETED")


def is_revenue_eligible(res: dict) -> bool:
    """Return True if reservation is eligible to contribute revenue.

    CANCELLED reservations do not contribute UNLESS they were cancelled after start
    due to maintenance or interruption, in which case days realised prior to
    cancellation are preserved. All active, completed, or booked rentals
    (PENDING, CONFIRMED, RESERVED, ACTIVE, COMPLETED) are eligible,
    contributing pro-rata for their elapsed/realised days once started.
    """
    status = str(res.get("status", "")).strip().upper()
    if not status:
        return False
    if status == CANCELLED:
        reason = str(res.get("cancellation_reason", "")).strip().upper()
        if reason == "MAINTENANCE" or res.get("realised_revenue_preserved"):
            return True
        return False
    return True


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        s = str(value).replace("Z", "+00:00").replace("z", "+00:00")
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_BIZ_TZ)
    return dt.astimezone(_BIZ_TZ)


def _as_date(value) -> date:
    return _as_datetime(value).date()


def _realised_days(start_dt: datetime, num_days: int, now: datetime) -> int:
    elapsed = (now - start_dt).total_seconds() / 86400.0
    import math

    n = math.floor(elapsed) + 1
    if n < 0:
        n = 0
    if n > num_days:
        n = num_days
    return n


def _q2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _realised_day_dates(res: dict, now: datetime):
    """(per_day_rate: Decimal, first_date, count) for a reservation's realised
    days, or (0, None, 0) if it contributes nothing."""
    if not is_revenue_eligible(res):
        return Decimal("0"), None, 0
    num_days = int(res.get("num_days") or 0)
    if num_days <= 0:
        return Decimal("0"), None, 0

    start_dt = _as_datetime(res.get("start_datetime") or res.get("start_date"))
    start_d = start_dt.date()
    status = str(res.get("status") or "").strip().upper()
    reason = str(res.get("cancellation_reason") or "").strip().upper()

    if status == CANCELLED and (reason == "MAINTENANCE" or res.get("realised_revenue_preserved")):
        # Interrupted rental: only days elapsed prior to the interruption are realised.
        end_cap = _as_datetime(res.get("cancelled_at") or res.get("end_datetime")) if (res.get("cancelled_at") or res.get("end_datetime")) else None
        effective_now = min(now, end_cap) if end_cap else now
        realised = _realised_days(start_dt, num_days, effective_now)
    elif status == "COMPLETED":
        realised = num_days
    else:
        realised = _realised_days(start_dt, num_days, now)
    if realised <= 0:
        return Decimal("0"), None, 0

    total_price = res.get("total_price")
    if total_price is not None:
        per_day = Decimal(str(total_price)) / Decimal(num_days)
    else:
        per_day = Decimal(str(res.get("daily_price") or 0))
    return per_day, start_d, realised


def reservation_period_revenue(
    res: dict, from_date: date, to_date: date, now: datetime
) -> Decimal:
    """Pro-rata revenue a single reservation contributes to [from_date, to_date)."""
    per_day, start_d, realised = _realised_day_dates(res, now)
    if realised <= 0:
        return Decimal("0.00")
    lo = max(start_d, from_date)
    hi = min(start_d + timedelta(days=realised), to_date)
    days = (hi - lo).days
    if days <= 0:
        return Decimal("0.00")
    return per_day * Decimal(days)


def revenue_between(
    reservations: list[dict],
    from_date: date,
    to_date: date,
    now: datetime | None = None,
) -> float:
    """Total realised pro-rata revenue for [from_date, to_date) (`to` exclusive).

    `now` is the business-local instant used to decide which days have been
    realised. When omitted, the window is assumed fully in the past.
    """
    if now is None:
        now = datetime(to_date.year, to_date.month, to_date.day, tzinfo=_BIZ_TZ)
    acc = Decimal("0")
    for res in reservations:
        acc += reservation_period_revenue(res, from_date, to_date, now)
    return float(_q2(acc))


def rental_days_between(
    reservations: list[dict],
    from_date: date,
    to_date: date,
    now: datetime | None = None,
) -> int:
    """Realised rental-days in the window (the pro-rata companion to revenue)."""
    if now is None:
        now = datetime(to_date.year, to_date.month, to_date.day, tzinfo=_BIZ_TZ)
    total = 0
    for res in reservations:
        _pd, start_d, realised = _realised_day_dates(res, now)
        if realised <= 0:
            continue
        lo = max(start_d, from_date)
        hi = min(start_d + timedelta(days=realised), to_date)
        total += max(0, (hi - lo).days)
    return total


def rentals_started_between(
    reservations: list[dict], from_date: date, to_date: date
) -> int:
    """Count of non-cancelled reservations whose start date is in [from, to).

    Rental *count* stays anchored to the start date (a rental is "a rental
    made in September" by when it started), independent of the pro-rata
    revenue split.
    """
    n = 0
    for res in reservations:
        if not is_revenue_eligible(res):
            continue
        start_d = _as_date(res.get("start_date") or res.get("start_datetime"))
        if from_date <= start_d < to_date:
            n += 1
    return n
