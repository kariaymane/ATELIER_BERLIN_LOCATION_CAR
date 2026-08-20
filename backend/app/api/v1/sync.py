"""
Sync API endpoints for offline-first Desktop synchronization and ATELIER BERLIN LOCATION CAR Mobile bootstrap.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database import get_db
from app.dependencies import get_current_user, require_perm, get_language
from app.auth.rbac import Permission
from app.schemas.sync import (
    SyncPushRequest, SyncPushResponse,
    SyncPullRequest, SyncPullResponse,
    SyncBootstrapResponse, SyncHealthResponse,
)
from app.services.sync_service import SyncService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["Synchronization"])


@router.get("/health", response_model=SyncHealthResponse)
async def sync_health():
    """
    Lightweight health check endpoint for mobile and desktop connection verification.
    """
    return SyncHealthResponse(
        status="healthy",
        version="1.0.0",
        api_version="1.0.0",
        server_id="car-rental-server-v1",
    )


@router.get("/bootstrap", response_model=SyncBootstrapResponse)
async def sync_bootstrap(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.SYNC_PULL)),
):
    """
    Authoritative initial snapshot for ATELIER BERLIN LOCATION CAR Mobile & Desktop bootstrap.
    Returns all vehicles, reservations, maintenance, and notifications.
    """
    service = SyncService(db)
    user_id = UUID(current_user["sub"]) if "sub" in current_user else None
    result = await service.get_bootstrap(user_id=user_id)
    return SyncBootstrapResponse(**result)


@router.post("/push", response_model=SyncPushResponse)
async def sync_push(
    body: SyncPushRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.SYNC_PUSH)),
    lang: str = Depends(get_language),
):
    """
    Push local Desktop changes to the server.
    Each item includes an idempotency key for safe retries.
    """
    try:
        service = SyncService(db)
        results = await service.process_push(
            items=body.items,
            user_id=UUID(current_user["sub"]),
            lang=lang,
        )
        await db.commit()

        # Broadcast real-time events for all successfully committed sync items
        from app.services.event_broadcaster import broadcaster
        for item, res in zip(body.items, results):
            if res.get("status") == "ok":
                etype = item.entity_type.lower()
                op = item.operation.upper()
                if op == "CREATE":
                    event_name = f"{etype.upper()}_CREATED"
                elif op == "DELETE":
                    event_name = f"{etype.upper()}_DELETED"
                else:
                    event_name = f"{etype.upper()}_UPDATED"

                v_id = str(item.payload.get("vehicle_id") or item.entity_id) if etype in ["vehicle", "reservation", "maintenance"] else None
                await broadcaster.broadcast_event(
                    event_type=event_name,
                    entity_type=etype,
                    entity_id=str(item.entity_id),
                    message=f"Sync {op} for {etype} ({item.entity_id}) from {item.device_id or 'Desktop'}.",
                    origin=item.device_id or "Desktop",
                    vehicle_id=v_id,
                    data=item.payload or {}
                )

        return SyncPushResponse(results=results)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise


@router.post("/pull", response_model=SyncPullResponse)
async def sync_pull(
    body: SyncPullRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.SYNC_PULL)),
    lang: str = Depends(get_language),
):
    """
    Pull server changes since a given timestamp.
    Desktop merges these with its local SQLite.
    """
    service = SyncService(db)
    result = await service.process_pull(
        since=body.since,
        entity_types=body.entity_types,
        device_id=body.device_id,
        user_id=UUID(current_user["sub"]),
        lang=lang,
    )
    return SyncPullResponse(**result)
