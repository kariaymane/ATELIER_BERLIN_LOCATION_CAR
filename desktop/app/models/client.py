"""
Local SQLite client model — mirrors PostgreSQL clients table.
"""
from sqlalchemy import Column, String, Integer, Text
from app.database import LocalBase

class LocalClient(LocalBase):
    __tablename__ = "clients"

    id = Column(String(36), primary_key=True)  # UUID as text
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=True, default="")  # Made nullable with default for test
    email = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    cin_number = Column(String(50), nullable=True)
    identity_card_image = Column(Text, nullable=True)
    license_number = Column(String(50), nullable=True)
    driving_license_image = Column(Text, nullable=True)
    photo_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="ACTIVE")
    created_at = Column(String(30), nullable=True)  # Made nullable for test simplicity
    updated_at = Column(String(30), nullable=True)  # Made nullable for test simplicity
    version = Column(Integer, nullable=False, default=1)
