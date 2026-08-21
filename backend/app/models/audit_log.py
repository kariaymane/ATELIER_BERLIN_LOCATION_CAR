"""
Immutable audit log model.
Records all important business and security events.
Never logs passwords, tokens, or encryption keys.
"""
from sqlalchemy import Column, String, Text, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from datetime import datetime, timezone

from app.database import Base
from app.models.base import generate_uuid
from sqlalchemy.orm import relationship


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    action = Column(String(50), nullable=False, index=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    old_values = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    new_values = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    device_id = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)  # IPv6 max length
    details = Column(Text, nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    user = relationship("User", back_populates="audit_logs", foreign_keys=[user_id])

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action={self.action}, entity={self.entity_type})>"
