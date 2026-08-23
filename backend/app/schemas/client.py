from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class ClientCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    cin_number: Optional[str] = Field(None, max_length=50)
    identity_card_image: Optional[str] = None
    license_number: Optional[str] = Field(None, max_length=50)
    driving_license_image: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None

class ClientUpdate(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    cin_number: Optional[str] = Field(None, max_length=50)
    identity_card_image: Optional[str] = None
    license_number: Optional[str] = Field(None, max_length=50)
    driving_license_image: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = Field(None, max_length=20)

class ClientResponse(BaseModel):
    id: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    cin_number: Optional[str] = None
    identity_card_image: Optional[str] = None
    license_number: Optional[str] = None
    driving_license_image: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None
    status: str = "ACTIVE"
    created_at: datetime
    updated_at: datetime
    version: int = 1
    rental_count: Optional[int] = 0
    active_rentals_count: Optional[int] = 0

    model_config = {"from_attributes": True}

class ClientListResponse(BaseModel):
    clients: List[ClientResponse]
    total: int
    page: int
    page_size: int
