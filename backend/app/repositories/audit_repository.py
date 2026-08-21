"""
Audit log repository — append-only operations.
"""
from typing import Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
import logging

logger = logging.getLogger(__name__)


class AuditRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        entity_type: str,
        action: str,
        user_id: Optional[UUID] = None,
        entity_id: Optional[UUID] = None,
        old_values: Optional[dict] = None,
        new_values: Optional[dict] = None,
        device_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        details: Optional[str] = None,
    ) -> AuditLog:
        """Create an audit log entry. This is append-only — no updates or deletes."""
        # Ensure user_id exists in users table to prevent FK constraint failures
        valid_user_id = user_id
        if valid_user_id:
            from app.models.user import User
            user_exists = await self._session.get(User, valid_user_id)
            if not user_exists:
                valid_user_id = None

        log = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            user_id=valid_user_id,
            old_values=old_values,
            new_values=new_values,
            device_id=device_id,
            ip_address=ip_address,
            details=details,
        )
        self._session.add(log)
        await self._session.flush()
        return log

    async def get_for_entity(
        self,
        entity_type: str,
        entity_id: UUID,
        limit: int = 50,
    ) -> list[AuditLog]:
        """Get audit logs for a specific entity."""
        result = await self._session.execute(
            select(AuditLog)
            .where(
                AuditLog.entity_type == entity_type,
                AuditLog.entity_id == entity_id,
            )
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_for_user(
        self,
        user_id: UUID,
        limit: int = 50,
    ) -> list[AuditLog]:
        """Get audit logs for a specific user."""
        result = await self._session.execute(
            select(AuditLog)
            .where(AuditLog.user_id == user_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_recent(self, limit: int = 100) -> list[AuditLog]:
        """Get most recent audit logs."""
        result = await self._session.execute(
            select(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
