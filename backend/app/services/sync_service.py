"""
Sync service — handles push/pull synchronization between Desktop and PostgreSQL.
Supports idempotency, conflict detection, and version-based resolution.

This service ACTUALLY processes entity operations (CREATE/UPDATE/DELETE)
against the PostgreSQL database, not just logging them.
"""
from typing import Optional
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.models.idempotency_key import IdempotencyKey
from app.models.vehicle import Vehicle
from app.models.vehicle_image import VehicleImage
from app.models.user import User
from app.models.reservation import Reservation
from app.models.maintenance import Maintenance
from app.models.client import Client
from app.models.notification import Notification
from app.schemas.vehicle import VehicleResponse
from app.schemas.rental import RentalResponse
from app.schemas.maintenance import MaintenanceResponse
from app.schemas.notification import NotificationResponse
from app.schemas.client import ClientResponse
from app.repositories.audit_repository import AuditRepository
from app.i18n import get_message
import logging

logger = logging.getLogger(__name__)


def _as_utc(dt):
    """Coerce a (possibly naive) datetime to aware UTC. Naive == UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _maintenance_active_now(m) -> bool:
    """True only when maintenance ``m`` occupies the vehicle at this instant —
    the ONLY condition under which the raw ``vehicle.status`` MAINTENANCE hold
    may be set. A future-dated ticket returns False; the canonical effective
    status flips it via the interval rule when the window opens."""
    if (getattr(m, "status", None) or "").upper() in ("CANCELLED", "COMPLETED"):
        return False
    start = _as_utc(getattr(m, "start_datetime", None))
    if start is None:
        return False
    end = _as_utc(getattr(m, "expected_end_datetime", None)
                  or getattr(m, "actual_end_datetime", None))
    now = datetime.now(timezone.utc)
    return start <= now and (end is None or end > now)


class SyncService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._audit = AuditRepository(session)

    async def check_idempotency(self, key: str) -> Optional[dict]:
        """Check if an operation with this key was already processed."""
        result = await self._session.execute(
            select(IdempotencyKey).where(IdempotencyKey.key == key)
        )
        existing = result.scalar_one_or_none()
        if existing and existing.response_body:
            return existing.response_body
        return None

    async def store_idempotency(
        self, key: str, endpoint: str, status_code: str, response: dict
    ):
        """Store an idempotency record for a processed operation."""
        record = IdempotencyKey(
            key=key,
            endpoint=endpoint,
            status_code=status_code,
            response_body=response,
        )
        self._session.add(record)
        await self._session.flush()

    async def _process_vehicle_create(self, payload: dict, user_id: UUID) -> dict:
        """Create a vehicle from sync payload."""
        try:
            vehicle_id = payload.get("id")
            # Check if vehicle already exists (re-sync)
            if vehicle_id:
                existing = await self._session.execute(
                    select(Vehicle).where(Vehicle.id == UUID(vehicle_id))
                )
                if existing.scalar_one_or_none():
                    return {"status": "ok", "message": "Already exists", "server_version": 1}

            raw_fuel = payload.get("fuel_type", "GASOLINE").upper()
            if "ESSENCE" in raw_fuel or "GASOLINE" in raw_fuel:
                fuel_type = "GASOLINE"
            elif "DIESEL" in raw_fuel:
                fuel_type = "DIESEL"
            elif "HYBRID" in raw_fuel or "HYBRIDE" in raw_fuel:
                fuel_type = "HYBRID"
            elif "ELECTR" in raw_fuel:
                fuel_type = "ELECTRIC"
            else:
                fuel_type = "GASOLINE"

            raw_trans = payload.get("transmission", "AUTOMATIC").upper()
            transmission = "MANUAL" if "MANU" in raw_trans else "AUTOMATIC"

            vehicle = Vehicle(
                id=UUID(vehicle_id) if vehicle_id else None,
                registration=payload["registration"],
                vin=payload["vin"],
                brand=payload["brand"],
                model=payload["model"],
                year=payload["year"],
                color=payload.get("color", "Noir"),
                fuel_type=fuel_type,
                transmission=transmission,
                current_mileage=payload.get("current_mileage", 0),
                purchase_mileage=payload.get("purchase_mileage", 0),
                purchase_price=payload.get("purchase_price", 0),
                daily_rental_price=payload.get("daily_rental_price", 0),
                purchase_date=None,
                notes=payload.get("notes"),
                assurance_expiry=datetime.fromisoformat(payload["assurance_expiry"]) if payload.get("assurance_expiry") else None,
                vignette_expiry=datetime.fromisoformat(payload["vignette_expiry"]) if payload.get("vignette_expiry") else None,
                visite_technique_expiry=datetime.fromisoformat(payload["visite_technique_expiry"]) if payload.get("visite_technique_expiry") else None,
                carte_grise_expiry=datetime.fromisoformat(payload["carte_grise_expiry"]) if payload.get("carte_grise_expiry") else None,
                autres_expiry=datetime.fromisoformat(payload["autres_expiry"]) if payload.get("autres_expiry") else None,
                autres_label=payload.get("autres_label"),
                image_url=payload.get("image_url"),
                created_by=user_id,
            )
            self._session.add(vehicle)
            await self._session.flush()

            # Sync individual vehicle photos
            raw_images = payload.get("images") or []
            if not raw_images and payload.get("image_url"):
                raw_images = [u.strip() for u in payload["image_url"].split(",") if u.strip()]
            for idx, img in enumerate(raw_images):
                img_url = img if isinstance(img, str) else img.get("image_url", "")
                if img_url:
                    v_img = VehicleImage(
                        vehicle_id=vehicle.id,
                        image_url=img_url,
                        sort_order=idx
                    )
                    self._session.add(v_img)
            await self._session.flush()

            await self._audit.create(
                entity_type="vehicle",
                action="CREATED",
                entity_id=vehicle.id,
                user_id=user_id,
                new_values={
                    "registration": vehicle.registration,
                    "source": "sync",
                },
            )

            logger.info("Sync created vehicle: %s (%s)", vehicle.registration, vehicle.id)
            return {"status": "ok", "server_version": vehicle.version}

        except IntegrityError as e:
            error_str = str(e.orig) if e.orig else str(e)
            logger.warning("Sync vehicle create integrity error: %s", error_str)
            if "registration" in error_str.lower() or "vin" in error_str.lower():
                return {"status": "conflict", "message": "Duplicate registration or VIN"}
            return {"status": "error", "message": "Database constraint violation"}
        except Exception as e:
            raise

    async def _process_vehicle_update(self, entity_id: str, payload: dict, user_id: UUID, client_version: int) -> dict:
        """Update a vehicle from sync payload with version checking."""
        try:
            result = await self._session.execute(
                select(Vehicle).where(Vehicle.id == UUID(entity_id))
            )
            vehicle = result.scalar_one_or_none()

            if not vehicle:
                return {"status": "error", "message": "Vehicle not found"}

            # Optimistic concurrency check
            if vehicle.version > client_version:
                logger.warning(
                    "Sync conflict: vehicle %s server_version=%d > client_version=%d",
                    entity_id, vehicle.version, client_version
                )
                return {
                    "status": "conflict",
                    "message": "Server has a newer version",
                    "server_version": vehicle.version,
                }

            # Apply updates
            updatable = [
                "registration", "brand", "model", "year", "color",
                "fuel_type", "transmission", "current_mileage",
                "purchase_price", "daily_rental_price", "notes", "status",
                "assurance_expiry", "vignette_expiry", "visite_technique_expiry",
                "carte_grise_expiry", "autres_expiry", "autres_label", "image_url"
            ]
            for field in updatable:
                if field in payload and payload[field] is not None:
                    val = payload[field]
                    if field.endswith("_expiry") or field.endswith("_date"):
                        if isinstance(val, str) and val:
                            from datetime import datetime
                            val = datetime.fromisoformat(val.replace("Z", "+00:00")).date()
                    setattr(vehicle, field, val)

            if "images" in payload or "image_url" in payload:
                await self._session.execute(delete(VehicleImage).where(VehicleImage.vehicle_id == vehicle.id))
                raw_images = payload.get("images") or []
                if not raw_images and payload.get("image_url"):
                    raw_images = [u.strip() for u in payload["image_url"].split(",") if u.strip()]
                for idx, img in enumerate(raw_images):
                    img_url = img if isinstance(img, str) else img.get("image_url", "")
                    if img_url:
                        v_img = VehicleImage(
                            vehicle_id=vehicle.id,
                            image_url=img_url,
                            sort_order=idx
                        )
                        self._session.add(v_img)

            vehicle.version += 1
            await self._session.flush()

            await self._audit.create(
                entity_type="vehicle",
                action="UPDATED",
                entity_id=vehicle.id,
                user_id=user_id,
                new_values={"source": "sync", "fields": list(payload.keys())},
            )

            logger.info("Sync updated vehicle: %s (version=%d)", entity_id, vehicle.version)
            return {"status": "ok", "server_version": vehicle.version}

        except IntegrityError as e:
            return {"status": "conflict", "message": "Constraint violation on update"}
        except Exception as e:
            raise

    async def _process_vehicle_delete(self, entity_id: str, user_id: UUID) -> dict:
        """Delete a vehicle from sync."""
        try:
            result = await self._session.execute(
                select(Vehicle).where(Vehicle.id == UUID(entity_id))
            )
            vehicle = result.scalar_one_or_none()

            if not vehicle:
                return {"status": "ok", "message": "Already deleted"}

            # Clean up dependent child records to satisfy FK RESTRICT
            await self._session.execute(delete(Maintenance).where(Maintenance.vehicle_id == UUID(entity_id)))
            await self._session.execute(delete(Reservation).where(Reservation.vehicle_id == UUID(entity_id)))

            await self._audit.create(
                entity_type="vehicle",
                action="DELETED",
                entity_id=vehicle.id,
                user_id=user_id,
                old_values={"registration": vehicle.registration, "source": "sync"},
            )

            await self._session.delete(vehicle)
            await self._session.flush()

            logger.info("Sync deleted vehicle: %s", entity_id)
            return {"status": "ok"}

        except Exception as e:
            raise

    async def _process_maintenance_delete(self, entity_id: str, user_id: UUID) -> dict:
        """Delete a maintenance record from sync payload."""
        try:
            m = (await self._session.execute(select(Maintenance).where(Maintenance.id == UUID(entity_id)))).scalar_one_or_none()
            if m:
                if m.status == "ACTIVE":
                    v = (await self._session.execute(select(Vehicle).where(Vehicle.id == m.vehicle_id))).scalar_one_or_none()
                    if v and v.status == "MAINTENANCE":
                        v.status = "AVAILABLE"
                        v.version += 1
                await self._session.delete(m)
                await self._session.flush()
            return {"status": "ok"}
        except Exception as e:
            raise

    async def _process_reservation_create(self, payload: dict, user_id: UUID) -> dict:
        try:
            res_id = payload.get("id")
            if res_id:
                existing = await self._session.execute(select(Reservation).where(Reservation.id == UUID(res_id)))
                if existing.scalar_one_or_none():
                    return {"status": "ok", "message": "Already exists", "server_version": 1}

            res = Reservation(
                id=UUID(res_id) if res_id else None,
                vehicle_id=UUID(payload["vehicle_id"]),
                customer_id=UUID(payload["customer_id"]) if payload.get("customer_id") else None,
                customer_name=payload.get("customer_name"),
                customer_phone=payload.get("customer_phone"),
                customer_email=payload.get("customer_email"),
                identity_card_image=payload.get("identity_card_image"),
                driving_license_image=payload.get("driving_license_image"),
                start_datetime=datetime.fromisoformat(payload["start_datetime"]),
                end_datetime=datetime.fromisoformat(payload["end_datetime"]),
                daily_price=payload.get("daily_price", 0),
                num_days=payload.get("num_days", 1),
                total_price=payload.get("total_price", 0),
                deposit=payload.get("deposit", 0),
                payment_status=payload.get("payment_status", "PENDING"),
                status=payload.get("status", "RESERVED"),
                created_by=user_id
            )
            self._session.add(res)
            await self._session.flush()
            return {"status": "ok", "server_version": res.version}
        except IntegrityError as e:
            if "excl_reservations_no_overlap" in str(e):
                return {"status": "conflict", "message": "Double booking detected"}
            if "Vehicle is in maintenance" in str(e):
                return {"status": "conflict", "message": "Vehicle is in maintenance"}
            return {"status": "error", "message": "Constraint violation"}
        except Exception as e:
            raise

    async def _process_reservation_update(self, entity_id: str, payload: dict, user_id: UUID, client_version: int) -> dict:
        try:
            res = (await self._session.execute(select(Reservation).where(Reservation.id == UUID(entity_id)))).scalar_one_or_none()
            if not res: return {"status": "error", "message": "Not found"}
            if res.version > client_version: return {"status": "conflict", "server_version": res.version}

            if "status" in payload: res.status = payload["status"]
            if "cancellation_reason" in payload:
                res.cancellation_reason = payload["cancellation_reason"]
            res.version += 1
            await self._session.flush()
            return {"status": "ok", "server_version": res.version}
        except Exception as e:
            raise

    async def _process_maintenance_create(self, payload: dict, user_id: UUID) -> dict:
        try:
            m_id = payload.get("id")
            if m_id:
                existing = await self._session.execute(select(Maintenance).where(Maintenance.id == UUID(m_id)))
                if existing.scalar_one_or_none():
                    return {"status": "ok", "message": "Already exists", "server_version": 1}

            m = Maintenance(
                id=UUID(m_id) if m_id else None,
                vehicle_id=UUID(payload["vehicle_id"]),
                type=payload.get("type", "Autre"),
                description=payload.get("description"),
                start_datetime=datetime.fromisoformat(payload["start_datetime"]),
                expected_end_datetime=datetime.fromisoformat(payload.get("expected_end_datetime")) if payload.get("expected_end_datetime") else None,
                estimated_cost=payload.get("estimated_cost", 0),
                step=payload.get("step", "DIAGNOSTIC"),
                status=payload.get("status", "ACTIVE"),
                created_by=user_id
            )
            self._session.add(m)
            await self._session.flush()

            cancelled_ids: list[str] = []
            if (m.status or "").upper() not in ("CANCELLED", "COMPLETED"):
                v = (await self._session.execute(select(Vehicle).where(Vehicle.id == m.vehicle_id))).scalar_one_or_none()
                # Raw MAINTENANCE hold ONLY for a currently-active window — a
                # future-dated ticket must not create a second status authority
                # that contradicts the canonical derivation (forensic P0-B).
                if v and v.status not in ("SOLD", "INACTIVE") and _maintenance_active_now(m):
                    v.status = "MAINTENANCE"
                    v.version += 1
                # CANONICAL: maintenance wins — cancel overlapping reservations
                # atomically inside this savepoint.
                from app.repositories.rental_repository import RentalRepository
                maint_end = m.expected_end_datetime or m.actual_end_datetime  # None => open-ended (helper applies FAR_FUTURE)
                cancelled = await RentalRepository(self._session).cancel_overlapping_reservations(
                    m.vehicle_id, m.start_datetime, maint_end
                )
                cancelled_ids = [str(r.id) for r in cancelled]

            await self._session.flush()
            return {
                "status": "ok",
                "server_version": m.version,
                "cancelled_reservation_ids": cancelled_ids,
            }
        except IntegrityError as e:
            return {"status": "error", "message": "Constraint violation"}
        except Exception as e:
            raise

    async def _process_maintenance_update(self, entity_id: str, payload: dict, user_id: UUID, client_version: int) -> dict:
        try:
            m = (await self._session.execute(select(Maintenance).where(Maintenance.id == UUID(entity_id)))).scalar_one_or_none()
            if not m: return {"status": "error", "message": "Not found"}
            if m.version > client_version: return {"status": "conflict", "server_version": m.version}

            prev_status = (m.status or "").upper()
            for field in ["step", "status", "actual_end_datetime"]:
                if field in payload:
                    val = datetime.fromisoformat(payload[field]) if field.endswith("datetime") and payload[field] else payload[field]
                    setattr(m, field, val)

            new_status = (m.status or "").upper()
            cancelled_ids: list[str] = []
            if "status" in payload and new_status in ["COMPLETED", "CANCELLED"]:
                v = (await self._session.execute(select(Vehicle).where(Vehicle.id == m.vehicle_id))).scalar_one_or_none()
                if v and v.status == "MAINTENANCE":
                    v.status = "AVAILABLE"
                    v.version += 1
            elif prev_status in ("CANCELLED", "COMPLETED", "SCHEDULED") and new_status not in ("CANCELLED", "COMPLETED"):
                # Ticket (re)activated — maintenance wins.
                v = (await self._session.execute(select(Vehicle).where(Vehicle.id == m.vehicle_id))).scalar_one_or_none()
                # Raw MAINTENANCE hold only for a currently-active window.
                if v and v.status not in ("SOLD", "INACTIVE") and _maintenance_active_now(m):
                    v.status = "MAINTENANCE"
                    v.version += 1
                from app.repositories.rental_repository import RentalRepository
                maint_end = m.expected_end_datetime or m.actual_end_datetime  # None => open-ended (helper applies FAR_FUTURE)
                cancelled = await RentalRepository(self._session).cancel_overlapping_reservations(
                    m.vehicle_id, m.start_datetime, maint_end
                )
                cancelled_ids = [str(r.id) for r in cancelled]

            m.version += 1
            await self._session.flush()
            return {"status": "ok", "server_version": m.version, "cancelled_reservation_ids": cancelled_ids}
        except Exception as e:
            raise

    async def _process_client_create(self, payload: dict, user_id: UUID) -> dict:
        try:
            cid = UUID(payload["id"]) if "id" in payload and payload["id"] else None
            client = Client(
                id=cid,
                first_name=payload.get("first_name", "").strip(),
                last_name=payload.get("last_name", "").strip(),
                email=payload.get("email", "").strip().lower() if payload.get("email") else None,
                phone=payload.get("phone", "").strip() if payload.get("phone") else None,
                cin_number=payload.get("cin_number", "").strip() if payload.get("cin_number") else None,
                identity_card_image=payload.get("identity_card_image"),
                identity_card_image_back=payload.get("identity_card_image_back"),
                license_number=payload.get("license_number", "").strip() if payload.get("license_number") else None,
                driving_license_image=payload.get("driving_license_image"),
                driving_license_image_back=payload.get("driving_license_image_back"),
                photo_url=payload.get("photo_url"),
                notes=payload.get("notes"),
                status=payload.get("status", "ACTIVE"),
            )
            self._session.add(client)
            await self._session.flush()
            return {"status": "ok", "server_version": client.version}
        except IntegrityError:
            return {"status": "conflict", "message": "Client already exists or constraint violation"}
        except Exception as e:
            raise

    async def _process_client_update(self, entity_id: str, payload: dict, user_id: UUID, client_version: int) -> dict:
        try:
            client = (await self._session.execute(select(Client).where(Client.id == UUID(entity_id)))).scalar_one_or_none()
            if not client:
                return {"status": "error", "message": "Client not found"}
            if client.version > client_version:
                return {"status": "conflict", "server_version": client.version}

            for field in ["first_name", "last_name", "email", "phone", "cin_number", "identity_card_image", "identity_card_image_back", "license_number", "driving_license_image", "driving_license_image_back", "photo_url", "notes", "status"]:
                if field in payload and payload[field] is not None:
                    setattr(client, field, payload[field])

            client.version += 1
            await self._session.flush()
            return {"status": "ok", "server_version": client.version}
        except Exception as e:
            raise

    async def _process_client_delete(self, entity_id: str, user_id: UUID) -> dict:
        try:
            client = (await self._session.execute(select(Client).where(Client.id == UUID(entity_id)))).scalar_one_or_none()
            if not client:
                return {"status": "ok", "message": "Already deleted"}
            client.status = "INACTIVE"
            client.version += 1
            await self._session.flush()
            return {"status": "ok", "server_version": client.version}
        except Exception as e:
            raise

    async def process_push(
        self,
        items: list,
        user_id: UUID,
        lang: str = "fr",
    ) -> list[dict]:
        """
        Process sync push items from Desktop.
        Each item is validated, checked for conflicts, and ACTUALLY applied to PostgreSQL.
        """
        results = []

        for item in items:
            # Check idempotency
            cached = await self.check_idempotency(item.idempotency_key)
            if cached:
                results.append({
                    "entity_id": item.entity_id,
                    "status": "ok",
                    "message": get_message("sync.idempotency_duplicate", lang),
                    "server_version": cached.get("server_version"),
                })
                continue

            try:
                async with self._session.begin_nested():
                    # Route to the correct entity handler
                    result = None
                    entity_type = item.entity_type.lower()
                    operation = item.operation.upper()

                    if entity_type == "vehicle":
                        if operation == "CREATE":
                            result = await self._process_vehicle_create(item.payload, user_id)
                        elif operation == "UPDATE":
                            result = await self._process_vehicle_update(
                                item.entity_id, item.payload, user_id, item.version
                            )
                        elif operation == "DELETE":
                            result = await self._process_vehicle_delete(item.entity_id, user_id)
                        else:
                            result = {"status": "error", "message": f"Unknown operation: {operation}"}
                    elif entity_type == "reservation":
                        if operation == "CREATE":
                            result = await self._process_reservation_create(item.payload, user_id)
                        elif operation == "UPDATE":
                            result = await self._process_reservation_update(item.entity_id, item.payload, user_id, item.version)
                        else:
                            result = {"status": "error", "message": "Not supported"}
                    elif entity_type == "client":
                        if operation == "CREATE":
                            result = await self._process_client_create(item.payload, user_id)
                        elif operation == "UPDATE":
                            result = await self._process_client_update(item.entity_id, item.payload, user_id, item.version)
                        elif operation == "DELETE":
                            result = await self._process_client_delete(item.entity_id, user_id)
                        else:
                            result = {"status": "error", "message": "Not supported"}
                    elif entity_type == "maintenance":
                        if operation == "CREATE":
                            result = await self._process_maintenance_create(item.payload, user_id)
                        elif operation == "UPDATE":
                            result = await self._process_maintenance_update(item.entity_id, item.payload, user_id, item.version)
                        elif operation == "DELETE":
                            result = await self._process_maintenance_delete(item.entity_id, user_id)
                        else:
                            result = {"status": "error", "message": "Not supported"}
                    else:
                        logger.warning("Sync push for unsupported entity type: %s", entity_type)
                        result = {"status": "ok", "message": f"Entity type '{entity_type}' accepted"}

                    result["entity_id"] = item.entity_id

                    # Store idempotency
                    await self.store_idempotency(
                        key=item.idempotency_key,
                        endpoint=f"sync/push/{item.entity_type}",
                        status_code="200" if result["status"] == "ok" else "409",
                        response=result,
                    )

                    await self._audit.create(
                        entity_type="sync",
                        action="SYNC_PUSH",
                        entity_id=UUID(item.entity_id) if item.entity_id else None,
                        user_id=user_id,
                        new_values={
                            "entity_type": item.entity_type,
                            "operation": item.operation,
                            "device_id": item.device_id,
                            "result_status": result["status"],
                        },
                    )
            except Exception as e:
                # Catch integrity errors or unexpected errors that failed the savepoint
                logger.error("Sync item processing failed: %s", e)
                result = {
                    "entity_id": item.entity_id,
                    "status": "error",
                    "message": str(e)
                }

            results.append(result)

        return results

    async def process_pull(
        self,
        since: datetime,
        entity_types: Optional[list[str]] = None,
        device_id: Optional[str] = None,
        user_id: Optional[UUID] = None,
        lang: str = "fr",
    ) -> dict:
        """
        Pull changes from server since a given timestamp.
        Returns changed vehicle entities for the Desktop to merge.
        """
        items = []
        server_time = datetime.now(timezone.utc)

        # Pull vehicles updated since 'since'
        if not entity_types or "vehicle" in entity_types:
            result = await self._session.execute(
                select(Vehicle).where(Vehicle.updated_at >= since)
            )
            vehicles = result.scalars().all()
            from app.services.fleet_status import compute_effective_statuses
            _eff = await compute_effective_statuses(
                self._session, vehicle_ids=[v.id for v in vehicles]
            ) if vehicles else {}
            for v in vehicles:
                items.append({
                    "entity_type": "vehicle",
                    "entity_id": str(v.id),
                    "operation": "UPDATE",
                    "payload": {
                        "id": str(v.id),
                        "effective_status": _eff.get(str(v.id), v.status),
                        "registration": v.registration,
                        "vin": v.vin,
                        "brand": v.brand,
                        "model": v.model,
                        "year": v.year,
                        "color": v.color,
                        "fuel_type": v.fuel_type,
                        "transmission": v.transmission,
                        "current_mileage": v.current_mileage,
                        "purchase_mileage": v.purchase_mileage,
                        "purchase_price": float(v.purchase_price) if v.purchase_price else 0,
                        "daily_rental_price": float(v.daily_rental_price) if v.daily_rental_price else 0,
                        "status": v.status,
                        "notes": v.notes,
                        "assurance_expiry": v.assurance_expiry.isoformat() if v.assurance_expiry else None,
                        "vignette_expiry": v.vignette_expiry.isoformat() if v.vignette_expiry else None,
                        "visite_technique_expiry": v.visite_technique_expiry.isoformat() if v.visite_technique_expiry else None,
                        "carte_grise_expiry": v.carte_grise_expiry.isoformat() if v.carte_grise_expiry else None,
                        "autres_expiry": v.autres_expiry.isoformat() if v.autres_expiry else None,
                        "autres_label": v.autres_label,
                        "image_url": v.image_url,
                    },
                    "version": v.version,
                    "updated_at": v.updated_at.isoformat() if v.updated_at else server_time.isoformat(),
                })

        if not entity_types or "reservation" in entity_types:
            result = await self._session.execute(select(Reservation).where(Reservation.updated_at >= since))
            for r in result.scalars().all():
                items.append({
                    "entity_type": "reservation", "entity_id": str(r.id), "operation": "UPDATE",
                    "payload": {
                        "id": str(r.id), "vehicle_id": str(r.vehicle_id),
                        "customer_id": str(r.customer_id) if r.customer_id else None,
                        "customer_name": r.customer_name,
                        "customer_phone": r.customer_phone, "customer_email": r.customer_email, "identity_card_image": r.identity_card_image, "driving_license_image": r.driving_license_image, "start_datetime": r.start_datetime.isoformat(),
                        "end_datetime": r.end_datetime.isoformat(), "daily_price": float(r.daily_price),
                        "num_days": r.num_days, "total_price": float(r.total_price), "deposit": float(r.deposit),
                        "payment_status": r.payment_status, "status": r.status,
                        "cancellation_reason": r.cancellation_reason,
                    },
                    "version": r.version, "updated_at": r.updated_at.isoformat()
                })

        if not entity_types or "maintenance" in entity_types:
            result = await self._session.execute(select(Maintenance).where(Maintenance.updated_at >= since))
            for m in result.scalars().all():
                items.append({
                    "entity_type": "maintenance", "entity_id": str(m.id), "operation": "UPDATE",
                    "payload": {
                        "id": str(m.id), "vehicle_id": str(m.vehicle_id), "type": m.type,
                        "description": m.description, "start_datetime": m.start_datetime.isoformat(),
                        "expected_end_datetime": m.expected_end_datetime.isoformat() if m.expected_end_datetime else None,
                        "actual_end_datetime": m.actual_end_datetime.isoformat() if m.actual_end_datetime else None,
                        "estimated_cost": float(m.estimated_cost) if m.estimated_cost else 0,
                        "step": m.step, "status": m.status,
                    },
                    "version": m.version, "updated_at": m.updated_at.isoformat()
                })

        if not entity_types or "client" in entity_types:
            result = await self._session.execute(select(Client).where(Client.updated_at >= since))
            for c in result.scalars().all():
                items.append({
                    "entity_type": "client", "entity_id": str(c.id), "operation": "UPDATE",
                    "payload": {
                        "id": str(c.id), "first_name": c.first_name, "last_name": c.last_name,
                        "email": c.email, "phone": c.phone, "cin_number": c.cin_number,
                        "identity_card_image": c.identity_card_image,
                        "identity_card_image_back": c.identity_card_image_back,
                        "license_number": c.license_number,
                        "driving_license_image": c.driving_license_image,
                        "driving_license_image_back": c.driving_license_image_back,
                        "photo_url": c.photo_url, "notes": c.notes, "status": c.status,
                    },
                    "version": c.version, "updated_at": c.updated_at.isoformat()
                })

        if user_id:
            await self._audit.create(
                entity_type="sync",
                action="SYNC_PULL",
                user_id=user_id,
                new_values={
                    "since": since.isoformat(),
                    "device_id": device_id,
                    "items_count": len(items),
                },
            )

        # Fetch hard deletions from AuditLog
        from app.models.audit_log import AuditLog
        audit_result = await self._session.execute(
            select(AuditLog).where(
                AuditLog.action == "DELETED",
                AuditLog.created_at >= since
            )
        )
        for log in audit_result.scalars().all():
            if not entity_types or log.entity_type.lower() in entity_types:
                items.append({
                    "entity_type": log.entity_type.lower(),
                    "entity_id": str(log.entity_id),
                    "operation": "DELETE",
                    "payload": {},
                    "version": 1,
                    "updated_at": log.created_at.isoformat(),
                })

        return {
            "items": items,
            "server_time": server_time,
        }

    async def get_bootstrap(self, user_id: Optional[UUID] = None) -> dict:
        """
        Authoritative snapshot containing all vehicles, rentals, maintenances, and notifications.
        Used for atomic initial bootstrap of ATELIER BERLIN LOCATION CAR Mobile and Desktop sync.
        """
        server_time = datetime.now(timezone.utc)

        # 1. Fetch Vehicles
        from sqlalchemy.orm import selectinload
        v_res = await self._session.execute(select(Vehicle).options(selectinload(Vehicle.images)).order_by(Vehicle.created_at.desc()))
        vehicles = v_res.scalars().all()
        from app.services.fleet_status import compute_effective_statuses
        _eff = await compute_effective_statuses(
            self._session, vehicle_ids=[v.id for v in vehicles]
        ) if vehicles else {}
        vehicle_responses = [
            VehicleResponse(
                id=str(v.id),
                effective_status=_eff.get(str(v.id), v.status),
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
                purchase_price=float(v.purchase_price) if v.purchase_price is not None else 0.0,
                daily_rental_price=float(v.daily_rental_price) if v.daily_rental_price is not None else 0.0,
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
                images=[{"id": img.id, "vehicle_id": img.vehicle_id, "image_url": img.image_url, "sort_order": img.sort_order, "created_at": img.created_at} for img in v.images] if v.images else [],
                created_at=v.created_at,
                updated_at=v.updated_at,
                version=v.version,
            )
            for v in vehicles
        ]
        v_map = {str(v.id): v for v in vehicles}

        # 2. Fetch Rentals with joined vehicle info
        r_res = await self._session.execute(select(Reservation).order_by(Reservation.created_at.desc()))
        rentals = r_res.scalars().all()
        rental_responses = []
        for r in rentals:
            veh = v_map.get(str(r.vehicle_id))
            r_resp = RentalResponse(
                id=str(r.id),
                vehicle_id=str(r.vehicle_id),
                customer_name=r.customer_name,
                customer_phone=r.customer_phone,
                customer_email=r.customer_email,
                identity_card_image=r.identity_card_image,
                driving_license_image=r.driving_license_image,
                start_datetime=r.start_datetime,
                end_datetime=r.end_datetime,
                daily_price=float(r.daily_price),
                num_days=r.num_days,
                total_price=float(r.total_price),
                deposit=float(r.deposit),
                payment_status=r.payment_status,
                status=r.status,
                cancellation_reason=r.cancellation_reason,
                notes=r.notes,
                created_at=r.created_at,
                updated_at=r.updated_at,
                version=r.version,
                vehicle_registration=veh.registration if veh else None,
                vehicle_brand=veh.brand if veh else None,
                vehicle_model=veh.model if veh else None,
            )
            rental_responses.append(r_resp)

        # 3. Fetch Maintenance with joined vehicle info
        m_res = await self._session.execute(select(Maintenance).order_by(Maintenance.created_at.desc()))
        maintenances = m_res.scalars().all()
        maintenance_responses = []
        for m in maintenances:
            veh = v_map.get(str(m.vehicle_id))
            m_resp = MaintenanceResponse(
                id=m.id,
                vehicle_id=m.vehicle_id,
                type=m.type,
                description=m.description,
                start_datetime=m.start_datetime,
                expected_end_datetime=m.expected_end_datetime,
                actual_end_datetime=m.actual_end_datetime,
                mileage=m.mileage,
                location=m.location,
                estimated_cost=float(m.estimated_cost) if m.estimated_cost else None,
                actual_cost=float(m.actual_cost) if m.actual_cost else None,
                step=m.step,
                status=m.status,
                notes=m.notes,
                created_by=m.created_by,
                created_at=m.created_at,
                updated_at=m.updated_at,
                version=m.version,
                vehicle_brand=veh.brand if veh else None,
                vehicle_model=veh.model if veh else None,
                vehicle_registration=veh.registration if veh else None,
                vehicle_image_url=veh.image_url if veh else None,
            )
            maintenance_responses.append(m_resp)

        # 4. Fetch Notifications
        n_res = await self._session.execute(select(Notification).order_by(Notification.created_at.desc()))
        notifications = n_res.scalars().all()
        notification_responses = []
        for n in notifications:
            veh = v_map.get(str(n.vehicle_id)) if n.vehicle_id else None
            n_resp = NotificationResponse(
                id=str(n.id),
                vehicle_id=str(n.vehicle_id) if n.vehicle_id else None,
                vehicle_name=f"{veh.brand} {veh.model}" if veh else None,
                vehicle_registration=veh.registration if veh else None,
                type=n.type,
                severity=n.severity,
                title=n.title,
                message=n.message,
                due_date=n.due_date,
                is_read=n.is_read,
                created_at=n.created_at,
            )
            notification_responses.append(n_resp)

        # 5. Fetch Clients
        c_res = await self._session.execute(select(Client).where(Client.status != "DELETED").order_by(Client.last_name.asc(), Client.first_name.asc()))
        clients = c_res.scalars().all()
        client_responses = []
        for c in clients:
            c_resp = ClientResponse(
                id=str(c.id),
                first_name=c.first_name,
                last_name=c.last_name,
                email=c.email,
                phone=c.phone,
                cin_number=c.cin_number,
                identity_card_image=c.identity_card_image,
                identity_card_image_back=c.identity_card_image_back,
                license_number=c.license_number,
                driving_license_image=c.driving_license_image,
                driving_license_image_back=c.driving_license_image_back,
                photo_url=c.photo_url,
                notes=c.notes,
                status=c.status,
                created_at=c.created_at,
                updated_at=c.updated_at,
                version=c.version,
            )
            client_responses.append(c_resp)

        # Monotonic authoritative revision = latest updated_at (epoch-ms UTC)
        # across every temporally-relevant row in this snapshot. `updated_at`
        # only ever moves forward, so this is monotonic; it lets a client
        # distinguish "complete through revision N" from a stale/partial cache
        # and reject applying an older snapshot over a newer one.
        def _rev_ms(row) -> int:
            ts = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
            if ts is None:
                return 0
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return int(ts.timestamp() * 1000)

        revision = 0
        for _row in (*vehicles, *rentals, *maintenances):
            revision = max(revision, _rev_ms(_row))

        if user_id:
            await self._audit.create(
                entity_type="sync",
                action="SYNC_BOOTSTRAP",
                user_id=user_id,
                new_values={
                    "vehicles_count": len(vehicle_responses),
                    "rentals_count": len(rental_responses),
                    "maintenance_count": len(maintenance_responses),
                    "notifications_count": len(notification_responses),
                    "clients_count": len(client_responses),
                },
            )

        return {
            "sync_version": 1,
            "revision": revision,
            "server_time": server_time,
            "server_id": "car-rental-server-v1",
            "api_version": "1.0.0",
            "vehicles": vehicle_responses,
            "rentals": rental_responses,
            "clients": client_responses,
            "maintenance": maintenance_responses,
            "notifications": notification_responses,
        }
