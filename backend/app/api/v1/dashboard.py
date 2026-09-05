"""
Dashboard & statistics API endpoints.
"""
from datetime import date

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_perm
from app.auth.rbac import Permission
from app.services.dashboard_service import DashboardService
from app.services.dashboard_snapshot import (
    build_dashboard_snapshot,
    build_legacy_overview,
)
from app.services.rental_service import RentalService
from app.repositories.vehicle_repository import VehicleRepository
from shared.money_time import PERIOD_NAMES
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary")
async def dashboard_summary(
    period: str = Query(
        "month",
        description="Revenue window: today | yesterday | week | last_week | month | "
                    "last_month | year | last_year | custom",
    ),
    from_: date | None = Query(
        None, alias="from", description="Custom range start (ISO date, inclusive)"
    ),
    to: date | None = Query(
        None, description="Custom range end (ISO date, INCLUSIVE — the operator's 'Au')"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """THE dashboard endpoint — one coherent snapshot for every card.

    Revenue, réservations du jour, maintenances en cours, the four fleet
    buckets and the Top-5 are all computed from ONE database read set against
    ONE ``now``, so no two cards can describe different instants. ``period``
    scopes the REVENUE window only; the operational counters always describe
    the current state.
    """
    try:
        return await build_dashboard_snapshot(
            db, period=period, custom_from=from_, custom_to_inclusive=to
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/stats")
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """Legacy dashboard overview.

    Kept for the mobile app and older desktop builds; it is a pure projection
    of the SAME snapshot the new ``/summary`` endpoint returns, so the two
    shapes cannot drift apart.
    """
    return await build_legacy_overview(db)


@router.get("/daily")
async def daily_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """Today's statistics."""
    service = DashboardService(db)
    return await service.get_period_stats("daily")


@router.get("/weekly")
async def weekly_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """This week's statistics."""
    service = DashboardService(db)
    return await service.get_period_stats("weekly")


@router.get("/monthly")
async def monthly_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """This month's statistics."""
    service = DashboardService(db)
    return await service.get_period_stats("monthly")


@router.get("/yearly")
async def yearly_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """This year's statistics."""
    service = DashboardService(db)
    return await service.get_period_stats("yearly")


@router.get("/revenue")
async def revenue_range(
    from_: date = Query(..., alias="from", description="ISO date YYYY-MM-DD, inclusive"),
    to: date = Query(..., description="ISO date YYYY-MM-DD, inclusive (the picked 'Au' date counts in full)"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """Chiffre d'affaires for an arbitrary date range (pro-rata by day).

    `from`/`to` are ISO dates in the business timezone; `to` is INCLUSIVE
    (the operator's 'Au:' date counts fully). One engine, same as every card.
    """
    service = DashboardService(db)
    return await service.get_revenue_range(from_, to)


@router.get("/period/{name}")
async def period_stats_named(
    name: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """Stats for a named preset period: today, yesterday, week, last_week,
    month, last_month, year, last_year."""
    if name not in PERIOD_NAMES:
        raise HTTPException(status_code=422, detail=f"unknown period '{name}'")
    service = DashboardService(db)
    return await service.get_period_stats(name)


@router.get("/vehicle-performance")
async def vehicle_performance(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """Vehicle performance ranking."""
    service = DashboardService(db)
    return await service.get_vehicle_performance()
