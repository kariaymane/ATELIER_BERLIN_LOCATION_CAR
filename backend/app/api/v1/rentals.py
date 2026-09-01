"""
Rental/reservation API endpoints.
Covers full lifecycle: create, list, get, update, cancel, activate, complete.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from datetime import datetime, timezone

from app.database import get_db
from app.dependencies import get_current_user, require_perm, get_language
from app.auth.rbac import Permission
from app.models.vehicle import Vehicle
from app.schemas.rental import (
    RentalCreate, RentalUpdate, RentalResponse,
    RentalListResponse, AvailabilityRequest, AvailabilityResponse,
)
from app.services.rental_service import RentalService
from app.services.event_broadcaster import broadcaster
from app.i18n import get_message
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rentals", tags=["Rentals"])


def _get_origin(request: Request, current_user: dict) -> str:
    origin_hdr = request.headers.get("X-Client-Origin", "")
    if origin_hdr.upper() == "MOBILE" or current_user.get("role") == "MOBILE_USER":
        return "Mobile"
    return "Desktop"


def _rental_response(r, vehicle=None) -> RentalResponse:
    """Convert a Reservation model to a RentalResponse."""
    return RentalResponse(
        id=str(r.id),
        vehicle_id=str(r.vehicle_id),
        customer_name=getattr(r, "customer_name", None),
        customer_phone=getattr(r, "customer_phone", None),
        customer_email=getattr(r, "customer_email", None),
        identity_card_image=getattr(r, "identity_card_image", None),
        driving_license_image=getattr(r, "driving_license_image", None),
        start_datetime=r.start_datetime,
        end_datetime=r.end_datetime,
        daily_price=float(r.daily_price),
        num_days=r.num_days,
        total_price=float(r.total_price),
        deposit=float(r.deposit),
        payment_status=r.payment_status,
        status=r.status,
        cancellation_reason=getattr(r, "cancellation_reason", None),
        notes=r.notes,
        created_at=r.created_at,
        updated_at=r.updated_at,
        version=r.version,
    )


@router.post("", include_in_schema=False, response_model=RentalResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=RentalResponse, status_code=status.HTTP_201_CREATED)
async def create_rental(
    body: RentalCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_CREATE)),
    lang: str = Depends(get_language),
):
    """Create a new rental/reservation. Checks availability before creating."""
    service = RentalService(db)
    result = await service.create_rental(
        data=body,
        created_by=UUID(current_user["sub"]),
        lang=lang,
    )
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )
    rental = result["rental"]

    # Fetch vehicle registration for clear message
    v_res = await db.execute(select(Vehicle).where(Vehicle.id == rental.vehicle_id))
    vehicle = v_res.scalar_one_or_none()
    v_reg = vehicle.registration if vehicle else "Véhicule"

    origin = _get_origin(request, current_user)
    from app.services.notification_service import NotificationService
    notif_service = NotificationService(db)
    due_d = rental.start_datetime.date() if isinstance(rental.start_datetime, datetime) else datetime.now(timezone.utc).date()
    await notif_service.create_notification(
        vehicle_id=rental.vehicle_id,
        type="RESERVATION_CREATED",
        severity="info",
        title=f"🚗 Réservation : {v_reg}",
        message=f"Véhicule {v_reg} : nouvelle réservation créée depuis {origin} (Total: {rental.total_price} DH).",
        due_date=due_d,
        user_id=UUID(current_user["sub"]),
        origin=origin,
    )
    await db.commit()

    await broadcaster.broadcast_event(
        event_type="RESERVATION_CREATED",
        entity_type="reservation",
        entity_id=str(rental.id),
        message=f"🚗 Nouvelle réservation pour {v_reg} depuis {origin}.",
        origin=origin,
        vehicle_id=str(rental.vehicle_id),
        vehicle_registration=v_reg,
        data={"reservation_id": str(rental.id), "status": rental.status, "customer_name": rental.customer_name}
    )

    return _rental_response(rental)


@router.get("", include_in_schema=False, response_model=RentalListResponse)
@router.get("/", response_model=RentalListResponse)
async def list_rentals(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status_filter: str = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_READ)),
):
    """List rentals with pagination and optional status filter."""
    service = RentalService(db)
    result = await service.list_rentals(
        page=page, page_size=page_size, status=status_filter,
    )
    return RentalListResponse(
        rentals=[_rental_response(r) for r in result["rentals"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get("/{rental_id}", response_model=RentalResponse)
async def get_rental(
    rental_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_READ)),
    lang: str = Depends(get_language),
):
    """Get a specific rental by ID."""
    service = RentalService(db)
    result = await service.get_rental(rental_id, lang=lang)
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"],
        )
    return _rental_response(result["rental"])


@router.put("/{rental_id}", response_model=RentalResponse)
async def update_rental(
    rental_id: UUID,
    body: RentalUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_UPDATE)),
    lang: str = Depends(get_language),
):
    """Update a rental (dates, customer info, notes)."""
    service = RentalService(db)
    result = await service.update_rental(
        rental_id=rental_id,
        data=body,
        updated_by=UUID(current_user["sub"]),
        lang=lang,
    )
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )
    rental = result["rental"]

    v_res = await db.execute(select(Vehicle).where(Vehicle.id == rental.vehicle_id))
    vehicle = v_res.scalar_one_or_none()
    v_reg = vehicle.registration if vehicle else "Véhicule"

    origin = _get_origin(request, current_user)
    msg = f"📋 Réservation mise à jour pour véhicule {v_reg} depuis {origin}."
    await broadcaster.broadcast_event(
        event_type="RESERVATION_UPDATED",
        entity_type="reservation",
        entity_id=str(rental.id),
        message=msg,
        origin=origin,
        vehicle_id=str(rental.vehicle_id),
        vehicle_registration=v_reg,
        data={"reservation_id": str(rental.id), "status": rental.status}
    )

    return _rental_response(rental)


@router.post("/{rental_id}/cancel", response_model=RentalResponse)
async def cancel_rental(
    rental_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_CANCEL)),
    lang: str = Depends(get_language),
):
    """Cancel a rental."""
    service = RentalService(db)
    result = await service.cancel_rental(
        rental_id=rental_id,
        cancelled_by=UUID(current_user["sub"]),
        lang=lang,
    )
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )
    rental = result["rental"]

    v_res = await db.execute(select(Vehicle).where(Vehicle.id == rental.vehicle_id))
    vehicle = v_res.scalar_one_or_none()
    v_reg = vehicle.registration if vehicle else "Véhicule"

    origin = _get_origin(request, current_user)
    from app.services.notification_service import NotificationService
    notif_service = NotificationService(db)
    await notif_service.create_notification(
        vehicle_id=rental.vehicle_id,
        type="RESERVATION_CANCELLED",
        severity="warning",
        title=f"❌ Réservation annulée : {v_reg}",
        message=f"Réservation annulée pour le véhicule {v_reg} depuis {origin}.",
        due_date=datetime.now(timezone.utc).date(),
        user_id=UUID(current_user["sub"]),
        origin=origin,
    )
    await db.commit()

    await broadcaster.broadcast_event(
        event_type="RESERVATION_STATUS_CHANGED",
        entity_type="reservation",
        entity_id=str(rental.id),
        message=f"❌ Réservation annulée pour {v_reg} depuis {origin}.",
        origin=origin,
        vehicle_id=str(rental.vehicle_id),
        vehicle_registration=v_reg,
        data={"reservation_id": str(rental.id), "status": rental.status}
    )

    return _rental_response(rental)


@router.post("/{rental_id}/complete", response_model=RentalResponse)
async def complete_rental(
    rental_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_UPDATE)),
    lang: str = Depends(get_language),
):
    """Complete/close a rental."""
    service = RentalService(db)
    result = await service.complete_rental(
        rental_id=rental_id,
        completed_by=UUID(current_user["sub"]),
        lang=lang,
    )
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )
    rental = result["rental"]

    v_res = await db.execute(select(Vehicle).where(Vehicle.id == rental.vehicle_id))
    vehicle = v_res.scalar_one_or_none()
    v_reg = vehicle.registration if vehicle else "Véhicule"

    origin = _get_origin(request, current_user)
    from app.services.notification_service import NotificationService
    notif_service = NotificationService(db)
    await notif_service.create_notification(
        vehicle_id=rental.vehicle_id,
        type="VEHICLE_RETURNED",
        severity="info",
        title=f"✅ Véhicule restitué : {v_reg}",
        message=f"Véhicule {v_reg} est restitué (location terminée) depuis {origin}.",
        due_date=datetime.now(timezone.utc).date(),
        user_id=UUID(current_user["sub"]),
        origin=origin,
    )
    await db.commit()

    await broadcaster.broadcast_event(
        event_type="RESERVATION_STATUS_CHANGED",
        entity_type="reservation",
        entity_id=str(rental.id),
        message=f"✅ Location terminée pour {v_reg} depuis {origin}.",
        origin=origin,
        vehicle_id=str(rental.vehicle_id),
        vehicle_registration=v_reg,
        data={"reservation_id": str(rental.id), "status": rental.status}
    )

    return _rental_response(rental)


@router.post("/{rental_id}/activate", response_model=RentalResponse)
async def activate_rental(
    rental_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_UPDATE)),
    lang: str = Depends(get_language),
):
    """Activate a rental (vehicle pickup)."""
    service = RentalService(db)
    result = await service.activate_rental(
        rental_id=rental_id,
        activated_by=UUID(current_user["sub"]),
        lang=lang,
    )
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )
    rental = result["rental"]

    v_res = await db.execute(select(Vehicle).where(Vehicle.id == rental.vehicle_id))
    vehicle = v_res.scalar_one_or_none()
    v_reg = vehicle.registration if vehicle else "Véhicule"

    origin = _get_origin(request, current_user)
    from app.services.notification_service import NotificationService
    notif_service = NotificationService(db)
    due_d = rental.end_datetime.date() if isinstance(rental.end_datetime, datetime) else datetime.now(timezone.utc).date()
    await notif_service.create_notification(
        vehicle_id=rental.vehicle_id,
        type="VEHICLE_RENTED",
        severity="warning",
        title=f"🚗 Location active : {v_reg}",
        message=f"Véhicule {v_reg} vient d'être loué depuis {origin}.",
        due_date=due_d,
        user_id=UUID(current_user["sub"]),
        origin=origin,
    )
    await db.commit()

    await broadcaster.broadcast_event(
        event_type="RESERVATION_STATUS_CHANGED",
        entity_type="reservation",
        entity_id=str(rental.id),
        message=f"🚗 Véhicule {v_reg} est désormais en location depuis {origin}.",
        origin=origin,
        vehicle_id=str(rental.vehicle_id),
        vehicle_registration=v_reg,
        data={"reservation_id": str(rental.id), "status": rental.status}
    )

    return _rental_response(rental)
