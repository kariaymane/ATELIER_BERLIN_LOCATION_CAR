"""
SQLite local model for Maintenance.
"""
from sqlalchemy import Column, String, Float, Text, Integer, Boolean
from app.database import LocalBase


class LocalMaintenance(LocalBase):
    __tablename__ = "maintenances"

    id = Column(String(36), primary_key=True)
    vehicle_id = Column(String(36), nullable=False)
    type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    diagnosis = Column(Text, nullable=True)
    repair_description = Column(Text, nullable=True)

    start_datetime = Column(String(50), nullable=False)
    expected_end_datetime = Column(String(50), nullable=True)
    actual_end_datetime = Column(String(50), nullable=True)

    mileage = Column(Float, nullable=True)
    location = Column(String(255), nullable=True)
    technician_name = Column(String(255), nullable=True)
    invoice_number = Column(String(255), nullable=True)

    oil_brand = Column(String(100), nullable=True)
    oil_viscosity = Column(String(50), nullable=True)
    oil_quantity = Column(Float, nullable=True)
    oil_filter_changed = Column(Boolean, default=False, nullable=False)
    air_filter_changed = Column(Boolean, default=False, nullable=False)
    fuel_filter_changed = Column(Boolean, default=False, nullable=False)
    cabin_filter_changed = Column(Boolean, default=False, nullable=False)

    estimated_cost = Column(Float, nullable=True)
    parts_cost = Column(Float, default=0.0, nullable=False)
    labor_cost = Column(Float, default=0.0, nullable=False)
    other_cost = Column(Float, default=0.0, nullable=False)
    actual_cost = Column(Float, nullable=True) # total cost

    next_maintenance_date = Column(String(50), nullable=True)
    next_maintenance_mileage = Column(Float, nullable=True)

    step = Column(String(50), nullable=False, default="EN ATTENTE")
    status = Column(String(20), nullable=False, default="ACTIVE")
    notes = Column(Text, nullable=True)

    created_at = Column(String(30), nullable=False)
    updated_at = Column(String(30), nullable=False)
    version = Column(Integer, nullable=False, default=1)

class LocalMaintenancePart(LocalBase):
    __tablename__ = "maintenance_parts"

    id = Column(String(36), primary_key=True)
    maintenance_id = Column(String(36), nullable=False)
    part_name = Column(String(255), nullable=False)
    quantity = Column(Float, nullable=False, default=1.0)
    unit_price = Column(Float, nullable=False, default=0.0)
    total_price = Column(Float, nullable=False, default=0.0)
    notes = Column(Text, nullable=True)

    created_at = Column(String(30), nullable=False)
    updated_at = Column(String(30), nullable=False)
