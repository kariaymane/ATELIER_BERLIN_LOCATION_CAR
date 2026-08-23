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
            license_number=data.license_number.strip() if data.license_number else None,
            driving_license_image=data.driving_license_image,
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
