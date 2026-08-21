"""
Vehicle model with comprehensive CHECK constraints.
Status transitions are enforced at the application layer with
database-level CHECK constraint for valid status values.
"""

from sqlalchemy.orm import relationship
from sqlalchemy import (
    Column, String, Integer, Numeric, Date, Text,
    CheckConstraint, ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base
from app.models.base import TimestampMixin, VersionMixin, generate_uuid


class Vehicle(Base, TimestampMixin, VersionMixin):
    __tablename__ = "vehicles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    registration = Column(String(20), unique=True, nullable=False, index=True)
    vin = Column(String(17), unique=True, nullable=False, index=True)
    brand = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    year = Column(Integer, nullable=False)
    color = Column(String(50), nullable=False)
    fuel_type = Column(String(20), nullable=False)
    transmission = Column(String(20), nullable=False)
    current_mileage = Column(Integer, nullable=False, default=0)
    purchase_mileage = Column(Integer, nullable=False, default=0)
    purchase_price = Column(Numeric(12, 2), nullable=False, default=0)
    daily_rental_price = Column(Numeric(10, 2), nullable=False, default=0)
    purchase_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default="AVAILABLE")
    notes = Column(Text, nullable=True)

    # Document tracking
    assurance_expiry = Column(Date, nullable=True)
    vignette_expiry = Column(Date, nullable=True)
    visite_technique_expiry = Column(Date, nullable=True)
    carte_grise_expiry = Column(Date, nullable=True)
    autres_expiry = Column(Date, nullable=True)
    autres_label = Column(String(100), nullable=True)
    image_url = Column(String(500), nullable=True)  # Legacy field, keep for backward compatibility during migration
    images = relationship("VehicleImage", backref="vehicle", cascade="all, delete-orphan", order_by="VehicleImage.sort_order")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


    __table_args__ = (
        CheckConstraint(
            "status IN ('AVAILABLE', 'RESERVED', 'RENTED', 'MAINTENANCE', 'SOLD', 'INACTIVE')",
            name="ck_vehicles_valid_status",
        ),
        CheckConstraint(
            "fuel_type IN ('GASOLINE', 'DIESEL', 'ELECTRIC', 'HYBRID', 'LPG')",
            name="ck_vehicles_valid_fuel_type",
        ),
        CheckConstraint(
            "transmission IN ('MANUAL', 'AUTOMATIC')",
            name="ck_vehicles_valid_transmission",
        ),
        CheckConstraint(
            "current_mileage >= 0",
            name="ck_vehicles_mileage_non_negative",
        ),
        CheckConstraint(
            "purchase_mileage >= 0",
            name="ck_vehicles_purchase_mileage_non_negative",
        ),
        CheckConstraint(
            "purchase_price >= 0",
            name="ck_vehicles_purchase_price_non_negative",
        ),
        CheckConstraint(
            "daily_rental_price >= 0",
            name="ck_vehicles_daily_price_non_negative",
        ),
        CheckConstraint(
            "year >= 1990 AND year <= 2035",
            name="ck_vehicles_valid_year",
        ),
        CheckConstraint(
            "length(vin) = 17",
            name="ck_vehicles_vin_length",
        ),
    )

    def __repr__(self):
        return f"<Vehicle(id={self.id}, reg={self.registration}, status={self.status})>"
