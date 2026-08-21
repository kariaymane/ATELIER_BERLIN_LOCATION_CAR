"""
User service — business logic for user management.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.repositories.audit_repository import AuditRepository
from app.i18n import get_message
from app.schemas.user import UserCreate, UserUpdate
import logging

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = UserRepository(session)
        self._audit = AuditRepository(session)

    async def create_user(
        self,
        data: UserCreate,
        created_by: Optional[UUID] = None,
        lang: str = "fr",
    ) -> dict:
        """Create a new user with hashed password."""
        # Check uniqueness
        if await self._repo.email_exists(data.email):
            return {"error": get_message("user.email_exists", lang)}
        if await self._repo.username_exists(data.username):
            return {"error": get_message("user.username_exists", lang)}

        user = User(
            email=data.email,
            username=data.username,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            role=data.role,
        )
        await self._repo.create(user)

        await self._audit.create(
            entity_type="user",
            action="CREATED",
            entity_id=user.id,
            user_id=created_by,
            new_values={"email": user.email, "role": user.role},
        )

        return {"user": user, "message": get_message("user.created", lang)}

    async def get_user(self, user_id: UUID, lang: str = "fr") -> dict:
        """Get user by ID."""
        user = await self._repo.get_by_id(user_id)
        if not user:
            return {"error": get_message("user.not_found", lang)}
        return {"user": user}

    async def update_user(
        self,
        user_id: UUID,
        data: UserUpdate,
        updated_by: Optional[UUID] = None,
        lang: str = "fr",
    ) -> dict:
        """Update a user."""
        user = await self._repo.get_by_id(user_id)
        if not user:
            return {"error": get_message("user.not_found", lang)}

        old_values = {}
        new_values = {}

        if data.email is not None and data.email != user.email:
            if await self._repo.email_exists(data.email, exclude_id=user_id):
                return {"error": get_message("user.email_exists", lang)}
            old_values["email"] = user.email
            user.email = data.email
            new_values["email"] = data.email

        if data.username is not None and data.username != user.username:
            if await self._repo.username_exists(data.username, exclude_id=user_id):
                return {"error": get_message("user.username_exists", lang)}
            old_values["username"] = user.username
            user.username = data.username
            new_values["username"] = data.username

        if data.full_name is not None:
            old_values["full_name"] = user.full_name
            user.full_name = data.full_name
            new_values["full_name"] = data.full_name

        if data.role is not None:
            old_values["role"] = user.role
            user.role = data.role
            new_values["role"] = data.role

        if data.is_active is not None:
            old_values["is_active"] = user.is_active
            user.is_active = data.is_active
            new_values["is_active"] = data.is_active

        user.version += 1

        if new_values:
            await self._audit.create(
                entity_type="user",
                action="UPDATED",
                entity_id=user.id,
                user_id=updated_by,
                old_values=old_values,
                new_values=new_values,
            )

        return {"user": user, "message": get_message("user.updated", lang)}

    async def list_users(
        self, page: int = 1, page_size: int = 25
    ) -> dict:
        """List users with pagination."""
        users, total = await self._repo.get_all(page=page, page_size=page_size)
        return {"users": users, "total": total, "page": page, "page_size": page_size}
