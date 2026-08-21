"""
Pydantic schemas for rental/reservation endpoints.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


class RentalCreate(BaseModel):
    vehicle_id: UUID
    customer_name: str = Field(..., min_length=2, max_length=255)
    customer_phone: str = Field(..., min_length=5, max_length=20)
    start_datetime: datetime
    end_datetime: datetime
    daily_price: Optional[float] = Field(None, ge=0)
    deposit: Optional[float] = Field(0, ge=0)
    notes: Optional[str] = None

    model_config = {"json_schema_extra": {
        "example": {
            "vehicle_id": "87dfe5d3-c48e-469d-bd5b-ef6b93106102",
            "customer_name": "Ahmed El Fassi",
            "customer_phone": "+212661234567",
            "start_datetime": "2026-08-12T10:00:00Z",
            "end_datetime": "2026-08-16T10:00:00Z",
            "daily_price": 250.00,
            "deposit": 500.00,
        }
    }}


class RentalUpdate(BaseModel):
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    customer_name: Optional[str] = Field(None, min_length=2, max_length=255)
    customer_phone: Optional[str] = Field(None, min_length=5, max_length=20)
    notes: Optional[str] = None


class RentalResponse(BaseModel):
    id: str
    vehicle_id: str
    customer_name: Optional[str]
    customer_phone: Optional[str]
    start_datetime: datetime
    end_datetime: datetime
    daily_price: float
    num_days: int
    total_price: float
    deposit: float
    payment_status: str
    status: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    version: int
    # Enriched fields (optional, from joins)
    vehicle_registration: Optional[str] = None
    vehicle_brand: Optional[str] = None
    vehicle_model: Optional[str] = None

    model_config = {"from_attributes": True}


class RentalListResponse(BaseModel):
    rentals: list[RentalResponse]
    total: int
    page: int
    page_size: int


class AvailabilityRequest(BaseModel):
    start_datetime: datetime
    end_datetime: datetime


class AvailabilityResponse(BaseModel):
    vehicle_id: str
    available: bool
    daily_price: float
    start_datetime: datetime
    end_datetime: datetime
    num_days: int
    estimated_total: float
