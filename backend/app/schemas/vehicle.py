"""
Pydantic schemas for vehicle endpoints.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from app.schemas.vehicle_image import VehicleImageResponse


class VehicleCreate(BaseModel):
    registration: str = Field(..., min_length=1, max_length=20)
    vin: str = Field(..., min_length=17, max_length=17)
    brand: str = Field(..., min_length=1, max_length=100)
    model: str = Field(..., min_length=1, max_length=100)
    year: int = Field(..., ge=1990, le=2035)
    color: str = Field(..., min_length=1, max_length=50)
    fuel_type: str = Field(...)
    transmission: str = Field(...)
    current_mileage: int = Field(default=0, ge=0)
    purchase_mileage: int = Field(default=0, ge=0)
    purchase_price: float = Field(default=0, ge=0)
    daily_rental_price: float = Field(default=0, ge=0)
    purchase_date: Optional[date] = None
    notes: Optional[str] = None
    assurance_expiry: Optional[date] = None
    vignette_expiry: Optional[date] = None
    visite_technique_expiry: Optional[date] = None
    carte_grise_expiry: Optional[date] = None
    autres_expiry: Optional[date] = None
    autres_label: Optional[str] = None
    image_url: Optional[str] = None
    image_urls: List[str] = []
    images: List[VehicleImageResponse] = []

    model_config = {"json_schema_extra": {
        "example": {
            "registration": "AB-123-CD",
            "vin": "WVWZZZ3CZWE123456",
            "brand": "Dacia",
            "model": "Logan",
            "year": 2024,
            "color": "Blanc",
            "fuel_type": "DIESEL",
            "transmission": "MANUAL",
            "current_mileage": 15000,
            "purchase_mileage": 0,
            "purchase_price": 120000.00,
            "daily_rental_price": 350.00,
            "purchase_date": "2024-01-15",
            "image_url": "/static/uploads/vehicles/sample.jpg",
        }
    }}


class VehicleUpdate(BaseModel):
    registration: Optional[str] = Field(None, min_length=1, max_length=20)
    brand: Optional[str] = Field(None, min_length=1, max_length=100)
    model: Optional[str] = Field(None, min_length=1, max_length=100)
    year: Optional[int] = Field(None, ge=1990, le=2035)
    color: Optional[str] = Field(None, min_length=1, max_length=50)
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    current_mileage: Optional[int] = Field(None, ge=0)
    purchase_price: Optional[float] = Field(None, ge=0)
    daily_rental_price: Optional[float] = Field(None, ge=0)
    purchase_date: Optional[date] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    assurance_expiry: Optional[date] = None
    vignette_expiry: Optional[date] = None
    visite_technique_expiry: Optional[date] = None
    carte_grise_expiry: Optional[date] = None
    autres_expiry: Optional[date] = None
    autres_label: Optional[str] = None
    image_url: Optional[str] = None
    image_urls: List[str] = []
    images: List[VehicleImageResponse] = []


class VehicleResponse(BaseModel):
    id: str
    registration: str
    vin: str
    brand: str
    model: str
    year: int
    color: str
    fuel_type: str
    transmission: str
    current_mileage: int
    purchase_mileage: int
    purchase_price: float
    daily_rental_price: float
    purchase_date: Optional[date]
    status: str
    # Structural status is `status`. `effective_status` is the DERIVED
    # right-now state (SOLD/INACTIVE > MAINTENANCE > RENTED > RESERVED >
    # AVAILABLE) — the single value every list/dashboard/mobile screen shows.
    effective_status: Optional[str] = None
    notes: Optional[str]
    assurance_expiry: Optional[date] = None
    vignette_expiry: Optional[date] = None
    visite_technique_expiry: Optional[date] = None
    carte_grise_expiry: Optional[date] = None
    autres_expiry: Optional[date] = None
    autres_label: Optional[str] = None
    image_url: Optional[str] = None
    image_urls: List[str] = []
    images: List[VehicleImageResponse] = []
    created_at: datetime
    updated_at: datetime
    version: int

    model_config = {"from_attributes": True}


class VehicleListResponse(BaseModel):
    vehicles: list[VehicleResponse]
    total: int
    page: int
    page_size: int


class VehicleStatusUpdate(BaseModel):
    status: str = Field(...)
