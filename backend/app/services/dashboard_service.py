"""
Dashboard service — aggregated business statistics.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.rental_repository import RentalRepository
from app.repositories.vehicle_repository import VehicleRepository
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
        
        now = datetime.now(ZoneInfo('Africa/Casablanca'))

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

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        today_rentals = await self._rental_repo.count_rentals_between(today_start, today_end)
        today_revenue = await self._rental_repo.get_revenue_between(today_start, today_end, now=now)
        
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

        week_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        week_end = week_start + timedelta(weeks=1)
        week_rentals = await self._rental_repo.count_rentals_between(week_start, week_end)
        week_revenue = await self._rental_repo.get_revenue_between(week_start, week_end, now=now)

        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            month_end = month_start.replace(year=now.year + 1, month=1)
        else:
            month_end = month_start.replace(month=now.month + 1)
        month_rentals = await self._rental_repo.count_rentals_between(month_start, month_end)
        month_revenue = await self._rental_repo.get_revenue_between(month_start, month_end, now=now)

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
        }

    async def get_period_stats(self, period: str) -> dict:
        """Get stats for a specific period: daily, weekly, monthly, yearly."""
        now = datetime.now(ZoneInfo('Africa/Casablanca'))

        if period == "daily":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif period == "weekly":
            start = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            end = start + timedelta(weeks=1)
        elif period == "monthly":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if now.month == 12:
                end = start.replace(year=now.year + 1, month=1)
            else:
                end = start.replace(month=now.month + 1)
        elif period == "yearly":
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = start.replace(year=now.year + 1)
        else:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)

        rentals = await self._rental_repo.count_rentals_between(start, end)
        days = await self._rental_repo.sum_days_between(start, end)
        revenue = await self._rental_repo.get_revenue_between(start, end, now=now)

        return {
            "period": period,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "rentals": rentals,
            "days_rented": days,
            "revenue": revenue,
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
                # Calculate utilization rate (days rented / days since first rental)
                if stat["last_rental"]:
                    first_rental_dt = datetime.fromisoformat(stat["last_rental"])
                    total_possible_days = max(
                        1, (datetime.now(ZoneInfo('Africa/Casablanca')) - first_rental_dt).days
                    )
                    stat["utilization_rate"] = round(
                        (stat["total_days"] / total_possible_days) * 100, 1
                    )
                else:
                    stat["utilization_rate"] = 0.0

        return stats
