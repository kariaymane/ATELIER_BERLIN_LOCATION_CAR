"""
Vehicle management API endpoints.
Catches PostgreSQL constraint errors for double booking and returns localized messages.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from uuid import UUID
from typing import Optional
import os
import shutil
import uuid
from pathlib import Path
from datetime import datetime, date, timezone

from app.database import get_db
from app.dependencies import get_current_user, require_perm, get_language
from app.auth.rbac import Permission
from app.schemas.vehicle import (
    VehicleCreate, VehicleUpdate, VehicleResponse,
    VehicleListResponse, VehicleStatusUpdate,
)
from app.services.vehicle_service import VehicleService
from app.services.event_broadcaster import broadcaster
from app.i18n import get_message
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


def _get_origin(request: Request, current_user: dict) -> str:
    origin_hdr = request.headers.get("X-Client-Origin", "")
    if origin_hdr.upper() == "MOBILE" or current_user.get("role") == "MOBILE_USER":
        return "Mobile"
    return "Desktop"



@router.post("/upload-image")
async def upload_vehicle_image(
    file: UploadFile = File(...),
    vehicle_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_CREATE)),
    lang: str = Depends(get_language),
):
    """Upload a vehicle image and optionally attach to a vehicle."""
    # Size limit (e.g., 5MB)
    MAX_SIZE = 5 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le fichier est trop volumineux (max 5 MB).",
        )

    # Magic bytes validation
    is_jpeg = content.startswith(b'\xff\xd8\xff')
    is_png = content.startswith(b'\x89PNG\r\n\x1a\n')
    is_webp = content.startswith(b'RIFF') and content[8:12] == b'WEBP'

    if not (is_jpeg or is_png or is_webp):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fichier image invalide ou corrompu. Seuls JPG, PNG, WEBP sont autorisés.",
        )

    upload_dir = Path("uploads/vehicles")
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = ".jpg"
    if is_png:
        ext = ".png"
    elif is_webp:
        ext = ".webp"
    filename = f"{uuid.uuid4().hex}{ext}"
    target_path = upload_dir / filename

    with open(target_path, "wb") as buffer:
        buffer.write(content)

    relative_url = f"/static/uploads/vehicles/{filename}"

    if vehicle_id:
        service = VehicleService(db)
        update_data = VehicleUpdate(image_url=relative_url)
        await service.update_vehicle(
            vehicle_id=vehicle_id,
            data=update_data,
            updated_by=UUID(current_user["sub"]),
            lang=lang,
        )

    return {
        "status": "ok",
        "image_url": relative_url,
        "filename": filename,
    }


@router.post("", include_in_schema=False, response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    body: VehicleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_CREATE)),
    lang: str = Depends(get_language),
):
    """Create a new vehicle. Requires ADMIN or MANAGER role."""
    service = VehicleService(db)
    try:
        result = await service.create_vehicle(
            data=body,
            created_by=UUID(current_user["sub"]),
            lang=lang,
        )
    except IntegrityError as e:
        await db.rollback()
        error_str = str(e.orig) if e.orig else str(e)
        if "registration" in error_str.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=get_message("vehicle.registration_exists", lang),
            )
        elif "vin" in error_str.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=get_message("vehicle.vin_exists", lang),
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=get_message("validation.error", lang),
        )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    v = result["vehicle"]
    origin = _get_origin(request, current_user)
    msg = f"🚗 Nouveau véhicule {v.brand} {v.model} ({v.registration}) ajouté depuis {origin}."
    await broadcaster.broadcast_event(
        event_type="VEHICLE_CREATED",
        entity_type="vehicle",
        entity_id=str(v.id),
        message=msg,
        origin=origin,
        vehicle_id=str(v.id),
        vehicle_registration=v.registration,
        data={"registration": v.registration, "status": v.status, "brand": v.brand, "model": v.model}
    )

    return _vehicle_response(v)


@router.get("", include_in_schema=False, response_model=VehicleListResponse)
@router.get("/", response_model=VehicleListResponse)
async def list_vehicles(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    status_filter: str = Query(None, alias="status"),
    search: str = Query(None),
    price: Optional[float] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """List vehicles with pagination, status filter, price filter, and search."""
    service = VehicleService(db)
    result = await service.list_vehicles(
        page=page,
        page_size=page_size,
        status=status_filter,
        search=search,
        price=price,
    )
    from app.services.fleet_status import compute_effective_statuses
    eff = await compute_effective_statuses(
        db, vehicle_ids=[v.id for v in result["vehicles"]]
    )
    return VehicleListResponse(
        vehicles=[_vehicle_response(v, eff.get(str(v.id))) for v in result["vehicles"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get("/stats")
async def vehicle_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
):
    """Get vehicle count by status for dashboard."""
    service = VehicleService(db)
    counts = await service.get_status_counts()
    return {"status_counts": counts}


@router.get("/{vehicle_id}/availability")
async def check_availability(
    vehicle_id: UUID,
    start: str = Query(..., description="ISO datetime"),
    end: str = Query(..., description="ISO datetime"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
    lang: str = Depends(get_language),
):
    """Check vehicle availability for a date range and return pricing estimate."""
    from datetime import datetime
    from app.services.rental_service import RentalService

    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail=get_message("reservation.invalid_dates", lang))

    service = VehicleService(db)
    result = await service.get_vehicle(vehicle_id, lang=lang)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    vehicle = result["vehicle"]
    rental_service = RentalService(db)
    available, reason = await rental_service.check_availability(vehicle_id, start_dt, end_dt)
    num_days = rental_service.calculate_days(start_dt, end_dt)
    daily_price = float(vehicle.daily_rental_price)

    return {
        "vehicle_id": str(vehicle_id),
        "available": available,
        "reason": reason,
        "daily_price": daily_price,
        "start_datetime": start_dt.isoformat(),
        "end_datetime": end_dt.isoformat(),
        "num_days": num_days,
        "estimated_total": round(daily_price * num_days, 2),
    }


@router.get("/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(
    vehicle_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_READ)),
    lang: str = Depends(get_language),
):
    """Get a specific vehicle by ID."""
    service = VehicleService(db)
    result = await service.get_vehicle(vehicle_id, lang=lang)

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"],
        )

    from app.services.fleet_status import compute_effective_statuses
    eff = await compute_effective_statuses(db, vehicle_ids=[vehicle_id])
    return _vehicle_response(result["vehicle"], eff.get(str(vehicle_id)))


@router.put("/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    vehicle_id: UUID,
    body: VehicleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_UPDATE)),
    lang: str = Depends(get_language),
):
    """Update a vehicle. ADMIN can correct mileage downward."""
    is_admin = current_user.get("role") == "ADMIN"
    service = VehicleService(db)

    try:
        result = await service.update_vehicle(
            vehicle_id=vehicle_id,
            data=body,
            updated_by=UUID(current_user["sub"]),
            is_admin=is_admin,
            lang=lang,
        )
    except IntegrityError as e:
        await db.rollback()
        error_str = str(e.orig) if e.orig else str(e)
        if "registration" in error_str.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=get_message("vehicle.registration_exists", lang),
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=get_message("validation.error", lang),
        )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    v = result["vehicle"]
    origin = _get_origin(request, current_user)
    msg = f"📋 Véhicule {v.registration} mis à jour depuis {origin}."
    await broadcaster.broadcast_event(
        event_type="VEHICLE_UPDATED",
        entity_type="vehicle",
        entity_id=str(v.id),
        message=msg,
        origin=origin,
        vehicle_id=str(v.id),
        vehicle_registration=v.registration,
        data={"registration": v.registration, "status": v.status, "brand": v.brand, "model": v.model}
    )

    return _vehicle_response(v)


@router.patch("/{vehicle_id}/status")
async def update_vehicle_status(
    vehicle_id: UUID,
    body: VehicleStatusUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_UPDATE)),
    lang: str = Depends(get_language),
):
    """Update vehicle status with transition validation."""
    service = VehicleService(db)
    update_data = VehicleUpdate(status=body.status)

    result = await service.update_vehicle(
        vehicle_id=vehicle_id,
        data=update_data,
        updated_by=UUID(current_user["sub"]),
        lang=lang,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    v = result["vehicle"]
    origin = _get_origin(request, current_user)

    if body.status == "MAINTENANCE":
        msg = f"🔧 Véhicule {v.registration} envoyé en maintenance depuis {origin}."
        severity = "maintenance_required"
        notif_type = "MAINTENANCE_REQUIRED"
        title = f"🔧 Maintenance : {v.brand} {v.model}"
    elif body.status == "RENTED":
        msg = f"🚗 Véhicule {v.registration} vient d'être loué depuis {origin}."
        severity = "warning"
        notif_type = "VEHICLE_RENTED"
        title = f"🚗 Location en cours : {v.registration}"
    elif body.status == "AVAILABLE":
        msg = f"✅ Véhicule {v.registration} est désormais disponible depuis {origin}."
        severity = "info"
        notif_type = "VEHICLE_AVAILABLE"
        title = f"✅ Véhicule disponible : {v.brand} {v.model}"
    else:
        msg = f"📋 Statut du véhicule {v.registration} changé en {body.status} depuis {origin}."
        severity = "info"
        notif_type = "VEHICLE_STATUS"
        title = f"📋 Statut {v.registration} : {body.status}"

    from app.services.notification_service import NotificationService
    notif_service = NotificationService(db)
    await notif_service.create_notification(
        vehicle_id=v.id,
        type=notif_type,
        severity=severity,
        title=title,
        message=msg,
        due_date=datetime.now(timezone.utc).date(),
        user_id=UUID(current_user["sub"]),
        origin=origin,
    )
    await db.commit()

    await broadcaster.broadcast_event(
        event_type="VEHICLE_STATUS_CHANGED",
        entity_type="vehicle",
        entity_id=str(v.id),
        message=msg,
        origin=origin,
        vehicle_id=str(v.id),
        vehicle_registration=v.registration,
        data={"registration": v.registration, "status": v.status, "brand": v.brand, "model": v.model}
    )

    return _vehicle_response(v)


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle(
    vehicle_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_DELETE)),
    lang: str = Depends(get_language),
):
    """Delete a vehicle. Requires ADMIN role."""
    service = VehicleService(db)
    result = await service.delete_vehicle(
        vehicle_id=vehicle_id,
        deleted_by=UUID(current_user["sub"]),
        lang=lang,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"],
        )

    await broadcaster.broadcast_event(
        event_type="VEHICLE_DELETED",
        entity_type="vehicle",
        entity_id=str(vehicle_id),
        message=f"🗑️ Véhicule {vehicle_id} supprimé.",
        origin="API",
    )


def _vehicle_response(v, effective_status: str = None) -> VehicleResponse:
    """Convert a Vehicle model to a VehicleResponse."""
    return VehicleResponse(
        effective_status=effective_status or v.status,
        id=str(v.id),
        registration=v.registration,
        vin=v.vin,
        brand=v.brand,
        model=v.model,
        year=v.year,
        color=v.color,
        fuel_type=v.fuel_type,
        transmission=v.transmission,
        current_mileage=v.current_mileage,
        purchase_mileage=v.purchase_mileage,
        purchase_price=float(v.purchase_price),
        daily_rental_price=float(v.daily_rental_price),
        purchase_date=v.purchase_date,
        status=v.status,
        notes=v.notes,
        assurance_expiry=v.assurance_expiry,
        vignette_expiry=v.vignette_expiry,
        visite_technique_expiry=v.visite_technique_expiry,
        carte_grise_expiry=v.carte_grise_expiry,
        autres_expiry=v.autres_expiry,
        autres_label=v.autres_label,
        image_url=v.image_url,
        created_at=v.created_at,
        updated_at=v.updated_at,
        version=v.version,
    )
