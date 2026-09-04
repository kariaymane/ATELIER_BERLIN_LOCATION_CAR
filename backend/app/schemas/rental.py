from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID

class RentalCreate(BaseModel):
    vehicle_id: UUID
    # Canonical client link: set when the reservation is created for an
    # existing Client entity (desktop client selector / API clients).
    customer_id: Optional[UUID] = None
    customer_name: str = Field(..., min_length=2, max_length=255)
    # Optional everywhere else in the system (DB column is nullable; desktop UI
    # and Android model treat it as optional) — keep length rules when provided.
    customer_phone: Optional[str] = Field(None, min_length=5, max_length=20)
    customer_email: Optional[str] = None
    identity_card_image: Optional[str] = None
    driving_license_image: Optional[str] = None
    start_datetime: datetime
    end_datetime: datetime
    daily_price: Optional[float] = Field(None, ge=0)
    deposit: Optional[float] = Field(0, ge=0)
    notes: Optional[str] = None

class RentalUpdate(BaseModel):
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    customer_name: Optional[str] = Field(None, min_length=2, max_length=255)
    customer_phone: Optional[str] = Field(None, min_length=5, max_length=20)
    customer_email: Optional[str] = None
    identity_card_image: Optional[str] = None
    driving_license_image: Optional[str] = None
    notes: Optional[str] = None

class RentalResponse(BaseModel):
    id: str
    vehicle_id: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    identity_card_image: Optional[str] = None
    driving_license_image: Optional[str] = None
    start_datetime: datetime
    end_datetime: datetime
    daily_price: float
    num_days: int
    total_price: float
    deposit: float
    payment_status: str
    status: str
    cancellation_reason: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    version: int
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
