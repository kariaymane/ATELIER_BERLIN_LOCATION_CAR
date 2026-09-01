"""
Vehicle service — business logic for vehicle management.
Enforces status transitions and mileage rules.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.models.vehicle_image import VehicleImage
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.audit_repository import AuditRepository
from app.i18n import get_message
from app.schemas.vehicle import VehicleCreate, VehicleUpdate
import logging
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[3]))
from shared.enums import VehicleStatus, VALID_VEHICLE_TRANSITIONS

logger = logging.getLogger(__name__)


class VehicleService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = VehicleRepository(session)
        self._audit = AuditRepository(session)

    async def create_vehicle(
        self,
        data: VehicleCreate,
        created_by: Optional[UUID] = None,
        lang: str = "fr",
    ) -> dict:
        """Create a new vehicle."""
        # Check uniqueness
        if await self._repo.registration_exists(data.registration):
            return {"error": get_message("vehicle.registration_exists", lang)}
        if await self._repo.vin_exists(data.vin):
            return {"error": get_message("vehicle.vin_exists", lang)}

        vehicle = Vehicle(
            registration=data.registration,
            vin=data.vin,
            brand=data.brand,
            model=data.model,
            year=data.year,
            color=data.color,
            fuel_type=data.fuel_type,
            transmission=data.transmission,
            current_mileage=data.current_mileage,
            purchase_mileage=data.purchase_mileage,
            purchase_price=data.purchase_price,
            daily_rental_price=data.daily_rental_price,
            purchase_date=data.purchase_date,
            notes=data.notes,
            assurance_expiry=data.assurance_expiry,
            vignette_expiry=data.vignette_expiry,
            visite_technique_expiry=data.visite_technique_expiry,
            carte_grise_expiry=data.carte_grise_expiry,
            autres_expiry=data.autres_expiry,
            autres_label=data.autres_label,
            image_url=data.image_url,
            created_by=created_by,
        )

        await self._repo.create(vehicle)

        # Parse comma-separated image_url and create VehicleImage records
        if vehicle.image_url:
            urls = [u.strip() for u in vehicle.image_url.split(",") if u.strip()]
            for idx, u in enumerate(urls):
                img = VehicleImage(vehicle_id=vehicle.id, image_url=u, sort_order=idx)
                self._session.add(img)
            await self._session.commit()

        await self._audit.create(
            entity_type="vehicle",
            action="CREATED",
            entity_id=vehicle.id,
            user_id=created_by,
            new_values={
                "registration": vehicle.registration,
                "vin": vehicle.vin,
                "brand": vehicle.brand,
                "model": vehicle.model,
            },
        )

        return {"vehicle": vehicle, "message": get_message("vehicle.created", lang)}

    async def get_vehicle(self, vehicle_id: UUID, lang: str = "fr") -> dict:
        """Get vehicle by ID."""
        vehicle = await self._repo.get_by_id(vehicle_id)
        if not vehicle:
            return {"error": get_message("vehicle.not_found", lang)}
        return {"vehicle": vehicle}

    async def update_vehicle(
        self,
        vehicle_id: UUID,
        data: VehicleUpdate,
        updated_by: Optional[UUID] = None,
        is_admin: bool = False,
        lang: str = "fr",
    ) -> dict:
        """Update a vehicle with audit logging."""
        vehicle = await self._repo.get_by_id(vehicle_id)
        if not vehicle:
            return {"error": get_message("vehicle.not_found", lang)}

        old_values = {}
        new_values = {}

        # Handle status transition
        if data.status is not None and data.status != vehicle.status:
            current = VehicleStatus(vehicle.status)
            target = VehicleStatus(data.status)
            if target not in VALID_VEHICLE_TRANSITIONS.get(current, set()):
                return {
                    "error": get_message(
                        "vehicle.invalid_status_transition",
                        lang,
                        from_status=vehicle.status,
                        to_status=data.status,
                    )
                }
            old_values["status"] = vehicle.status
            vehicle.status = data.status
            new_values["status"] = data.status

        # Handle mileage (cannot decrease without admin permission)
        if data.current_mileage is not None:
            if data.current_mileage < vehicle.current_mileage and not is_admin:
                return {"error": get_message("vehicle.mileage_decrease", lang)}
            if data.current_mileage != vehicle.current_mileage:
                old_values["current_mileage"] = vehicle.current_mileage
                vehicle.current_mileage = data.current_mileage
                new_values["current_mileage"] = data.current_mileage

        # Update other fields
        updatable_fields = [
            "registration", "brand", "model", "year", "color",
            "fuel_type", "transmission", "purchase_price",
            "daily_rental_price", "purchase_date", "notes",
            "assurance_expiry", "vignette_expiry", "visite_technique_expiry",
            "carte_grise_expiry", "autres_expiry", "autres_label", "image_url",
        ]
        for field in updatable_fields:
            value = getattr(data, field, None)
            if value is not None:
                old_val = getattr(vehicle, field)
                if old_val != value:
                    old_values[field] = str(old_val) if old_val is not None else None
                    setattr(vehicle, field, value)
                    new_values[field] = str(value)

        # Check registration uniqueness if changed
        if "registration" in new_values:
            if await self._repo.registration_exists(data.registration, exclude_id=vehicle_id):
                return {"error": get_message("vehicle.registration_exists", lang)}

        vehicle.version += 1

        if new_values:
            await self._audit.create(
                entity_type="vehicle",
                action="UPDATED",
                entity_id=vehicle.id,
                user_id=updated_by,
                old_values=old_values,
                new_values=new_values,
            )

        return {"vehicle": vehicle, "message": get_message("vehicle.updated", lang)}

    async def delete_vehicle(
        self,
        vehicle_id: UUID,
        deleted_by: Optional[UUID] = None,
        lang: str = "fr",
    ) -> dict:
        """Soft-delete or remove a vehicle."""
        vehicle = await self._repo.get_by_id(vehicle_id)
        if not vehicle:
            return {"error": get_message("vehicle.not_found", lang)}

        await self._audit.create(
            entity_type="vehicle",
            action="DELETED",
            entity_id=vehicle.id,
            user_id=deleted_by,
            old_values={"registration": vehicle.registration},
        )

        from sqlalchemy import select
        from app.models.reservation import Reservation
        from app.models.maintenance import Maintenance

        vid = vehicle.id
        res_query = select(Reservation).where(Reservation.vehicle_id == vid)
        maint_query = select(Maintenance).where(Maintenance.vehicle_id == vid)

        reservations = await self._session.execute(res_query)
        maintenances = await self._session.execute(maint_query)

        if reservations.first() or maintenances.first():
            vehicle.status = "INACTIVE"
            await self._session.commit()
            return {"message": "Véhicule désactivé car il possède un historique de location ou de maintenance."}

        await self._repo.delete_entity(vehicle)
        return {"message": get_message("vehicle.deleted", lang)}

    async def list_vehicles(
        self,
        page: int = 1,
        page_size: int = 25,
        status: Optional[str] = None,
        search: Optional[str] = None,
        price: Optional[float] = None,
    ) -> dict:
        """List vehicles with optional filtering by status, search, and price."""
        vehicles, total = await self._repo.list_filtered(
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            price=price,
        )

        return {
            "vehicles": vehicles,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_status_counts(self) -> dict[str, int]:
        """Count of vehicles per EFFECTIVE status — the same derivation the
        Dashboard uses, so /vehicles/stats and /dashboard/stats never disagree.
        Structural buckets (SOLD/INACTIVE) are reported from raw status."""
        from app.services.fleet_status import compute_effective_statuses
        eff = await compute_effective_statuses(self._session)
        counts: dict[str, int] = {}
        for st in eff.values():
            counts[st] = counts.get(st, 0) + 1
        return counts
