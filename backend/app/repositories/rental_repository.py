"""
Rental repository — database operations for reservations/rentals.
"""
from typing import Optional
from uuid import UUID
from datetime import datetime
from datetime import timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, func, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reservation import Reservation
from app.models.vehicle import Vehicle
from app.repositories.base import BaseRepository
import logging

logger = logging.getLogger(__name__)


class RentalRepository(BaseRepository[Reservation]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Reservation)

    async def check_availability(
        self,
        vehicle_id: UUID,
        start_dt: datetime,
        end_dt: datetime,
        exclude_id: Optional[UUID] = None,
    ) -> tuple[bool, Optional[str]]:
        """Check if a vehicle is available for the given date range.
        Checks both reservations and maintenance schedules.
        Returns a tuple: (is_available, blocking_entity_type)"""
        from app.models.maintenance import Maintenance
        from sqlalchemy import func, or_, text
        
        # 1. Check Reservations
        query_res = (
            select(func.count(Reservation.id))
            .where(
                Reservation.vehicle_id == vehicle_id,
                Reservation.status.notin_(["CANCELLED", "COMPLETED"]),
                Reservation.start_datetime < end_dt,
                Reservation.end_datetime > start_dt,
            )
        )
        if exclude_id:
            query_res = query_res.where(Reservation.id != exclude_id)
        count_res = await self._session.scalar(query_res)
        
        if count_res and count_res > 0:
            return False, "RESERVATION"

        # 2. Check Maintenances
        # We need to coalesce expected_end_datetime, actual_end_datetime, or start_datetime
        query_maint = (
            select(func.count(Maintenance.id))
            .where(
                Maintenance.vehicle_id == vehicle_id,
                Maintenance.status.notin_(["CANCELLED", "COMPLETED"]),
                Maintenance.start_datetime < end_dt,
                func.coalesce(Maintenance.expected_end_datetime, Maintenance.actual_end_datetime, Maintenance.start_datetime) > start_dt
            )
        )
        count_maint = await self._session.scalar(query_maint)
        
        if count_maint and count_maint > 0:
            return False, "MAINTENANCE"
            
        return True, None

    async def get_by_vehicle(
        self,
        vehicle_id: UUID,
        include_cancelled: bool = False,
    ) -> list[Reservation]:
        """Get all rentals for a vehicle."""
        query = select(Reservation).where(Reservation.vehicle_id == vehicle_id)
        if not include_cancelled:
            query = query.where(Reservation.status != "CANCELLED")
        query = query.order_by(Reservation.start_datetime.desc())
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_active_rentals(self) -> list[Reservation]:
        """Get all currently active rentals."""
        result = await self._session.execute(
            select(Reservation)
            .where(Reservation.status.in_(["RESERVED", "ACTIVE"]))
            .order_by(Reservation.start_datetime)
        )
        return list(result.scalars().all())

    async def get_by_status(self, status: str) -> list[Reservation]:
        """Get rentals by status."""
        result = await self._session.execute(
            select(Reservation)
            .where(Reservation.status == status)
            .order_by(Reservation.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_today_rentals(self) -> list[Reservation]:
        """Get rentals starting today."""
        today_start = datetime.now(ZoneInfo('Africa/Casablanca')).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start.replace(hour=23, minute=59, second=59)
        result = await self._session.execute(
            select(Reservation)
            .where(
                Reservation.start_datetime >= today_start,
                Reservation.start_datetime <= today_end,
                Reservation.status != "CANCELLED",
            )
            .order_by(Reservation.start_datetime)
        )
        return list(result.scalars().all())

    async def get_today_returns(self) -> list[Reservation]:
        """Get rentals ending today."""
        today_start = datetime.now(ZoneInfo('Africa/Casablanca')).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start.replace(hour=23, minute=59, second=59)
        result = await self._session.execute(
            select(Reservation)
            .where(
                Reservation.end_datetime >= today_start,
                Reservation.end_datetime <= today_end,
                Reservation.status.in_(["ACTIVE", "COMPLETED"]),
            )
            .order_by(Reservation.end_datetime)
        )
        return list(result.scalars().all())

    async def count_by_status(self) -> dict[str, int]:
        """Count rentals grouped by status."""
        result = await self._session.execute(
            select(Reservation.status, func.count(Reservation.id))
            .group_by(Reservation.status)
        )
        return dict(result.all())

    async def get_revenue_between(
        self, start_dt: datetime, end_dt: datetime
    ) -> float:
        """Sum total_price for completed/active rentals in a period."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(Reservation.total_price), 0))
            .where(
                Reservation.status.in_(["ACTIVE", "COMPLETED"]),
                Reservation.start_datetime >= start_dt,
                Reservation.start_datetime < end_dt,
            )
        )
        return float(result.scalar())

    async def count_rentals_between(
        self, start_dt: datetime, end_dt: datetime
    ) -> int:
        """Count rentals in a period."""
        result = await self._session.execute(
            select(func.count(Reservation.id))
            .where(
                Reservation.status != "CANCELLED",
                Reservation.start_datetime >= start_dt,
                Reservation.start_datetime < end_dt,
            )
        )
        return result.scalar()

    async def sum_days_between(
        self, start_dt: datetime, end_dt: datetime
    ) -> int:
        """Sum rental days in a period."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(Reservation.num_days), 0))
            .where(
                Reservation.status != "CANCELLED",
                Reservation.start_datetime >= start_dt,
                Reservation.start_datetime < end_dt,
            )
        )
        return int(result.scalar())

    async def get_vehicle_stats(self) -> list[dict]:
        """Get per-vehicle performance stats."""
        result = await self._session.execute(
            select(
                Reservation.vehicle_id,
                func.count(Reservation.id).label("rental_count"),
                func.coalesce(func.sum(Reservation.num_days), 0).label("total_days"),
                func.coalesce(func.sum(Reservation.total_price), 0).label("total_revenue"),
                func.max(Reservation.start_datetime).label("last_rental"),
            )
            .where(Reservation.status.in_(["ACTIVE", "COMPLETED"]))
            .group_by(Reservation.vehicle_id)
            .order_by(func.sum(Reservation.total_price).desc())
        )
        rows = result.all()
        return [
            {
                "vehicle_id": str(r.vehicle_id),
                "rental_count": r.rental_count,
                "total_days": int(r.total_days),
                "total_revenue": float(r.total_revenue),
                "last_rental": r.last_rental.isoformat() if r.last_rental else None,
            }
            for r in rows
        ]
