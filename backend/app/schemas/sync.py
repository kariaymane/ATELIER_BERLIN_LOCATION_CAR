"""
Pydantic schemas for sync endpoints.
"""
from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from app.schemas.vehicle import VehicleResponse
from app.schemas.rental import RentalResponse
from app.schemas.maintenance import MaintenanceResponse
from app.schemas.notification import NotificationResponse


class SyncPushItem(BaseModel):
    entity_type: str = Field(..., max_length=50)
    entity_id: str
    operation: str = Field(...)  # CREATE, UPDATE, DELETE
    payload: dict[str, Any]
    device_id: str = Field(..., max_length=100)
    idempotency_key: str = Field(..., max_length=255)
    timestamp: datetime
    version: int = Field(default=1)


class SyncPushRequest(BaseModel):
    items: list[SyncPushItem] = Field(..., max_length=50)


class SyncPushResult(BaseModel):
    entity_id: str
    status: str  # "ok", "conflict", "error"
    message: Optional[str] = None
    server_version: Optional[int] = None


class SyncPushResponse(BaseModel):
    results: list[SyncPushResult]


class SyncPullRequest(BaseModel):
    since: datetime
    entity_types: Optional[list[str]] = None
    device_id: str = Field(..., max_length=100)


class SyncPullItem(BaseModel):
    entity_type: str
    entity_id: str
    operation: str
    payload: dict[str, Any]
    version: int
    updated_at: datetime


class SyncPullResponse(BaseModel):
    items: list[SyncPullItem]
    server_time: datetime


class SyncHealthResponse(BaseModel):
    status: str = "healthy"
    version: str = "1.0.0"
    api_version: str = "1.0.0"
    server_id: str = "car-rental-server-v1"


class SyncBootstrapResponse(BaseModel):
    sync_version: int = 1
    server_time: datetime
    server_id: str = "car-rental-server-v1"
    api_version: str = "1.0.0"
    vehicles: list[VehicleResponse] = Field(default_factory=list)
    rentals: list[RentalResponse] = Field(default_factory=list)
    maintenance: list[MaintenanceResponse] = Field(default_factory=list)
    notifications: list[NotificationResponse] = Field(default_factory=list)
