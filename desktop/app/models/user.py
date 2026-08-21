"""
Local user model for offline auth caching.
"""
from sqlalchemy import Column, String, Integer, Boolean
from app.database import LocalBase


class LocalUser(LocalBase):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="EMPLOYEE")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(String(30), nullable=False)
    updated_at = Column(String(30), nullable=False)
    version = Column(Integer, nullable=False, default=1)
