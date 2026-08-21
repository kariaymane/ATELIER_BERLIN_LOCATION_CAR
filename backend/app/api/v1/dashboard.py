"""
Dashboard & statistics API endpoints.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_perm
from app.auth.rbac import Permission
from app.services.dashboard_service import DashboardService
from app.services.rental_service import RentalService
from app.repositories.vehicle_repository import VehicleRepository
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """Main dashboard overview with key metrics."""
    service = DashboardService(db)
    return await service.get_overview()


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


@router.get("/vehicle-performance")
async def vehicle_performance(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """Vehicle performance ranking."""
    service = DashboardService(db)
    return await service.get_vehicle_performance()
