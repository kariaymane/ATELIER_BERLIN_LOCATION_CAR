"""
Pending upload model — durable record for files created while offline.

Each record tracks a single file that must be uploaded to the backend once
connectivity returns. The `marker` (e.g. "pending_uploads/<uuid>.jpg") is the
placeholder stored in local entity fields until the real remote URL replaces
it after confirmed server success. The unique constraint on `marker` makes
uploads idempotent across restarts, reconnects and duplicate sync cycles.
"""
from sqlalchemy import Column, String, Integer, Text

from app.database import LocalBase


class LocalPendingUpload(LocalBase):
    __tablename__ = "pending_uploads"

    id = Column(String(36), primary_key=True)            # UUID
    marker = Column(String(500), unique=True, nullable=False)  # idempotency key
    entity_type = Column(String(50), nullable=False)     # vehicle | reservation | client
    entity_id = Column(String(36), nullable=False)
    upload_type = Column(String(50), nullable=False)     # VEHICLE_IMAGE | CLIENT_DOCUMENT
    field_name = Column(String(64), nullable=True)       # target field on the entity
    local_path = Column(Text, nullable=False)            # durable local file copy
    remote_endpoint = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")
    # PENDING | SYNCED | FAILED (temporary) | PERMANENT_FAILED
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=8)
    next_attempt_at = Column(String(30), nullable=True)  # ISO timestamp for backoff
    error_message = Column(Text, nullable=True)
    created_at = Column(String(30), nullable=False)
    updated_at = Column(String(30), nullable=True)
    completed_at = Column(String(30), nullable=True)


PendingUpload = LocalPendingUpload
