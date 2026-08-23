"""
User repository — database operations for users.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository
import logging

logger = logging.getLogger(__name__)


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email address (case-insensitive & trimmed)."""
        from sqlalchemy import func
        clean_email = email.strip().lower() if email else ""
        result = await self._session.execute(
            select(User).where(func.lower(User.email) == clean_email)
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        result = await self._session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def email_exists(self, email: str, exclude_id: Optional[UUID] = None) -> bool:
        """Check if email already exists."""
        query = select(User).where(User.email == email)
        if exclude_id:
            query = query.where(User.id != exclude_id)
        result = await self._session.execute(query)
        return result.scalar_one_or_none() is not None

    async def username_exists(self, username: str, exclude_id: Optional[UUID] = None) -> bool:
        """Check if username already exists."""
        query = select(User).where(User.username == username)
        if exclude_id:
            query = query.where(User.id != exclude_id)
        result = await self._session.execute(query)
        return result.scalar_one_or_none() is not None

    async def get_active_users(self) -> list[User]:
        """Get all active users."""
        result = await self._session.execute(
            select(User).where(User.is_active == True)
        )
        return list(result.scalars().all())
