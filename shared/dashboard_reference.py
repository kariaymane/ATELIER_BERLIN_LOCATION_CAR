"""
NORMATIVE SPECIFICATION — the Dashboard snapshot.

This is the single authoritative definition of every number the Dashboard
shows. It is a pure function over primitive row dicts (no ORM, no DB, no
network, no Qt) so that each runtime is a thin *port* that only supplies rows:

    backend/app/services/dashboard_snapshot.py   rows from PostgreSQL
    desktop/app/sync/dashboard_snapshot.py       rows from the DomainStore

Both call ``build_snapshot`` here. There is exactly ONE implementation of the
arithmetic, so "the desktop and the server show different numbers" is not a
bug that can be re-introduced by editing one side — there is only one side.

WHY THE SNAPSHOT IS BUILT ALL AT ONCE
-------------------------------------
Every figure is derived from ONE ``now`` and ONE set of rows. Before the
2026-09-05 rebuild the dashboard issued three HTTP calls at three instants
(stats / vehicle-performance / revenue) and then merged some server keys with
locally re-derived ones; cards could therefore describe different moments and
different data. Building the whole DTO in one pass makes that structurally
impossible.

------------------------------------------------------------------------
ROW CONTRACT  (datetimes may be ``datetime`` objects or ISO-8601 strings;
a value with no offset is business-local wall time — THE naive policy)

  vehicle       {"id", "status", "registration", "brand", "model"}
  reservation   {"id", "vehicle_id", "status", "cancellation_reason",
                 "cancelled_at", "start_datetime", "end_datetime",
                 "num_days", "total_price", "daily_price"}
  maintenance   {"id", "vehicle_id", "status", "start_datetime",
                 "expected_end_datetime", "actual_end_datetime"}

------------------------------------------------------------------------
KPI DEFINITIONS

  revenue.amount        shared.revenue_reference.revenue_between over the
                        selected period — PRO-RATA BY DAY, realised days only.
  revenue.rentals       rentals whose START date falls in the period.
  revenue.rental_days   realised rental-days inside the period.

  reservations_today.count / .starting_today
                        rentals that STARTED today (same eligibility as the
                        money, so both cards describe the same set).
  .ending_today         blocking rentals whose end date is today.
  .in_progress          blocking rentals whose window contains `now`.

  maintenance.active_tickets
                        maintenance ROWS that are open AND whose window
                        contains `now` — the same predicate the fleet
                        derivation uses.
  .vehicles_in_maintenance   distinct vehicles among those tickets.
  .open_tickets         all non-terminal rows (legacy figure, any date).

  vehicles.*            shared.fleet_status_reference — four mutually
                        exclusive buckets that partition the active fleet.

  top_vehicles          valid, already-started rentals per vehicle; ordered
                        rental_count DESC, revenue DESC, vehicle_id ASC.

VEHICLE STATUS PRECEDENCE (from shared/fleet_status_reference.py — a vehicle
is in exactly ONE bucket):

    SOLD / INACTIVE  >  MAINTENANCE  >  ACTIVE_RENTAL  >  RESERVED  >  READY

INVARIANTS checked before returning (reported in ``integrity``, logged on
violation, never silently returned as contradictory numbers):

  I1  every bucket count >= 0
  I2  ready_to_rent + active_rental + maintenance == vehicles.total
  I3  active fleet + structural == fleet size (nothing lost, nothing counted twice)
  I4  revenue.amount >= 0 and revenue.rental_days >= 0
  I5  top_vehicles ordered by rental_count DESC
------------------------------------------------------------------------
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from shared.money_time import (
    BUSINESS_TIMEZONE_NAME,
    custom_bounds,
    now_business,
    period_bounds,
    to_business,
)
from shared.fleet_status_reference import (
    EFFECTIVE_AVAILABLE,
    EFFECTIVE_MAINTENANCE,
    EFFECTIVE_RENTED,
    EFFECTIVE_RESERVED,
    STRUCTURAL_STATUSES,
    TERMINAL_MAINTENANCE_STATUSES,
    _maintenance_end,
    _parse,
    effective_statuses,
)
from shared.revenue_reference import (
    _realised_day_dates,
    is_revenue_eligible,
    rental_days_between,
    rentals_started_between,
    reservation_period_revenue,
    revenue_between,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
CURRENCY = "MAD"
TOP_VEHICLES_LIMIT = 5

# The window used for the all-time money column of "Top 5 les plus loués".
_ALL_TIME_START = date(2000, 1, 1)
_ALL_TIME_END = date(9999, 12, 31)

# What the desktop shows when the server is unreachable. Not a number.
SOURCE_SERVER = "server"
SOURCE_LOCAL = "local"


def resolve_period(
    period: str,
    now: datetime,
    custom_from: Optional[date] = None,
    custom_to_inclusive: Optional[date] = None,
) -> tuple[str, datetime, datetime]:
    """(canonical_name, start, end_exclusive) for a requested period.

    ``custom`` takes the operator's INCLUSIVE 'Au' date and converts it to the
    canonical half-open bound. Every other name must be one of
    ``shared.money_time.PERIOD_NAMES``; anything else raises ValueError (the
    API turns that into a 422 — an unknown period is never silently coerced
    into "today", which would show a plausible but wrong figure).
    """
    name = (period or "month").strip().lower()
    if name == "custom":
        if custom_from is None or custom_to_inclusive is None:
            raise ValueError("custom period requires both 'from' and 'to'")
        start, end = custom_bounds(custom_from, custom_to_inclusive)
        return "custom", start, end
    start, end = period_bounds(name, now)
    return name, start, end


def fleet_section(vehicles, reservations, maintenances, now) -> tuple[dict, dict]:
    """The four mutually exclusive buckets, straight from the fleet spec.

    Structural vehicles (SOLD / INACTIVE) are not part of the active fleet and
    are reported separately, so the four operational buckets partition exactly
    ``total``.
    """
    per_vehicle = effective_statuses(
        [{"id": v["id"], "status": v.get("status")} for v in vehicles],
        [
            {
                "vehicle_id": r["vehicle_id"],
                "status": r.get("status"),
                "start": r.get("start_datetime"),
                "end": r.get("end_datetime"),
            }
            for r in reservations
        ],
        [
            {
                "vehicle_id": m["vehicle_id"],
                "status": m.get("status"),
                "start": m.get("start_datetime"),
                "expected_end": m.get("expected_end_datetime"),
                "actual_end": m.get("actual_end_datetime"),
            }
            for m in maintenances
        ],
        now,
    )
    counts = {
        EFFECTIVE_AVAILABLE: 0,
        EFFECTIVE_RENTED: 0,
        EFFECTIVE_MAINTENANCE: 0,
    }
    structural = 0
    for st in per_vehicle.values():
        if st in counts:
            counts[st] += 1
        elif st == EFFECTIVE_RESERVED:
            # Vehicles with future reservations are ready to rent right now
            counts[EFFECTIVE_AVAILABLE] += 1
        elif st in STRUCTURAL_STATUSES:
            structural += 1
    return {
        "total": sum(counts.values()),
        "ready_to_rent": counts[EFFECTIVE_AVAILABLE],
        "active_rental": counts[EFFECTIVE_RENTED],
        "maintenance": counts[EFFECTIVE_MAINTENANCE],
        "excluded_structural": structural,
        "fleet_size": len(per_vehicle),
    }, per_vehicle


def reservations_today_section(reservations, now) -> dict:
    """"Réservations (Ce jour)" plus the two figures it is routinely confused
    with, so an operator can see which one they are looking at."""
    today_start, today_end = period_bounds("today", now)
    d0, d1 = today_start.date(), today_end.date()

    starting = rentals_started_between(reservations, d0, d1)
    ending = 0
    in_progress = 0
    for r in reservations:
        if (r.get("status") or "").strip().upper() not in ("RESERVED", "ACTIVE"):
            continue
        start_dt = _parse(r.get("start_datetime"))
        end_dt = _parse(r.get("end_datetime"))
        if end_dt is not None and d0 <= to_business(end_dt).date() < d1:
            ending += 1
        if start_dt is not None and end_dt is not None and start_dt <= _parse(now) < end_dt:
            in_progress += 1
    return {
        "count": starting,
        "starting_today": starting,
        "ending_today": ending,
        "in_progress": in_progress,
        "date": d0.isoformat(),
    }


def maintenance_section(maintenances, fleet, now) -> dict:
    """"Maintenances en cours".

    ``active_tickets`` uses the SAME active-maintenance condition as the fleet
    derivation (open AND window covers ``now``), so a ticket can never be
    "en cours" while its vehicle is not "en maintenance" on the fleet card.
    Two overlapping tickets on one car are two tickets but ONE vehicle.
    """
    now_utc = _parse(now)
    tickets = 0
    open_rows = 0
    vehicles_seen: set[str] = set()
    for m in maintenances:
        if (m.get("status") or "").strip().upper() in TERMINAL_MAINTENANCE_STATUSES:
            continue
        open_rows += 1
        start = _parse(m.get("start_datetime"))
        end = _maintenance_end({
            "actual_end": m.get("actual_end_datetime"),
            "expected_end": m.get("expected_end_datetime"),
        })
        if start is not None and start <= now_utc < end:
            tickets += 1
            vehicles_seen.add(str(m["vehicle_id"]))
    return {
        "active_tickets": tickets,
        "open_tickets": open_rows,
        "vehicles_in_maintenance": len(vehicles_seen),
        "fleet_maintenance_vehicles": fleet["maintenance"],
    }


def top_vehicles_section(vehicles, reservations, now, limit=TOP_VEHICLES_LIMIT) -> list[dict]:
    """"Top N véhicules les plus loués".

    METRIC: the number of VALID rental records per vehicle that have already
    started. "Valid" is ``is_revenue_eligible`` — the same predicate the money
    uses — so a row's rental_count and its revenue always describe the same
    rentals. Cancelled rentals are excluded; a rental cut short by maintenance
    did happen and counts (it also earned money).

    ORDER: rental_count DESC, revenue DESC, vehicle_id ASC. The revenue term
    only breaks ties between equal counts; vehicle_id makes the order total,
    so identical data always produces an identical ranking.
    """
    meta = {str(v["id"]): v for v in vehicles}
    now_biz = to_business(now)
    agg: dict[str, dict] = {}

    for r in reservations:
        if not is_revenue_eligible(r):
            continue
        start_dt = _parse(r.get("start_datetime"))
        if start_dt is None or start_dt > _parse(now):
            continue
        vid = str(r["vehicle_id"])
        a = agg.setdefault(vid, {
            "vehicle_id": vid, "rental_count": 0, "rental_days": 0,
            "revenue": Decimal("0.00"), "last_rental": None,
        })
        a["rental_count"] += 1
        a["revenue"] += reservation_period_revenue(r, _ALL_TIME_START, _ALL_TIME_END, now_biz)
        _rate, _first, realised = _realised_day_dates(r, now_biz)
        a["rental_days"] += max(0, realised)
        iso = to_business(start_dt).isoformat()
        if a["last_rental"] is None or iso > a["last_rental"]:
            a["last_rental"] = iso

    ranked = sorted(
        agg.values(),
        key=lambda a: (-a["rental_count"], -a["revenue"], a["vehicle_id"]),
    )[:limit]

    out = []
    for i, a in enumerate(ranked, start=1):
        m = meta.get(a["vehicle_id"], {})
        out.append({
            "rank": i,
            "vehicle_id": a["vehicle_id"],
            "registration": m.get("registration") or "",
            "brand": m.get("brand") or "",
            "model": m.get("model") or "",
            "rental_count": a["rental_count"],
            "rental_days": a["rental_days"],
            "revenue": float(a["revenue"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "last_rental": a["last_rental"],
        })
    return out


def _period_block(reservations, name: str, now: datetime) -> dict:
    """Revenue / rental count / realised days for one standing window."""
    s, e = period_bounds(name, now)
    d0, d1 = s.date(), e.date()
    return {
        "revenue": revenue_between(reservations, d0, d1, now),
        "rentals": rentals_started_between(reservations, d0, d1),
        "rental_days": rental_days_between(reservations, d0, d1, now),
        "period_start": d0.isoformat(),
        "period_end": d1.isoformat(),
    }


def validate(dto: dict) -> dict:
    """Check the dashboard invariants; return the ``integrity`` section.

    A violation is logged at ERROR with the offending numbers, so a broken
    derivation shows up in the log rather than only as two cards that
    disagree on an operator's screen.
    """
    v = dto["vehicles"]
    rev = dto["revenue"]
    violations: list[str] = []

    for key in ("total", "ready_to_rent", "active_rental", "maintenance"):
        if v[key] < 0:
            violations.append(f"vehicles.{key} is negative ({v[key]})")

    bucket_sum = v["ready_to_rent"] + v["active_rental"] + v["maintenance"]
    if bucket_sum != v["total"]:
        violations.append(
            "fleet does not reconcile: ready_to_rent+active_rental+"
            f"maintenance={bucket_sum} != total={v['total']}"
        )
    if v["total"] + v["excluded_structural"] != v["fleet_size"]:
        violations.append(
            f"active fleet {v['total']} + structural {v['excluded_structural']} "
            f"!= fleet size {v['fleet_size']}"
        )
    if rev["amount"] < 0:
        violations.append(f"revenue.amount is negative ({rev['amount']})")
    if rev["rental_days"] < 0:
        violations.append(f"revenue.rental_days is negative ({rev['rental_days']})")

    counts = [t["rental_count"] for t in dto["top_vehicles"]]
    if counts != sorted(counts, reverse=True):
        violations.append(f"top_vehicles not ordered by rental_count DESC: {counts}")

    if violations:
        logger.error(
            "DASHBOARD INVARIANT VIOLATION at %s: %s | vehicles=%s revenue=%s",
            dto.get("generated_at"), "; ".join(violations), v, rev,
        )
    return {"ok": not violations, "violations": violations}


def build_snapshot(
    vehicles,
    reservations,
    maintenances,
    period: str = "month",
    custom_from: Optional[date] = None,
    custom_to_inclusive: Optional[date] = None,
    now: Optional[datetime] = None,
    top_limit: int = TOP_VEHICLES_LIMIT,
    source: str = SOURCE_SERVER,
) -> dict:
    """THE dashboard DTO: one ``now``, one row set, every card.

    ``period`` scopes the REVENUE window only. The operational counters (fleet
    buckets, réservations du jour, maintenances en cours) always describe the
    CURRENT state — "how many cars are out" has no meaning "for last month",
    and silently re-scoping them by a historical revenue filter is exactly the
    confusion this contract exists to prevent.
    """
    now = to_business(now) if now is not None else now_business()
    name, start, end = resolve_period(period, now, custom_from, custom_to_inclusive)
    from_date, to_date = start.date(), end.date()

    fleet, _per_vehicle = fleet_section(vehicles, reservations, maintenances, now)

    dto = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "business_timezone": BUSINESS_TIMEZONE_NAME,
        "currency": CURRENCY,
        "source": source,
        "revenue": {
            "amount": revenue_between(reservations, from_date, to_date, now),
            "currency": CURRENCY,
            "period": name,
            "period_start": from_date.isoformat(),
            "period_end": to_date.isoformat(),                        # EXCLUSIVE
            "period_end_inclusive": (to_date - timedelta(days=1)).isoformat(),
            "period_start_at": start.isoformat(),
            "period_end_at": end.isoformat(),
            "rentals": rentals_started_between(reservations, from_date, to_date),
            "rental_days": rental_days_between(reservations, from_date, to_date, now),
        },
        # The four standing windows, computed in the SAME pass against the SAME
        # `now`. This is not a second snapshot: one instant, one row set, so a
        # consumer that shows "ce mois" next to "cette année" is still showing
        # one coherent picture. It is also what the legacy flat payload needs.
        "periods": {
            name: _period_block(reservations, name, now)
            for name in ("today", "week", "month", "year")
        },
        "reservations_today": reservations_today_section(reservations, now),
        "maintenance": maintenance_section(maintenances, fleet, now),
        "vehicles": fleet,
        "top_vehicles": top_vehicles_section(vehicles, reservations, now, top_limit),
    }
    dto["integrity"] = validate(dto)
    return dto


def legacy_overview(vehicles, reservations, maintenances, now=None) -> dict:
    """The historical ``/dashboard/stats`` flat shape (mobile + older desktop
    builds), derived from the same rows as ``build_snapshot`` so the two can
    never drift apart."""
    now = to_business(now) if now is not None else now_business()
    fleet, _pv = fleet_section(vehicles, reservations, maintenances, now)
    maint = maintenance_section(maintenances, fleet, now)
    today = reservations_today_section(reservations, now)
    now_utc = _parse(now)

    out = {
        "total_vehicles": fleet["total"],
        "available": fleet["ready_to_rent"],
        "rented": fleet["active_rental"],
        "maintenance": fleet["maintenance"],
        "active_rentals": today["in_progress"],
        "active_maintenance_tickets": maint["open_tickets"],
        "active_maintenances": maint["active_tickets"],
        "today_returns": today["ending_today"],
    }
    for key in ("today", "week", "month", "year"):
        block = _period_block(reservations, key, now)
        out[f"{key}_rentals"] = block["rentals"]
        out[f"{key}_revenue"] = block["revenue"]
    return out
