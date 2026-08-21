"""
Vehicle repository — database operations for vehicles.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.repositories.base import BaseRepository
import logging

logger = logging.getLogger(__name__)


class VehicleRepository(BaseRepository[Vehicle]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Vehicle)

    async def get_by_registration(self, registration: str) -> Optional[Vehicle]:
        """Get vehicle by registration/license plate."""
        result = await self._session.execute(
            select(Vehicle).where(Vehicle.registration == registration)
        )
        return result.scalar_one_or_none()

    async def get_by_vin(self, vin: str) -> Optional[Vehicle]:
        """Get vehicle by VIN/chassis number."""
        result = await self._session.execute(
            select(Vehicle).where(Vehicle.vin == vin)
        )
        return result.scalar_one_or_none()

    async def registration_exists(
        self, registration: str, exclude_id: Optional[UUID] = None
    ) -> bool:
        """Check if registration plate already exists."""
        query = select(Vehicle).where(Vehicle.registration == registration)
        if exclude_id:
            query = query.where(Vehicle.id != exclude_id)
        result = await self._session.execute(query)
        return result.scalar_one_or_none() is not None

    async def vin_exists(
        self, vin: str, exclude_id: Optional[UUID] = None
    ) -> bool:
        """Check if VIN already exists."""
        query = select(Vehicle).where(Vehicle.vin == vin)
        if exclude_id:
            query = query.where(Vehicle.id != exclude_id)
        result = await self._session.execute(query)
        return result.scalar_one_or_none() is not None

    async def get_by_status(self, status: str) -> list[Vehicle]:
        """Get all vehicles with a given status."""
        result = await self._session.execute(
            select(Vehicle).where(Vehicle.status == status)
        )
        return list(result.scalars().all())

    async def search(
        self,
        query_str: str,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[Vehicle], int]:
        """Search vehicles by registration, VIN, brand, or model."""
        search_filter = or_(
            Vehicle.registration.ilike(f"%{query_str}%"),
            Vehicle.vin.ilike(f"%{query_str}%"),
            Vehicle.brand.ilike(f"%{query_str}%"),
            Vehicle.model.ilike(f"%{query_str}%"),
        )
    async def list_filtered(
        self,
        page: int = 1,
        page_size: int = 25,
        status: Optional[str] = None,
        search: Optional[str] = None,
        price: Optional[float] = None,
    ) -> tuple[list[Vehicle], int]:
        """List vehicles with status, search, and price filters."""
        filters = []
        if status:
            filters.append(Vehicle.status == status)
        if search:
            filters.append(
                or_(
                    Vehicle.registration.ilike(f"%{search}%"),
                    Vehicle.vin.ilike(f"%{search}%"),
                    Vehicle.brand.ilike(f"%{search}%"),
                    Vehicle.model.ilike(f"%{search}%"),
                )
            )
        if price is not None:
            # Exact price matching with small float tolerance
            filters.append(
                Vehicle.daily_rental_price.between(price - 0.5, price + 0.5)
            )
        return await self.get_all(page=page, page_size=page_size, filters=filters if filters else None)

    async def count_by_status(self) -> dict[str, int]:
        """Get count of vehicles per status."""
        from sqlalchemy import func
        result = await self._session.execute(
            select(Vehicle.status, func.count(Vehicle.id))
            .group_by(Vehicle.status)
        )
        return dict(result.all())
