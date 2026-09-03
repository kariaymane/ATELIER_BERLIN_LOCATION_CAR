"""
Revenue service — the ONE authoritative chiffre-d'affaires engine.

Business rule: PRO-RATA BY DAY. See the normative spec in
`shared/revenue_reference.py`. This service does the DB fetch and delegates
every arithmetic decision to that shared pure function, so the backend,
the desktop offline cache and the mobile offline engine compute byte-for-byte
identical numbers (enforced by the cross-runtime parity tests against
`shared/revenue_cases.json`).

`daily`/`weekly`/`monthly`/`yearly` and the custom `?from=&to=` range all
funnel through `revenue_between` — there is no second code path.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reservation import Reservation
from shared.money_time import BUSINESS_TZ, now_business, to_business
from shared.revenue_reference import (
    revenue_between as _spec_revenue,
    rental_days_between as _spec_days,
    rentals_started_between as _spec_started,
)


async def _load_candidate_reservations(
    session: AsyncSession, end_dt: datetime
) -> list[dict]:
    """Every non-cancelled reservation that could contribute to a window
    ending at `end_dt` — i.e. that started before the window closes.

    The exact per-day overlap + realised-day cap is applied in the shared
    spec, not here, so this filter only has to be a safe superset.
    """
    rows = (
        await session.execute(
            select(Reservation).where(
                (
                    (Reservation.status != "CANCELLED")
                    | (Reservation.cancellation_reason == "MAINTENANCE")
                ),
                Reservation.start_datetime < end_dt,
            )
        )
    ).scalars().all()

    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "status": r.status,
                "cancellation_reason": r.cancellation_reason,
                "start_datetime": to_business(r.start_datetime),
                "end_datetime": to_business(r.end_datetime) if r.end_datetime else None,
                "num_days": int(r.num_days or 0),
                "total_price": r.total_price,  # Decimal from NUMERIC — exact
                "daily_price": r.daily_price,
            }
        )
    return out


async def revenue_between(
    session: AsyncSession,
    start_dt: datetime,
    end_dt: datetime,
    now: datetime | None = None,
) -> dict:
    """Realised pro-rata revenue for the half-open window [start_dt, end_dt).

    Returns {"revenue", "rental_days", "rentals", "from", "to"} where
    `from`/`to` are ISO dates (`to` exclusive) and `rentals` counts
    reservations that STARTED in the window (count stays start-anchored).
    """
    now = to_business(now) if now is not None else now_business()
    from_date: date = to_business(start_dt).date()
    to_date: date = to_business(end_dt).date()

    reservations = await _load_candidate_reservations(session, end_dt)

    return {
        "revenue": _spec_revenue(reservations, from_date, to_date, now),
        "rental_days": _spec_days(reservations, from_date, to_date, now),
        "rentals": _spec_started(reservations, from_date, to_date),
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
    }
