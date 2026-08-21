"""
Sync queue model — tracks all local changes that need to sync to server.
"""
from sqlalchemy import Column, String, Integer, Text
from app.database import LocalBase


class SyncQueueItem(LocalBase):
    __tablename__ = "sync_queue"

    id = Column(String(36), primary_key=True)  # UUID
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(36), nullable=False)
    operation = Column(String(20), nullable=False)  # CREATE, UPDATE, DELETE
    payload = Column(Text, nullable=False)  # JSON string
    device_id = Column(String(100), nullable=False)
    user_id = Column(String(36), nullable=True)
    sync_status = Column(String(20), nullable=False, default="PENDING")
    retry_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    idempotency_key = Column(String(255), unique=True, nullable=False)
    created_at = Column(String(30), nullable=False)
    synced_at = Column(String(30), nullable=True)


LocalSyncQueue = SyncQueueItem
