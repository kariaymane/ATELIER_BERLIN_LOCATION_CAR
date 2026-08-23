"""
API v1 router — aggregates all sub-routers.
"""
from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.vehicles import router as vehicles_router
from app.api.v1.rentals import router as rentals_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.users import router as users_router
from app.api.v1.sync import router as sync_router
from app.api.v1.maintenance import router as maintenance_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.events import router as events_router
from app.api.v1.clients import router as clients_router

router = APIRouter(prefix="/api/v1")

router.include_router(auth_router)
router.include_router(vehicles_router)
router.include_router(rentals_router)
router.include_router(clients_router)
router.include_router(dashboard_router)
router.include_router(users_router)
router.include_router(sync_router)
router.include_router(maintenance_router)
router.include_router(notifications_router)
router.include_router(events_router)
