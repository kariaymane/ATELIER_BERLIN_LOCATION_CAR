"""
Dashboard service — aggregated business statistics.

Revenue (chiffre d'affaires) for every period — the fixed daily/weekly/
monthly/yearly cards AND the custom `?from=&to=` range — is computed by the
ONE engine in `app.services.revenue_service` (pro-rata by day, normative
spec `shared/revenue_reference.py`). This module never sums prices itself.
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.rental_repository import RentalRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.revenue_service import revenue_between
from shared.money_time import BUSINESS_TZ, now_business, period_bounds
import logging

logger = logging.getLogger(__name__)


class DashboardService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._rental_repo = RentalRepository(session)
        self._vehicle_repo = VehicleRepository(session)
    async def get_overview(self) -> dict:
        """Main dashboard overview."""
        from sqlalchemy import select, func, or_
        from app.models.maintenance import Maintenance
        from app.models.reservation import Reservation
        from app.models.vehicle import Vehicle
        
        now = now_business()

        # CANONICAL fleet breakdown — one derivation, mutually exclusive,
        # provably sums to total_vehicles and matches per-vehicle
        # effective_status from /vehicles. See app/services/fleet_status.py.
        from app.services.fleet_status import compute_fleet_counts
        fleet = await compute_fleet_counts(self._session, now=now)
        total_vehicles = fleet["total_vehicles"]
        available = fleet["available"]
        reserved = fleet["reserved"]
        rented = fleet["rented"]
        maintenance = fleet["maintenance"]
        vehicle_counts = {
            "AVAILABLE": available,
            "RENTED": rented,
            "RESERVED": reserved,
            "MAINTENANCE": maintenance,
        }

        rental_counts = await self._rental_repo.count_by_status()

        # The dashboard shows ONE maintenance number everywhere: vehicles
        # currently occupied by maintenance (== the fleet card). No second,
        # differently-computed "open tickets" figure that could contradict it.
        active_maintenances = maintenance

        today_start, today_end = period_bounds("today", now)

        _today = await revenue_between(self._session, today_start, today_end, now=now)
        today_rentals = _today["rentals"]
        today_revenue = _today["revenue"]

        # today_returns: any real (non-cancelled) rental ending today. A
        # RESERVED reservation counts exactly like ACTIVE once it has covered
        # `now` — see app/services/fleet_status.py's time-derived rule.
        tr_res = await self._session.execute(
            select(func.count(Reservation.id)).where(
                Reservation.status != "CANCELLED",
                Reservation.end_datetime >= today_start,
                Reservation.end_datetime < today_end
            )
        )
        today_returns = tr_res.scalar() or 0

        _week = await revenue_between(self._session, *period_bounds("week", now), now=now)
        week_rentals = _week["rentals"]
        week_revenue = _week["revenue"]

        _month = await revenue_between(self._session, *period_bounds("month", now), now=now)
        month_rentals = _month["rentals"]
        month_revenue = _month["revenue"]

        # Year-to-date — same pro-rata engine, wider window.
        _year = await revenue_between(self._session, *period_bounds("year", now), now=now)
        year_rentals = _year["rentals"]
        year_revenue = _year["revenue"]

        return {
            "total_vehicles": total_vehicles,
            "available": vehicle_counts.get("AVAILABLE", 0),
            "reserved": vehicle_counts.get("RESERVED", 0),
            "rented": vehicle_counts.get("RENTED", 0),
            "maintenance": vehicle_counts.get("MAINTENANCE", 0),
            "active_rentals": rental_counts.get("ACTIVE", 0),
            "reserved_rentals": rental_counts.get("RESERVED", 0),
            "active_maintenance_tickets": active_maintenances,
            "today_rentals": today_rentals,
            "today_returns": today_returns,
            "today_revenue": today_revenue,
            "week_rentals": week_rentals,
            "week_revenue": week_revenue,
            "month_rentals": month_rentals,
            "month_revenue": month_revenue,
            "year_rentals": year_rentals,
            "year_revenue": year_revenue,
        }

    # Legacy endpoint period name -> canonical shared period name.
    _PERIOD_ALIAS = {
        "daily": "today",
        "weekly": "week",
        "monthly": "month",
        "yearly": "year",
        "today": "today",
        "yesterday": "yesterday",
        "week": "week",
        "last_week": "last_week",
        "month": "month",
        "last_month": "last_month",
        "year": "year",
        "last_year": "last_year",
    }

    async def get_period_stats(self, period: str) -> dict:
        """Stats for a named period. Accepts the legacy daily/weekly/monthly/
        yearly names and the canonical today/yesterday/week/last_week/month/
        last_month/year/last_year names. Revenue via the ONE pro-rata engine."""
        now = now_business()
        canonical = self._PERIOD_ALIAS.get(period, "today")
        start, end = period_bounds(canonical, now)

        r = await revenue_between(self._session, start, end, now=now)
        return {
            "period": period,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "from": r["from"],
            "to": r["to"],
            "rentals": r["rentals"],
            "days_rented": r["rental_days"],
            "revenue": r["revenue"],
        }

    async def get_revenue_range(
        self, from_date: date, to_date_inclusive: date
    ) -> dict:
        """Custom-range chiffre d'affaires. `to_date_inclusive` is the date the
        operator picked in the UI ('Au:') and counts in full — converted to an
        exclusive bound here. Same pro-rata engine as every fixed period."""
        from shared.money_time import custom_bounds

        now = now_business()
        start, end = custom_bounds(from_date, to_date_inclusive)
        r = await revenue_between(self._session, start, end, now=now)
        return {
            "period": "custom",
            "from": r["from"],
            "to": r["to"],
            "to_inclusive": to_date_inclusive.isoformat(),
            "rentals": r["rentals"],
            "days_rented": r["rental_days"],
            "revenue": r["revenue"],
            "generated_at": now.isoformat(),
        }

    async def get_vehicle_performance(self) -> list[dict]:
        """Get performance ranking for all vehicles."""
        stats = await self._rental_repo.get_vehicle_stats()

        # Enrich with vehicle info
        for stat in stats:
            from uuid import UUID
            vehicle = await self._vehicle_repo.get_by_id(UUID(stat["vehicle_id"]))
            if vehicle:
                stat["registration"] = vehicle.registration
                stat["brand"] = vehicle.brand
                stat["model"] = vehicle.model
                # Calculate utilization rate (days rented / days since first rental).
                # `last_rental` may be serialized from a naive OR an aware
                # datetime depending on how the column round-trips; normalise
                # BOTH sides to aware-UTC so the subtraction can never raise
                # "can't subtract offset-naive and offset-aware datetimes" — a
                # crash here 500s the whole endpoint and blanks the desktop
                # "Top 5 véhicules les plus loués" panel.
                if stat["last_rental"]:
                    first_rental_dt = datetime.fromisoformat(stat["last_rental"])
                    if first_rental_dt.tzinfo is None:
                        first_rental_dt = first_rental_dt.replace(tzinfo=timezone.utc)
                    now_utc = datetime.now(timezone.utc)
                    total_possible_days = max(
                        1, (now_utc - first_rental_dt.astimezone(timezone.utc)).days
                    )
                    stat["utilization_rate"] = round(
                        (stat["total_days"] / total_possible_days) * 100, 1
                    )
                else:
                    stat["utilization_rate"] = 0.0

        return stats
