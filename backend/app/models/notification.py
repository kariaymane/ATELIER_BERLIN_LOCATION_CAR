"""
Notification model for vehicle document expiration, maintenance events, and system alerts.
"""
from sqlalchemy import (
    Column, String, Text, Boolean, Date, ForeignKey, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP
from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    vehicle_id = Column(
        UUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    type = Column(String(50), nullable=False) # DOCUMENT_EXPIRY, MAINTENANCE_DUE, MAINTENANCE_REQUIRED, DIAGNOSTIC_EXPIRED
    severity = Column(String(30), nullable=False, default="warning") # warning, urgent, expired, maintenance_required, info
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    due_date = Column(Date, nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "severity IN ('warning', 'urgent', 'expired', 'maintenance_required', 'info')",
            name="ck_notifications_valid_severity",
        ),
    )

    def __repr__(self):
        return f"<Notification(id={self.id}, type={self.type}, severity={self.severity}, read={self.is_read})>"
