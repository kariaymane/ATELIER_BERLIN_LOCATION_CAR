"""
Pydantic schemas for user endpoints.
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=2, max_length=255)
    role: str = Field(default="EMPLOYEE")

    model_config = {"json_schema_extra": {
        "example": {
            "email": "user@carrental.local",
            "username": "jdoe",
            "password": "SecureP@ssw0rd!",
            "full_name": "Jean Dupont",
            "role": "EMPLOYEE",
        }
    }}


class UserUpdate(BaseModel):
    email: Optional[str] = Field(None, min_length=5, max_length=255)
    username: Optional[str] = Field(None, min_length=3, max_length=100)
    full_name: Optional[str] = Field(None, min_length=2, max_length=255)
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    version: int

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int
    page: int
    page_size: int
