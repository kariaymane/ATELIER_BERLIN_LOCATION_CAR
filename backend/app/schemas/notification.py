"""
Pydantic schemas for notification endpoints.
"""
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime


class NotificationResponse(BaseModel):
    id: str
    vehicle_id: Optional[str] = None
    vehicle_name: Optional[str] = None
    vehicle_registration: Optional[str] = None
    type: str
    severity: str
    title: str
    message: str
    due_date: Optional[date] = None
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread_count: int
    page: int
    page_size: int


class UnreadCountResponse(BaseModel):
    unread_count: int
