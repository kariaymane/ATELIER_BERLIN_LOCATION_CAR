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
        """The legacy flat overview.

        Delegates to the ONE dashboard computation
        (``shared/dashboard_reference``) via ``build_legacy_overview`` — this
        method used to run its own queries and its own period loop, which is
        how the legacy payload drifted away from the numbers the newer
        endpoints returned. It is now a projection, not a second calculation.
        """
        from app.services.dashboard_snapshot import build_legacy_overview
        return await build_legacy_overview(self._session)

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

        from shared.utilization_reference import calculate_vehicle_utilization
        from shared.money_time import now_business

        now_biz = now_business()

        # Enrich with vehicle info
        for stat in stats:
            from uuid import UUID
            vehicle = await self._vehicle_repo.get_by_id(UUID(stat["vehicle_id"]))
            if vehicle:
                stat["registration"] = vehicle.registration
                stat["brand"] = vehicle.brand
                stat["model"] = vehicle.model
                created_dt = vehicle.created_at
                if created_dt:
                    v_res = stat.get("reservations", [])
                    _, _, raw_pct, final_pct = calculate_vehicle_utilization(created_dt, v_res, now_biz)
                    stat["utilization_rate"] = final_pct
                else:
                    stat["utilization_rate"] = 0.0
            else:
                stat["utilization_rate"] = 0.0

            stat.pop("reservations", None)

        return stats
