"""
Notification API router — provides endpoints for alerts and document monitoring.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database import get_db
from app.dependencies import require_perm
from app.auth.rbac import Permission
from app.schemas.notification import (
    NotificationListResponse, NotificationResponse, UnreadCountResponse
)
from app.services.notification_service import NotificationService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", include_in_schema=False, response_model=NotificationListResponse)
@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    unread_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """List system notifications with pagination and unread filter."""
    service = NotificationService(db)
    result = await service.list_notifications(
        page=page,
        page_size=page_size,
        unread_only=unread_only,
    )
    return NotificationListResponse(**result)


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """Get the current count of unread notifications."""
    service = NotificationService(db)
    count = await service.get_unread_count()
    return UnreadCountResponse(unread_count=count)


@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """Mark a notification as read."""
    service = NotificationService(db)
    success = await service.mark_as_read(notification_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification introuvable.",
        )
    return {"status": "ok", "message": "Notification marquée comme lue."}


@router.post("/mark-all-read")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """Mark all notifications as read."""
    service = NotificationService(db)
    updated = await service.mark_all_read()
    return {"status": "ok", "updated_count": updated}


@router.post("/scan")
async def scan_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """Manually trigger a check for document and maintenance expirations."""
    service = NotificationService(db)
    count = await service.scan_and_generate_notifications()
    return {"status": "ok", "new_notifications": count}
