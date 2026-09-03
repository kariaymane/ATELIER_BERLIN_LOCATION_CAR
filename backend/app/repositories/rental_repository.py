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
        Checks base vehicle status, reservations, and maintenance schedules.
        Returns a tuple: (is_available, blocking_entity_type)"""
        from app.models.maintenance import Maintenance
        from sqlalchemy import func, or_, text
        
        # 0. Check structural Vehicle status only. MAINTENANCE is NOT checked
        # here — it is a transient, schedule-derived hold enforced by step 2
        # below. Treating a persisted MAINTENANCE flag as a hard block risks a
        # stale flag making the vehicle permanently unbookable.
        v_status = await self._session.scalar(
            select(Vehicle.status).where(Vehicle.id == vehicle_id)
        )
        if v_status in ["SOLD", "INACTIVE"]:
            return False, v_status

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

        # 2. Check Maintenances.
        # CANONICAL: an active maintenance ticket occupies its vehicle from
        # start_datetime until it is closed. No explicit end => open-ended:
        # effective_end = COALESCE(actual_end, expected_end, +infinity).
        from app.services.fleet_status import FAR_FUTURE
        from sqlalchemy import literal
        query_maint = (
            select(func.count(Maintenance.id))
            .where(
                Maintenance.vehicle_id == vehicle_id,
                Maintenance.status.notin_(["CANCELLED", "COMPLETED"]),
                Maintenance.start_datetime < end_dt,
                func.coalesce(
                    Maintenance.actual_end_datetime,
                    Maintenance.expected_end_datetime,
                    literal(FAR_FUTURE),
                ) > start_dt,
            )
        )
        count_maint = await self._session.scalar(query_maint)
        
        if count_maint and count_maint > 0:
            return False, "MAINTENANCE"
            
        return True, None

    async def cancel_overlapping_reservations(
        self,
        vehicle_id: UUID,
        maint_start: datetime,
        maint_end: Optional[datetime],
        reason: str = "MAINTENANCE",
    ) -> list[Reservation]:
        """Cancel every blocking reservation that overlaps a maintenance period.

        Canonical rule: maintenance wins. A reservation whose status is
        RESERVED or ACTIVE and whose interval overlaps ``[maint_start,
        maint_end)`` for the same vehicle is moved to CANCELLED with
        ``cancellation_reason = reason``. COMPLETED / already-CANCELLED
        reservations are never touched.

        Overlap predicate is the project canonical half-open rule
        (``start < end`` boundary does NOT overlap), identical to
        :meth:`check_availability`. Rows are locked FOR UPDATE so concurrent
        maintenance writers serialise on them.

        Returns the list of reservations that were cancelled (empty if none).
        Caller is responsible for audit entries / event broadcasts / commit.
        """
        # CANONICAL: an active maintenance with no explicit end is open-ended —
        # it occupies the vehicle until closed. Callers pass maint_end=None for
        # that case; treat it as the far future.
        from app.services.fleet_status import FAR_FUTURE
        if maint_end is None:
            maint_end = FAR_FUTURE
        if maint_end <= maint_start:
            return []

        query = (
            select(Reservation)
            .where(
                Reservation.vehicle_id == vehicle_id,
                Reservation.status.in_(["RESERVED", "ACTIVE"]),
                Reservation.start_datetime < maint_end,
                Reservation.end_datetime > maint_start,
            )
        )
        # SQLite (tests) does not support SELECT ... FOR UPDATE.
        try:
            dialect_name = self._session.get_bind().dialect.name
        except Exception:
            dialect_name = ""
        if dialect_name == "postgresql":
            query = query.with_for_update()

        result = await self._session.execute(query)
        affected = list(result.scalars().all())
        for res in affected:
            res.status = "CANCELLED"
            res.cancellation_reason = reason
            res.version += 1
        if affected:
            await self._session.flush()
        return affected

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
        """Get rentals ending today. A pending return due today is any active or
        reserved reservation ending today (COMPLETED and CANCELLED excluded)."""
        today_start = datetime.now(ZoneInfo('Africa/Casablanca')).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start.replace(hour=23, minute=59, second=59)
        result = await self._session.execute(
            select(Reservation)
            .where(
                Reservation.end_datetime >= today_start,
                Reservation.end_datetime <= today_end,
                Reservation.status.in_(["ACTIVE", "RESERVED"]),
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
        self, start_dt: datetime, end_dt: datetime, now: Optional[datetime] = None
    ) -> float:
        """Realised pro-rata revenue for [start_dt, end_dt) via the canonical engine."""
        from app.services.revenue_service import revenue_between
        res = await revenue_between(self._session, start_dt, end_dt, now=now)
        return float(res["revenue"])

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

    async def get_vehicle_stats(self, now: Optional[datetime] = None) -> list[dict]:
        """Get per-vehicle performance stats. Canonical ranking:
        1) rental_count DESC (most rented = rental count)
        2) realised_revenue DESC (canonical pro-rata realised revenue)
        3) vehicle_id ASC (deterministic tiebreaker)
        """
        from datetime import date
        from shared.revenue_reference import reservation_period_revenue, _realised_days
        from shared.money_time import now_business, to_business
        from decimal import Decimal, ROUND_HALF_UP

        now = to_business(now) if now is not None else now_business()
        result = await self._session.execute(
            select(Reservation).where(
                Reservation.status != "CANCELLED",
                Reservation.start_datetime <= now,
            )
        )
        reservations = result.scalars().all()

        all_time_start = date(2000, 1, 1)
        all_time_end = date(9999, 12, 31)

        agg: dict[str, dict] = {}
        for r in reservations:
            vid = str(r.vehicle_id)
            a = agg.setdefault(vid, {
                "vehicle_id": vid,
                "rental_count": 0,
                "total_days": 0,
                "total_revenue": Decimal("0.00"),
                "last_rental": None,
                "first_rental": None,
                "reservations": [],
            })
            a["rental_count"] += 1
            a["reservations"].append(r)

            r_dict = {
                "status": r.status,
                "start_datetime": to_business(r.start_datetime),
                "num_days": int(r.num_days or 0),
                "total_price": r.total_price,
                "daily_price": r.daily_price,
            }
            rev = reservation_period_revenue(r_dict, all_time_start, all_time_end, now)
            a["total_revenue"] += rev

            st = (r.status or "").strip().upper()
            if st == "COMPLETED":
                realised_d = int(r.num_days or 0)
            else:
                realised_d = _realised_days(to_business(r.start_datetime), int(r.num_days or 0), now)
            a["total_days"] += realised_d

            start_iso = to_business(r.start_datetime).isoformat()
            if a["last_rental"] is None or start_iso > a["last_rental"]:
                a["last_rental"] = start_iso
            if a["first_rental"] is None or start_iso < a["first_rental"]:
                a["first_rental"] = start_iso

        ranked = sorted(
            agg.values(),
            key=lambda x: (-x["rental_count"], -x["total_revenue"], str(x["vehicle_id"]))
        )
        return [
            {
                "vehicle_id": a["vehicle_id"],
                "rental_count": a["rental_count"],
                "total_days": a["total_days"],
                "total_revenue": float(a["total_revenue"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "last_rental": a["last_rental"],
                "first_rental": a["first_rental"],
                "reservations": a["reservations"],
            }
            for a in ranked
        ]
