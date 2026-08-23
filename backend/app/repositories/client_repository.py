from typing import Optional
from uuid import UUID
from sqlalchemy import select, func, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.reservation import Reservation
from app.models.vehicle import Vehicle
from app.repositories.base import BaseRepository

class ClientRepository(BaseRepository[Client]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Client)

    async def list_filtered(
        self,
        page: int = 1,
        page_size: int = 25,
        search: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[list[Client], int]:
        filters = []
        if status:
            filters.append(Client.status == status)
        if search:
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    Client.first_name.ilike(term),
                    Client.last_name.ilike(term),
                    Client.phone.ilike(term),
                    Client.email.ilike(term),
                    Client.cin_number.ilike(term),
                    Client.license_number.ilike(term),
                )
            )

        query = select(Client)
        count_query = select(func.count(Client.id))

        if filters:
            for f in filters:
                query = query.where(f)
                count_query = count_query.where(f)

        total_res = await self._session.execute(count_query)
        total = total_res.scalar() or 0

        query = query.order_by(Client.last_name.asc(), Client.first_name.asc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self._session.execute(query)
        clients = list(result.scalars().all())
        return clients, total

    async def get_by_phone(self, phone: str) -> Optional[Client]:
        if not phone:
            return None
        res = await self._session.execute(select(Client).where(Client.phone == phone.strip()))
        return res.scalar_one_or_none()

    async def get_by_cin(self, cin: str) -> Optional[Client]:
        if not cin:
            return None
        res = await self._session.execute(select(Client).where(Client.cin_number == cin.strip()))
        return res.scalar_one_or_none()

    async def get_client_rentals(self, client_id: Optional[UUID], client_name: Optional[str] = None, client_phone: Optional[str] = None) -> list[dict]:
        """Fetch all rentals belonging to this client, including vehicle details."""
        conds = []
        if client_id:
            conds.append(Reservation.customer_id == client_id)
        if client_name and client_phone:
            conds.append(
                or_(
                    Reservation.customer_phone == client_phone,
                    Reservation.customer_name.ilike(f"%{client_name.strip()}%")
                )
            )

        if not conds:
            return []

        stmt = (
            select(Reservation, Vehicle)
            .outerjoin(Vehicle, Reservation.vehicle_id == Vehicle.id)
            .where(or_(*conds))
            .order_by(desc(Reservation.start_datetime))
        )
        res = await self._session.execute(stmt)
        rows = res.all()

        results = []
        for r, v in rows:
            results.append({
                "id": str(r.id),
                "vehicle_id": str(r.vehicle_id),
                "vehicle_brand": v.brand if v else "",
                "vehicle_model": v.model if v else "",
                "vehicle_registration": v.registration if v else "",
                "vehicle_image_url": v.image_url if v else None,
                "customer_name": r.customer_name,
                "customer_phone": r.customer_phone,
                "customer_email": r.customer_email,
                "start_datetime": r.start_datetime.isoformat() if r.start_datetime else None,
                "end_datetime": r.end_datetime.isoformat() if r.end_datetime else None,
                "daily_price": float(r.daily_price or 0),
                "num_days": int(r.num_days or 1),
                "total_price": float(r.total_price or 0),
                "deposit": float(r.deposit or 0),
                "status": r.status,
                "payment_status": r.payment_status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return results
