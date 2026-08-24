from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete

from app.database import get_db
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.dependencies import require_perm
from app.auth.rbac import Permission
from app.models.vehicle import Vehicle
from app.models.maintenance import Maintenance
from app.models.reservation import Reservation
from app.schemas.maintenance import MaintenanceBase, MaintenanceCreate, MaintenanceUpdate, MaintenanceResponse, MaintenanceListResponse
from app.services.event_broadcaster import broadcaster

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])

def _extract_user_id(user) -> UUID | None:
    if isinstance(user, dict):
        sub = user.get("sub")
        return UUID(sub) if sub else None
    if hasattr(user, "id"):
        return user.id
    return None

def _get_origin(request: Request, current_user: dict) -> str:
    origin_hdr = request.headers.get("X-Client-Origin", "")
    if origin_hdr.upper() == "MOBILE" or current_user.get("role") == "MOBILE_USER":
        return "Mobile"
    return "Desktop"

def _maintenance_response(m: Maintenance, v: Vehicle | None = None) -> MaintenanceResponse:
    resp = MaintenanceResponse(
        id=m.id,
        vehicle_id=m.vehicle_id,
        type=m.type,
        description=m.description,
        start_datetime=m.start_datetime,
        expected_end_datetime=m.expected_end_datetime,
        actual_end_datetime=m.actual_end_datetime,
        mileage=m.mileage,
        location=m.location,
        estimated_cost=m.estimated_cost,
        actual_cost=m.actual_cost,
        step=m.step,
        status=m.status,
        notes=m.notes,
        created_by=m.created_by,
        created_at=m.created_at,
        updated_at=m.updated_at,
        version=m.version,
        vehicle_brand=v.brand if v else None,
        vehicle_model=v.model if v else None,
        vehicle_registration=v.registration if v else None,
        vehicle_image_url=v.image_url if v else None,
    )
    return resp


@router.get("", include_in_schema=False, response_model=MaintenanceListResponse)
@router.get("/", response_model=MaintenanceListResponse)
async def get_maintenances(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    vehicle_id: UUID = Query(None),
    status: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.MAINTENANCE_READ)),
):
    """
    Retrieve all maintenance records with pagination and joined vehicle metadata.
    """
    from sqlalchemy.orm import selectinload
    query = select(Maintenance, Vehicle).outerjoin(Vehicle, Maintenance.vehicle_id == Vehicle.id).options(selectinload(Maintenance.parts))
    if vehicle_id:
        query = query.where(Maintenance.vehicle_id == vehicle_id)
    if status:
        query = query.where(Maintenance.status == status)

    query = query.order_by(Maintenance.created_at.desc())

    count_query = select(func.count(Maintenance.id))
    if vehicle_id:
        count_query = count_query.where(Maintenance.vehicle_id == vehicle_id)
    if status:
        count_query = count_query.where(Maintenance.status == status)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.offset((page - 1) * size).limit(size)
    result = await db.execute(query)
    rows = result.all()

    items = [_maintenance_response(m, v) for m, v in rows]
    pages = (total + size - 1) // size

    return MaintenanceListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
        pages=pages
    )

@router.get("/{maintenance_id}", response_model=MaintenanceResponse)
async def get_maintenance(
    maintenance_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.MAINTENANCE_READ)),
):
    """
    Get maintenance record by ID with vehicle metadata.
    """
    from sqlalchemy.orm import selectinload
    query = select(Maintenance, Vehicle).outerjoin(Vehicle, Maintenance.vehicle_id == Vehicle.id).options(selectinload(Maintenance.parts)).where(Maintenance.id == maintenance_id)
    result = await db.execute(query)
    row = result.first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance not found"
        )
    m, v = row
    return _maintenance_response(m, v)

@router.post("", include_in_schema=False, response_model=MaintenanceResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=MaintenanceResponse, status_code=status.HTTP_201_CREATED)
async def create_maintenance(
    body: MaintenanceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.MAINTENANCE_CREATE)),
):
    """
    Create a new maintenance record and mark vehicle as in MAINTENANCE.
    """
    # Check vehicle
    v_res = await db.execute(select(Vehicle).where(Vehicle.id == body.vehicle_id))
    vehicle = v_res.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

    res_check = await db.execute(
        select(Reservation).where(
            Reservation.vehicle_id == body.vehicle_id,
            Reservation.status.in_(["ACTIVE", "RESERVED"])
        )
    )
    if res_check.first():
        raise HTTPException(status_code=409, detail="Impossible de créer une maintenance : le véhicule a des réservations actives.")

    from app.models.maintenance import MaintenancePart
    parts_cost = 0.0
    db_parts = []
    if body.parts:
        for p in body.parts:
            part = MaintenancePart(
                part_name=p.part_name,
                quantity=p.quantity,
                unit_price=p.unit_price,
                total_price=p.total_price if p.total_price else (p.quantity * p.unit_price),
                notes=p.notes
            )
            parts_cost += float(part.total_price)
            db_parts.append(part)

    actual_cost = parts_cost + body.labor_cost + body.other_cost

    new_maint = Maintenance(
        vehicle_id=body.vehicle_id,
        type=body.type,
        title=body.title,
        description=body.description,
        diagnosis=body.diagnosis,
        repair_description=body.repair_description,
        start_datetime=body.start_datetime,
        expected_end_datetime=body.expected_end_datetime,
        actual_end_datetime=body.actual_end_datetime,
        mileage=body.mileage,
        location=body.location,
        technician_name=body.technician_name,
        invoice_number=body.invoice_number,
        oil_brand=body.oil_brand,
        oil_viscosity=body.oil_viscosity,
        oil_quantity=body.oil_quantity,
        oil_filter_changed=body.oil_filter_changed,
        air_filter_changed=body.air_filter_changed,
        fuel_filter_changed=body.fuel_filter_changed,
        cabin_filter_changed=body.cabin_filter_changed,
        estimated_cost=body.estimated_cost,
        parts_cost=parts_cost,
        labor_cost=body.labor_cost,
        other_cost=body.other_cost,
        actual_cost=actual_cost,
        next_maintenance_date=body.next_maintenance_date,
        next_maintenance_mileage=body.next_maintenance_mileage,
        step=body.step or "EN ATTENTE",
        status=body.status or "ACTIVE",
        notes=body.notes,
        created_by=_extract_user_id(current_user),
        parts=db_parts
    )
    db.add(new_maint)

    # Set vehicle to MAINTENANCE
    vehicle.status = "MAINTENANCE"
    vehicle.version += 1

    await db.commit()
    await db.refresh(new_maint)

    # Persist Notification in PostgreSQL & Broadcast to Desktop + Mobile
    from app.services.notification_service import NotificationService
    notif_service = NotificationService(db)
    origin = _get_origin(request, current_user)
    due_d = new_maint.start_datetime.date() if isinstance(new_maint.start_datetime, datetime) else datetime.now(timezone.utc).date()
    await notif_service.create_notification(
        vehicle_id=vehicle.id,
        type="MAINTENANCE_CREATED",
        severity="maintenance_required",
        title=f"🔧 Maintenance : {vehicle.brand} {vehicle.model}",
        message=f"Véhicule {vehicle.registration} envoyé en maintenance ({new_maint.type}) depuis {origin}.",
        due_date=due_d,
        user_id=_extract_user_id(current_user),
        origin=origin,
    )
    await db.commit()

    await broadcaster.broadcast_event(
        event_type="MAINTENANCE_CREATED",
        entity_type="maintenance",
        entity_id=str(new_maint.id),
        message=f"🔧 Nouveau ticket maintenance pour {vehicle.registration} depuis {origin}.",
        origin=origin,
        vehicle_id=str(vehicle.id),
        vehicle_registration=vehicle.registration,
        data={"maintenance_id": str(new_maint.id), "status": new_maint.status, "step": new_maint.step}
    )

    # Re-query with eager-loaded parts (same pattern as GET endpoints) so
    # response serialization cannot hit a detached instance.
    from sqlalchemy.orm import selectinload as _selectinload
    reloaded = await db.execute(
        select(Maintenance)
        .options(_selectinload(Maintenance.parts))
        .where(Maintenance.id == new_maint.id)
    )
    return reloaded.scalar_one()

@router.post("/{maintenance_id}/advance", response_model=MaintenanceResponse)
async def advance_maintenance_step(
    maintenance_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.MAINTENANCE_UPDATE)),
):
    """
    Advance maintenance workflow step.
    """
    steps = ["EN ATTENTE", "DIAGNOSTIC", "REPARATION", "CONTROLE", "TERMINE"]
    query = select(Maintenance).where(Maintenance.id == maintenance_id)
    result = await db.execute(query)
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance not found")

    vehicle = None
    if m.step in steps:
        idx = steps.index(m.step)
        if idx < len(steps) - 1:
            m.step = steps[idx + 1]
            m.version += 1
            if m.step == "TERMINE":
                m.status = "COMPLETED"
                m.actual_end_datetime = datetime.now(timezone.utc)
                # Free vehicle
                v_res = await db.execute(select(Vehicle).where(Vehicle.id == m.vehicle_id))
                vehicle = v_res.scalar_one_or_none()
                if vehicle:
                    vehicle.status = "AVAILABLE"
                    vehicle.version += 1

    await db.commit()
    await db.refresh(m)

    origin = _get_origin(request, current_user)
    v_reg = vehicle.registration if vehicle else "Véhicule"
    v_title = f"{vehicle.brand} {vehicle.model}" if vehicle else v_reg

    # Persist Notification if completed
    if m.status == "COMPLETED" or m.step == "TERMINE":
        from app.services.notification_service import NotificationService
        notif_service = NotificationService(db)
        await notif_service.create_notification(
            vehicle_id=m.vehicle_id,
            type="MAINTENANCE_COMPLETED",
            severity="info",
            title=f"✅ Maintenance terminée : {v_title}",
            message=f"Véhicule {v_reg} est sorti de maintenance depuis {origin}.",
            due_date=datetime.now(timezone.utc).date(),
            user_id=_extract_user_id(current_user),
            origin=origin,
        )
        await db.commit()

    await broadcaster.broadcast_event(
        event_type="MAINTENANCE_UPDATED",
        entity_type="maintenance",
        entity_id=str(m.id),
        message=f"🔧 Ticket maintenance {m.id} avancé à l'étape {m.step} depuis {origin}.",
        origin=origin,
        vehicle_id=str(m.vehicle_id),
        vehicle_registration=v_reg,
        data={"maintenance_id": str(m.id), "status": m.status, "step": m.step}
    )

    return m

@router.post("/{maintenance_id}/complete", response_model=MaintenanceResponse)
async def complete_maintenance(
    maintenance_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.MAINTENANCE_UPDATE)),
):
    """
    Complete maintenance and set vehicle back to AVAILABLE.
    """
    query = select(Maintenance).where(Maintenance.id == maintenance_id)
    result = await db.execute(query)
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance not found")

    m.status = "COMPLETED"
    m.step = "TERMINE"
    m.actual_end_datetime = datetime.now(timezone.utc)
    m.version += 1

    # Free vehicle
    v_res = await db.execute(select(Vehicle).where(Vehicle.id == m.vehicle_id))
    vehicle = v_res.scalar_one_or_none()
    if vehicle and vehicle.status == "MAINTENANCE":
        vehicle.status = "AVAILABLE"
        vehicle.version += 1

    await db.commit()
    await db.refresh(m)

    # Persist Notification in PostgreSQL & Broadcast to Desktop + Mobile
    origin = _get_origin(request, current_user)
    v_reg = vehicle.registration if vehicle else "Véhicule"
    v_title = f"{vehicle.brand} {vehicle.model}" if vehicle else v_reg
    from app.services.notification_service import NotificationService
    notif_service = NotificationService(db)
    await notif_service.create_notification(
        vehicle_id=m.vehicle_id,
        type="MAINTENANCE_COMPLETED",
        severity="info",
        title=f"✅ Maintenance terminée : {v_title}",
        message=f"Véhicule {v_reg} est sorti de maintenance depuis {origin}.",
        due_date=datetime.now(timezone.utc).date(),
        user_id=_extract_user_id(current_user),
        origin=origin,
    )
    await db.commit()

    await broadcaster.broadcast_event(
        event_type="MAINTENANCE_UPDATED",
        entity_type="maintenance",
        entity_id=str(m.id),
        message=f"✅ Maintenance terminée pour {v_reg} depuis {origin}.",
        origin=origin,
        vehicle_id=str(m.vehicle_id),
        vehicle_registration=v_reg,
        data={"maintenance_id": str(m.id), "status": m.status, "step": m.step}
    )

    return m

@router.delete("/{maintenance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_maintenance(
    maintenance_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.MAINTENANCE_DELETE)),
):
    """
    Delete a maintenance record.
    """
    query = select(Maintenance).where(Maintenance.id == maintenance_id)
    result = await db.execute(query)
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance not found")

    if m.status == "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de supprimer une maintenance en cours. Veuillez la terminer ou l'annuler d'abord."
        )

    await db.delete(m)
    await db.commit()

    await broadcaster.broadcast_event(
        event_type="MAINTENANCE_CLOSED",
        entity_type="maintenance",
        entity_id=str(maintenance_id),
        message=f"🗑️ Ticket maintenance {maintenance_id} supprimé.",
        origin="API",
        vehicle_id=str(m.vehicle_id),
    )
    return None

@router.patch("/{maintenance_id}", response_model=MaintenanceResponse)
async def update_maintenance(
    maintenance_id: UUID,
    body: MaintenanceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.MAINTENANCE_UPDATE)),
):
    from sqlalchemy.orm import selectinload
    query = select(Maintenance, Vehicle).outerjoin(Vehicle, Maintenance.vehicle_id == Vehicle.id).where(Maintenance.id == maintenance_id).options(selectinload(Maintenance.parts))
    result = await db.execute(query)
    row = result.first()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance not found")

    m, v = row

    update_data = body.dict(exclude_unset=True)
    if "parts" in update_data:
        # For simplicity, if parts are provided, replace them entirely
        parts_data = update_data.pop("parts")
        from app.models.maintenance import MaintenancePart
        # delete old parts
        await db.execute(delete(MaintenancePart).where(MaintenancePart.maintenance_id == maintenance_id))

        parts_cost = 0.0
        db_parts = []
        for p in parts_data:
            part = MaintenancePart(
                maintenance_id=maintenance_id,
                part_name=p["part_name"],
                quantity=p["quantity"],
                unit_price=p["unit_price"],
                total_price=p.get("total_price") or (p["quantity"] * p["unit_price"]),
                notes=p.get("notes")
            )
            parts_cost += float(part.total_price)
            db_parts.append(part)

        db.add_all(db_parts)
        m.parts_cost = parts_cost

    for key, value in update_data.items():
        setattr(m, key, value)

    m.actual_cost = float(m.parts_cost) + float(m.labor_cost) + float(m.other_cost)
    m.version += 1

    await db.commit()
    await db.refresh(m)

    return _maintenance_response(m, v)
