"""
Shared enumerations used across backend and desktop.
These enums define the business domain constants.
"""
from enum import Enum


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    RENTED = "RENTED"
    MAINTENANCE = "MAINTENANCE"
    SOLD = "SOLD"
    INACTIVE = "INACTIVE"


class FuelType(str, Enum):
    GASOLINE = "GASOLINE"
    DIESEL = "DIESEL"
    ELECTRIC = "ELECTRIC"
    HYBRID = "HYBRID"
    LPG = "LPG"


class TransmissionType(str, Enum):
    MANUAL = "MANUAL"
    AUTOMATIC = "AUTOMATIC"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    EMPLOYEE = "EMPLOYEE"
    MOBILE_USER = "MOBILE_USER"


class SyncStatus(str, Enum):
    PENDING = "PENDING"
    SYNCING = "SYNCING"
    SYNCED = "SYNCED"
    FAILED = "FAILED"
    CONFLICT = "CONFLICT"


class SyncOperation(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class AuditAction(str, Enum):
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    LOGIN_FAILED = "LOGIN_FAILED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    PERMISSION_CHANGED = "PERMISSION_CHANGED"
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    DELETED = "DELETED"
    STATUS_CHANGED = "STATUS_CHANGED"
    SYNC_PUSH = "SYNC_PUSH"
    SYNC_PULL = "SYNC_PULL"
    SYNC_CONFLICT = "SYNC_CONFLICT"


# Valid vehicle status transitions
VALID_VEHICLE_TRANSITIONS: dict[VehicleStatus, set[VehicleStatus]] = {
    VehicleStatus.AVAILABLE: {
        VehicleStatus.RESERVED,
        VehicleStatus.RENTED,
        VehicleStatus.MAINTENANCE,
        VehicleStatus.SOLD,
        VehicleStatus.INACTIVE,
    },
    VehicleStatus.RESERVED: {
        VehicleStatus.RENTED,
        VehicleStatus.AVAILABLE,  # cancellation
    },
    VehicleStatus.RENTED: {
        VehicleStatus.AVAILABLE,  # return
    },
    VehicleStatus.MAINTENANCE: {
        VehicleStatus.AVAILABLE,
    },
    VehicleStatus.SOLD: set(),  # terminal state
    VehicleStatus.INACTIVE: {
        VehicleStatus.AVAILABLE,
    },
}
