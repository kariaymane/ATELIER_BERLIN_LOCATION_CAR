"""
User model — stores credentials with Argon2id hashing.
Passwords are NEVER stored in plaintext.
"""
from sqlalchemy import Column, String, Boolean, CheckConstraint, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.base import TimestampMixin, VersionMixin, generate_uuid


class User(Base, TimestampMixin, VersionMixin):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="EMPLOYEE")
    is_active = Column(Boolean, default=True, nullable=False)
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user", foreign_keys="AuditLog.user_id")

    __table_args__ = (
        CheckConstraint(
            "role IN ('ADMIN', 'MANAGER', 'EMPLOYEE', 'MOBILE_USER')",
            name="ck_users_valid_role",
        ),
        CheckConstraint(
            "length(email) >= 5",
            name="ck_users_email_min_length",
        ),
        CheckConstraint(
            "length(username) >= 3",
            name="ck_users_username_min_length",
        ),
    )

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"
