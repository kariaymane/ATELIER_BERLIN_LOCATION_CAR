"""
Idempotency key model to prevent duplicate operations.
Critical operations (reservations, payments, sync) use idempotency keys
to ensure safe retries without creating duplicates.
"""
from sqlalchemy import Column, String, Text, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from datetime import datetime, timezone

from app.database import Base
from app.models.base import generate_uuid


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    key = Column(String(255), unique=True, nullable=False, index=True)
    endpoint = Column(String(255), nullable=False)
    status_code = Column(String(10), nullable=True)
    response_body = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return f"<IdempotencyKey(key={self.key}, endpoint={self.endpoint})>"
