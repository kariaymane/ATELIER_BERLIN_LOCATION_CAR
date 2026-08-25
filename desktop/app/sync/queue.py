"""
Sync queue manager — enqueues local changes for later synchronization.
"""
import json
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.sync_queue import SyncQueueItem
import logging

logger = logging.getLogger(__name__)


class SyncQueue:
    """Manages the local sync queue."""

    def __init__(self, session: Session, device_id: str, user_id: str = None):
        self._session = session
        self._device_id = device_id
        self._user_id = user_id

    def enqueue(
        self,
        entity_type: str,
        entity_id: str,
        operation: str,
        payload: dict,
    ) -> SyncQueueItem:
        """Add an item to the sync queue."""
        item = SyncQueueItem(
            id=str(uuid.uuid4()),
            entity_type=entity_type,
            entity_id=entity_id,
            operation=operation,
            payload=json.dumps(payload, default=str),
            device_id=self._device_id,
            user_id=self._user_id,
            sync_status="PENDING",
            retry_count=0,
            idempotency_key=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._session.add(item)
        # removed self._session.commit() to preserve transaction atomicity
        logger.info(
            "Enqueued sync: %s %s %s", operation, entity_type, entity_id
        )
        return item

    def get_pending(self, limit: int = 50) -> list[SyncQueueItem]:
        """Get pending sync items."""
        return (
            self._session.query(SyncQueueItem)
            .filter(SyncQueueItem.sync_status.in_(["PENDING", "FAILED"]))
            .filter(SyncQueueItem.retry_count < 5)
            .order_by(SyncQueueItem.created_at)
            .limit(limit)
            .all()
        )

    def mark_synced(self, item_id: str):
        """Mark an item as synced."""
        item = self._session.get(SyncQueueItem, item_id)
        if item:
            item.sync_status = "SYNCED"
            item.synced_at = datetime.now(timezone.utc).isoformat()
            self._session.commit()

    def mark_failed(self, item_id: str, error: str):
        """Mark an item as failed and increment retry count."""
        item = self._session.get(SyncQueueItem, item_id)
        if item:
            item.sync_status = "FAILED"
            item.retry_count += 1
            item.error_message = error
            self._session.commit()

    def mark_conflict(self, item_id: str, error: str):
        """Mark an item as having a conflict."""
        item = self._session.get(SyncQueueItem, item_id)
        if item:
            item.sync_status = "CONFLICT"
            item.error_message = error
            self._session.commit()

    def get_pending_count(self) -> int:
        """Get count of pending sync items."""
        return (
            self._session.query(SyncQueueItem)
            .filter(SyncQueueItem.sync_status.in_(["PENDING", "FAILED"]))
            .filter(SyncQueueItem.retry_count < 5)
            .count()
        )
