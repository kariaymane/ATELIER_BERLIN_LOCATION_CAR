from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.repositories.client_repository import ClientRepository
from app.repositories.audit_repository import AuditRepository
from app.schemas.client import ClientCreate, ClientUpdate
from app.i18n import get_message

class ClientService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = ClientRepository(session)
        self._audit = AuditRepository(session)

    async def create_client(self, data: ClientCreate, created_by: Optional[UUID] = None, lang: str = "fr") -> dict:
        client = Client(
            first_name=data.first_name.strip(),
            last_name=data.last_name.strip(),
            email=data.email.strip().lower() if data.email else None,
            phone=data.phone.strip() if data.phone else None,
            cin_number=data.cin_number.strip() if data.cin_number else None,
            identity_card_image=data.identity_card_image,
            identity_card_image_back=data.identity_card_image_back,
            license_number=data.license_number.strip() if data.license_number else None,
            driving_license_image=data.driving_license_image,
            driving_license_image_back=data.driving_license_image_back,
            photo_url=data.photo_url,
            notes=data.notes,
            status="ACTIVE",
        )
        await self._repo.create(client)
        await self._session.commit()
        await self._session.refresh(client)

        await self._audit.create(
            entity_type="client",
            action="CREATED",
            entity_id=client.id,
            user_id=created_by,
            new_values={
                "name": f"{client.first_name} {client.last_name}",
                "phone": client.phone,
                "cin": client.cin_number,
            }
        )
        return {"client": client}

    async def update_client(self, client_id: UUID, data: ClientUpdate, updated_by: Optional[UUID] = None, lang: str = "fr") -> dict:
        client = await self._repo.get_by_id(client_id)
        if not client:
            return {"error": get_message("client.not_found", lang)}

        update_data = data.model_dump(exclude_unset=True)
        old_values = {}
        new_values = {}

        for k, v in update_data.items():
            if v is not None:
                old_val = getattr(client, k)
                if old_val != v:
                    old_values[k] = str(old_val) if old_val is not None else None
                    setattr(client, k, v.strip() if isinstance(v, str) else v)
                    new_values[k] = str(v)

        client.version += 1
        await self._session.commit()
        await self._session.refresh(client)

        if new_values:
            await self._audit.create(
                entity_type="client",
                action="UPDATED",
                entity_id=client.id,
                user_id=updated_by,
                old_values=old_values,
                new_values=new_values,
            )
        return {"client": client}

    async def get_client(self, client_id: UUID, lang: str = "fr") -> dict:
        client = await self._repo.get_by_id(client_id)
        if not client:
            return {"error": get_message("client.not_found", lang)}
        return {"client": client}

    async def list_clients(self, page: int = 1, page_size: int = 25, search: Optional[str] = None, status: Optional[str] = None) -> dict:
        clients, total = await self._repo.list_filtered(page=page, page_size=page_size, search=search, status=status)
        return {
            "clients": clients,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def delete_client(self, client_id: UUID, deleted_by: Optional[UUID] = None, lang: str = "fr") -> dict:
        client = await self._repo.get_by_id(client_id)
        if not client:
            return {"error": get_message("client.not_found", lang)}

        client.status = "INACTIVE"
        client.version += 1
        await self._session.commit()

        await self._audit.create(
            entity_type="client",
            action="DEACTIVATED",
            entity_id=client.id,
            user_id=deleted_by,
        )
        return {"message": "Client désactivé avec succès"}

    async def get_client_history(self, client_id: UUID) -> list[dict]:
        client = await self._repo.get_by_id(client_id)
        if not client:
            return []
        full_name = f"{client.first_name} {client.last_name}".strip()
        return await self._repo.get_client_rentals(client_id, client_name=full_name, client_phone=client.phone)

    async def get_client_rentals_report(self, client_id: UUID) -> Optional[dict]:
        """Canonical client rental report.

        Business rules (single definition, derived from authoritative rows):
          - Eligible rental  : any reservation of this client whose status is
                               RESERVED, ACTIVE or COMPLETED (CANCELLED is
                               reported but excluded from all totals).
          - total_rentals    = COUNT(eligible)
          - total_days       = SUM(reservation.num_days) over eligible
                               (server-stored canonical duration; >= 1 day,
                               same-day rentals count as 1)
          - total_amount     = SUM(total_price) over eligible (Numeric-backed,
                               returned as float for JSON)
          - active_rentals   = eligible reservations CURRENTLY covering `now`
                               (start <= now < end) — time-derived, matching
                               the fleet "en location" rule in fleet_status.py:
                               a RESERVED reservation whose window contains
                               now counts exactly like ACTIVE, so this number
                               never contradicts the vehicle's own RENTED
                               badge elsewhere in the app.
          - completed/cancelled counts from real statuses
          - vehicles rented  = COUNT(DISTINCT vehicle_id) with per-vehicle
                               rentals/days/amount breakdown.
        """
        client = await self._repo.get_by_id(client_id)
        if not client:
            return None
        full_name = f"{client.first_name} {client.last_name}".strip()
        rentals = await self._repo.get_client_rentals(
            client_id, client_name=full_name, client_phone=client.phone
        )

        now = datetime.now(timezone.utc)

        def _parse(v):
            if not v:
                return None
            s = str(v).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        ELIGIBLE = ("RESERVED", "ACTIVE", "COMPLETED")
        summary = {
            "total_rentals": 0,
            "total_days": 0,
            "total_amount": 0.0,
            "active_rentals": 0,
            "completed_rentals": 0,
            "cancelled_rentals": 0,
            "vehicles_rented": 0,
        }
        vehicles: dict[str, dict] = {}
        for r in rentals:
            status = r["status"]
            vid = r["vehicle_id"]
            if status == "CANCELLED":
                summary["cancelled_rentals"] += 1
                continue
            if status not in ELIGIBLE:
                continue
            days = int(r.get("num_days") or 1)
            amount = float(r.get("total_price") or 0.0)
            summary["total_rentals"] += 1
            summary["total_days"] += days
            summary["total_amount"] += amount
            start = _parse(r.get("start_datetime"))
            end = _parse(r.get("end_datetime"))
            if status != "COMPLETED" and start is not None and end is not None and start <= now < end:
                summary["active_rentals"] += 1
            elif status == "COMPLETED":
                summary["completed_rentals"] += 1
            entry = vehicles.setdefault(vid, {
                "vehicle_id": vid,
                "registration": r.get("vehicle_registration") or "",
                "brand": r.get("vehicle_brand") or "",
                "model": r.get("vehicle_model") or "",
                "rentals": 0,
                "days": 0,
                "amount": 0.0,
            })
            entry["rentals"] += 1
            entry["days"] += days
            entry["amount"] += amount

        summary["vehicles_rented"] = len(vehicles)
        # Round only for presentation precision; sums are decimal-derived.
        summary["total_amount"] = round(summary["total_amount"], 2)
        vehicle_list = sorted(
            vehicles.values(), key=lambda x: x["rentals"], reverse=True
        )
        return {
            "summary": summary,
            "rentals": rentals,
            "vehicles": vehicle_list,
        }
