"""
Base repository pattern for database operations.
All database access goes through repositories — never raw SQL in services or API.
Uses SQLAlchemy parameterized queries — never string concatenation.
"""
from typing import Optional, TypeVar, Generic, Type
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Base repository with common CRUD operations."""

    def __init__(self, session: AsyncSession, model_class: Type[T]):
        self._session = session
        self._model_class = model_class

    async def get_by_id(self, entity_id: UUID) -> Optional[T]:
        """Get a single entity by ID."""
        result = await self._session.execute(
            select(self._model_class).where(self._model_class.id == entity_id)
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        page: int = 1,
        page_size: int = 25,
        filters: Optional[list] = None,
    ) -> tuple[list[T], int]:
        """Get paginated entities with optional filters."""
        query = select(self._model_class)
        count_query = select(func.count()).select_from(self._model_class)

        if filters:
            for f in filters:
                query = query.where(f)
                count_query = count_query.where(f)

        # Get total count
        total_result = await self._session.execute(count_query)
        total = total_result.scalar()

        # Get paginated results
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        result = await self._session.execute(query)
        items = list(result.scalars().all())

        return items, total

    async def create(self, entity: T) -> T:
        """Create a new entity."""
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update_entity(self, entity: T) -> T:
        """Update an existing entity (already in session)."""
        await self._session.flush()
        return entity

    async def delete_entity(self, entity: T) -> None:
        """Delete an entity."""
        await self._session.delete(entity)
        await self._session.flush()
