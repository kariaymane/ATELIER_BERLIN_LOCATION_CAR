"""
Local SQLite vehicle model — mirrors PostgreSQL vehicle table.
Uses TEXT for UUIDs and ISO strings for timestamps (SQLite compatibility).
"""
from sqlalchemy import Column, String, Integer, Float, Text
from sqlalchemy.orm import relationship

from app.database import LocalBase


class LocalVehicle(LocalBase):
    __tablename__ = "vehicles"

    id = Column(String(36), primary_key=True)  # UUID as text
    registration = Column(String(20), unique=True, nullable=False)
    vin = Column(String(17), unique=True, nullable=False)
    brand = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    year = Column(Integer, nullable=False)
    color = Column(String(50), nullable=False)
    fuel_type = Column(String(20), nullable=False)
    transmission = Column(String(20), nullable=False)
    current_mileage = Column(Integer, nullable=False, default=0)
    purchase_mileage = Column(Integer, nullable=False, default=0)
    purchase_price = Column(Float, nullable=False, default=0)
    daily_rental_price = Column(Float, nullable=False, default=0)
    purchase_date = Column(String(10), nullable=True)  # ISO date
    status = Column(String(20), nullable=False, default="AVAILABLE")
    notes = Column(Text, nullable=True)

    # Document tracking
    assurance_expiry = Column(String(10), nullable=True)
    vignette_expiry = Column(String(10), nullable=True)
    visite_technique_expiry = Column(String(10), nullable=True)
    carte_grise_expiry = Column(String(10), nullable=True)
    autres_expiry = Column(String(10), nullable=True)
    autres_label = Column(String(100), nullable=True)
    image_url = Column(String(500), nullable=True)
    images = relationship("LocalVehicleImage", backref="vehicle", cascade="all, delete-orphan", order_by="LocalVehicleImage.sort_order")
    created_by = Column(String(36), nullable=True)
    created_at = Column(String(30), nullable=False)  # ISO timestamp
    updated_at = Column(String(30), nullable=False)
    version = Column(Integer, nullable=False, default=1)
