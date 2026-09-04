from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field

class MaintenancePartBase(BaseModel):
    part_name: str = Field(..., max_length=255)
    quantity: float = Field(default=1.0)
    unit_price: float = Field(default=0.0)
    total_price: float = Field(default=0.0)
    notes: Optional[str] = None

class MaintenancePartCreate(MaintenancePartBase):
    pass

class MaintenancePartResponse(MaintenancePartBase):
    id: UUID
    maintenance_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class MaintenanceBase(BaseModel):
    vehicle_id: UUID
    type: str = Field(..., max_length=50) # Vidange, Freins, etc.
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    diagnosis: Optional[str] = None
    repair_description: Optional[str] = None

    start_datetime: datetime
    expected_end_datetime: Optional[datetime] = None
    actual_end_datetime: Optional[datetime] = None
    mileage: Optional[float] = None

    location: Optional[str] = Field(None, max_length=255)
    technician_name: Optional[str] = Field(None, max_length=255)
    invoice_number: Optional[str] = Field(None, max_length=255)

    oil_brand: Optional[str] = Field(None, max_length=100)
    oil_viscosity: Optional[str] = Field(None, max_length=50)
    oil_quantity: Optional[float] = None
    oil_filter_changed: bool = False
    air_filter_changed: bool = False
    fuel_filter_changed: bool = False
    cabin_filter_changed: bool = False

    estimated_cost: Optional[float] = None
    parts_cost: float = 0.0
    labor_cost: float = 0.0
    other_cost: float = 0.0
    actual_cost: Optional[float] = None # Will be treated as total_cost

    next_maintenance_date: Optional[datetime] = None
    next_maintenance_mileage: Optional[float] = None

    step: str = Field(default="EN ATTENTE", max_length=50)
    status: str = Field(default="ACTIVE", max_length=20)
    notes: Optional[str] = None

class MaintenanceCreate(MaintenanceBase):
    parts: Optional[List[MaintenancePartCreate]] = None
    confirm_interruption: bool = False

class MaintenanceUpdate(BaseModel):
    # Same fields as Base but all optional for PATCH
    type: Optional[str] = Field(None, max_length=50)
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    diagnosis: Optional[str] = None
    repair_description: Optional[str] = None
    start_datetime: Optional[datetime] = None
    expected_end_datetime: Optional[datetime] = None
    actual_end_datetime: Optional[datetime] = None
    mileage: Optional[float] = None
    location: Optional[str] = Field(None, max_length=255)
    technician_name: Optional[str] = Field(None, max_length=255)
    invoice_number: Optional[str] = Field(None, max_length=255)
    oil_brand: Optional[str] = Field(None, max_length=100)
    oil_viscosity: Optional[str] = Field(None, max_length=50)
    oil_quantity: Optional[float] = None
    oil_filter_changed: Optional[bool] = None
    air_filter_changed: Optional[bool] = None
    fuel_filter_changed: Optional[bool] = None
    cabin_filter_changed: Optional[bool] = None
    estimated_cost: Optional[float] = None
    parts_cost: Optional[float] = None
    labor_cost: Optional[float] = None
    other_cost: Optional[float] = None
    actual_cost: Optional[float] = None
    next_maintenance_date: Optional[datetime] = None
    next_maintenance_mileage: Optional[float] = None
    step: Optional[str] = Field(None, max_length=50)
    status: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = None
    parts: Optional[List[MaintenancePartCreate]] = None
    # Explicit operator confirmation to interrupt a car that is out on rent
    # right now when this PATCH activates the ticket (Policy B guard).
    confirm_interruption: bool = False

class MaintenanceResponse(MaintenanceBase):
    id: UUID
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    version: int
    vehicle_brand: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_registration: Optional[str] = None
    vehicle_image_url: Optional[str] = None
    parts: List[MaintenancePartResponse] = []

    class Config:
        from_attributes = True

class MaintenanceListResponse(BaseModel):
    items: List[MaintenanceResponse]
    total: int
    page: int
    size: int
    pages: int
