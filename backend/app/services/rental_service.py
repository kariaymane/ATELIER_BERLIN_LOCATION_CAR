"""
Rental service — business logic for location/reservation management.
Enforces availability, calculates pricing, manages lifecycle.
"""
import math
from typing import Optional
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.models.reservation import Reservation
from app.models.vehicle import Vehicle
from app.models.client import Client
from app.repositories.rental_repository import RentalRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.audit_repository import AuditRepository
from app.schemas.rental import RentalCreate, RentalUpdate
from app.i18n import get_message
import logging

logger = logging.getLogger(__name__)


class RentalService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = RentalRepository(session)
        self._vehicle_repo = VehicleRepository(session)
        self._audit = AuditRepository(session)

    @staticmethod
    def calculate_days(start: datetime, end: datetime) -> int:
        """Calculate rental days (minimum 1 day). Partial days count as full."""
        delta = end - start
        total_hours = delta.total_seconds() / 3600
        return max(1, math.ceil(total_hours / 24))

    async def check_availability(
        self,
        vehicle_id: UUID,
        start_dt: datetime,
        end_dt: datetime,
        exclude_rental_id: Optional[UUID] = None,
    ) -> tuple[bool, Optional[str]]:
        """Check if a vehicle is available for the given period."""
        return await self._repo.check_availability(
            vehicle_id, start_dt, end_dt, exclude_rental_id
        )

    async def create_rental(
        self,
        data: RentalCreate,
        created_by: Optional[UUID] = None,
        lang: str = "fr",
    ) -> dict:
        """Create a new rental/reservation with full validation."""
        # Validate vehicle exists
        vehicle = await self._vehicle_repo.get_by_id(data.vehicle_id)
        if not vehicle:
            return {"error": get_message("vehicle.not_found", lang)}

        # Parse dates
        start_dt = data.start_datetime
        end_dt = data.end_datetime

        if end_dt <= start_dt:
            return {"error": get_message("reservation.invalid_dates", lang)}

        # Maintenance availability is now handled by check_availability 
        # based on date overlaps rather than a global vehicle status lock.

        # Validate the client link when provided (authoritative Clients table).
        if data.customer_id is not None:
            client = (await self._session.execute(
                select(Client).where(Client.id == data.customer_id)
            )).scalar_one_or_none()
            if client is None:
                return {"error": get_message("client.not_found", lang)}

        # Check availability (application-level, before the DB constraint)
        available, reason = await self._repo.check_availability(
            data.vehicle_id, start_dt, end_dt
        )
        if not available:
            if reason == "MAINTENANCE":
                return {"error": get_message("vehicle.in_maintenance", lang)}
            return {"error": get_message("reservation.double_booking", lang)}

        # Calculate pricing
        num_days = self.calculate_days(start_dt, end_dt)
        daily_price = data.daily_price or float(vehicle.daily_rental_price)
        total_price = round(daily_price * num_days, 2)

        try:
            rental = Reservation(
                vehicle_id=data.vehicle_id,
                customer_id=data.customer_id,
                customer_name=data.customer_name,
                customer_phone=data.customer_phone,
                customer_email=data.customer_email,
                identity_card_image=data.identity_card_image,
                driving_license_image=data.driving_license_image,
                start_datetime=start_dt,
                end_datetime=end_dt,
                daily_price=daily_price,
                num_days=num_days,
                total_price=total_price,
                deposit=data.deposit or 0,
                status="RESERVED",
                notes=data.notes,
                created_by=created_by,
            )
            self._session.add(rental)
            await self._session.flush()

            await self._audit.create(
                entity_type="rental",
                action="CREATED",
                entity_id=rental.id,
                user_id=created_by,
                new_values={
                    "vehicle_id": str(data.vehicle_id),
                    "customer_name": data.customer_name,
                    "start": start_dt.isoformat(),
                    "end": end_dt.isoformat(),
                    "total_price": total_price,
                },
            )

            logger.info("Rental created: %s for vehicle %s", rental.id, vehicle.registration)
            return {"rental": rental}

        except IntegrityError as e:
            await self._session.rollback()
            error_str = str(e.orig) if e.orig else str(e)
            if "excl_reservations_no_overlap" in error_str:
                return {"error": get_message("reservation.double_booking", lang)}
            logger.error("Rental create integrity error: %s", error_str)
            return {"error": get_message("validation.error", lang)}

    async def get_rental(self, rental_id: UUID, lang: str = "fr") -> dict:
        """Get a rental by ID."""
        rental = await self._repo.get_by_id(rental_id)
        if not rental:
            return {"error": get_message("reservation.not_found", lang)}
        return {"rental": rental}

    async def list_rentals(
        self,
        page: int = 1,
        page_size: int = 25,
        status: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> dict:
        """List rentals with pagination, deterministic ordering, and optional status/scope filters."""
        from sqlalchemy import or_, and_
        from shared.money_time import now_business

        filters = []
        if status:
            filters.append(Reservation.status == status)

        if scope:
            norm_scope = scope.strip().lower()
            if norm_scope == "current":
                filters.append(Reservation.status.in_(["ACTIVE", "RESERVED"]))
            elif norm_scope == "history":
                filters.append(Reservation.status.in_(["COMPLETED", "CANCELLED"]))

        order_by = [
            Reservation.start_datetime.desc(),
            Reservation.created_at.desc(),
            Reservation.id.desc(),
        ]
        rentals, total = await self._repo.get_all(
            page=page, page_size=page_size, filters=filters if filters else None, order_by=order_by
        )
        return {
            "rentals": rentals,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def cancel_rental(
        self,
        rental_id: UUID,
        cancelled_by: Optional[UUID] = None,
        lang: str = "fr",
    ) -> dict:
        """Cancel a rental. Only RESERVED rentals can be cancelled."""
        rental = await self._repo.get_by_id(rental_id)
        if not rental:
            return {"error": get_message("reservation.not_found", lang)}

        if rental.status not in ("RESERVED", "ACTIVE"):
            return {"error": get_message("reservation.invalid_dates", lang)}

        old_status = rental.status
        rental.status = "CANCELLED"
        rental.version += 1

        vehicle = await self._vehicle_repo.get_by_id(rental.vehicle_id)
        if vehicle and vehicle.status in ("RESERVED", "RENTED"):
            vehicle.status = "AVAILABLE"
            vehicle.version += 1

        await self._session.flush()

        await self._audit.create(
            entity_type="rental",
            action="CANCELLED",
            entity_id=rental.id,
            user_id=cancelled_by,
            old_values={"status": old_status},
            new_values={"status": "CANCELLED"},
        )

        return {"rental": rental}

    async def complete_rental(
        self,
        rental_id: UUID,
        completed_by: Optional[UUID] = None,
        lang: str = "fr",
    ) -> dict:
        """Complete/close a rental. ACTIVE or RESERVED rentals can be completed."""
        rental = await self._repo.get_by_id(rental_id)
        if not rental:
            return {"error": get_message("reservation.not_found", lang)}

        if rental.status not in ("ACTIVE", "RESERVED"):
            return {"error": "Seules les locations en cours ou réservées peuvent être terminées."}

        old_status = rental.status
        rental.status = "COMPLETED"
        rental.version += 1

        vehicle = await self._vehicle_repo.get_by_id(rental.vehicle_id)
        if vehicle and vehicle.status in ("RESERVED", "RENTED"):
            vehicle.status = "AVAILABLE"
            vehicle.version += 1

        await self._session.flush()

        await self._audit.create(
            entity_type="rental",
            action="COMPLETED",
            entity_id=rental.id,
            user_id=completed_by,
            old_values={"status": old_status},
            new_values={"status": "COMPLETED"},
        )

        return {"rental": rental}

    async def activate_rental(
        self,
        rental_id: UUID,
        activated_by: Optional[UUID] = None,
        lang: str = "fr",
    ) -> dict:
        """Move a rental from RESERVED to ACTIVE (vehicle pickup)."""
        rental = await self._repo.get_by_id(rental_id)
        if not rental:
            return {"error": get_message("reservation.not_found", lang)}

        if rental.status != "RESERVED":
            return {"error": "Seules les réservations peuvent être activées."}

        rental.status = "ACTIVE"
        rental.version += 1
        await self._session.flush()

        await self._audit.create(
            entity_type="rental",
            action="ACTIVATED",
            entity_id=rental.id,
            user_id=activated_by,
            old_values={"status": "RESERVED"},
            new_values={"status": "ACTIVE"},
        )

        return {"rental": rental}

    async def update_rental(
        self,
        rental_id: UUID,
        data: RentalUpdate,
        updated_by: Optional[UUID] = None,
        lang: str = "fr",
    ) -> dict:
        """Update a rental (dates, notes, etc.)."""
        rental = await self._repo.get_by_id(rental_id)
        if not rental:
            return {"error": get_message("reservation.not_found", lang)}

        if rental.status in ("COMPLETED", "CANCELLED"):
            return {"error": "Les locations terminées ou annulées ne peuvent pas être modifiées."}

        changes = {}

        if data.start_datetime and data.end_datetime:
            if data.end_datetime <= data.start_datetime:
                return {"error": get_message("reservation.invalid_dates", lang)}
            available, reason = await self._repo.check_availability(
                rental.vehicle_id, data.start_datetime, data.end_datetime,
                exclude_id=rental_id,
            )
            if not available:
                if reason == "MAINTENANCE":
                    return {"error": get_message("vehicle.in_maintenance", lang)}
                return {"error": get_message("reservation.double_booking", lang)}
            rental.start_datetime = data.start_datetime
            rental.end_datetime = data.end_datetime
            rental.num_days = self.calculate_days(data.start_datetime, data.end_datetime)
            rental.total_price = round(float(rental.daily_price) * rental.num_days, 2)
            changes["dates"] = f"{data.start_datetime} → {data.end_datetime}"

        if data.notes is not None:
            rental.notes = data.notes
            changes["notes"] = data.notes

        if data.customer_name:
            rental.customer_name = data.customer_name
            changes["customer_name"] = data.customer_name

        if data.customer_email:
            rental.customer_email = data.customer_email
            changes["customer_email"] = data.customer_email

        if data.identity_card_image:
            rental.identity_card_image = data.identity_card_image
            changes["identity_card_image"] = data.identity_card_image

        if data.driving_license_image:
            rental.driving_license_image = data.driving_license_image
            changes["driving_license_image"] = data.driving_license_image

        if data.customer_phone:
            rental.customer_phone = data.customer_phone
            changes["customer_phone"] = data.customer_phone

        rental.version += 1
        await self._session.flush()

        if changes:
            await self._audit.create(
                entity_type="rental",
                action="UPDATED",
                entity_id=rental.id,
                user_id=updated_by,
                new_values=changes,
            )

        return {"rental": rental}
