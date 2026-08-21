"""
Role-Based Access Control (RBAC).
Permissions are enforced server-side — never trust the frontend.
"""
from enum import Enum
from typing import Optional
from functools import wraps
from fastapi import HTTPException, status
import logging

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    # Users
    USERS_CREATE = "users:create"
    USERS_READ = "users:read"
    USERS_UPDATE = "users:update"
    USERS_DELETE = "users:delete"
    USERS_MANAGE_ROLES = "users:manage_roles"

    # Vehicles
    VEHICLES_CREATE = "vehicles:create"
    VEHICLES_READ = "vehicles:read"
    VEHICLES_UPDATE = "vehicles:update"
    VEHICLES_UPDATE_LIMITED = "vehicles:update_limited"
    VEHICLES_DELETE = "vehicles:delete"

    # Reservations
    RESERVATIONS_CREATE = "reservations:create"
    RESERVATIONS_READ = "reservations:read"
    RESERVATIONS_UPDATE = "reservations:update"
    RESERVATIONS_CANCEL = "reservations:cancel"

    # Mileage
    MILEAGE_CORRECT = "mileage:correct"

    # Maintenance
    MAINTENANCE_CREATE = "maintenance:create"
    MAINTENANCE_READ = "maintenance:read"
    MAINTENANCE_UPDATE = "maintenance:update"
    MAINTENANCE_DELETE = "maintenance:delete"

    # Audit
    AUDIT_READ = "audit:read"

    # Sync
    SYNC_PUSH = "sync:push"
    SYNC_PULL = "sync:pull"


# Permission matrix: what each role can do
ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "ADMIN": {p for p in Permission},  # Admin has all permissions
    "MANAGER": {
        Permission.VEHICLES_CREATE,
        Permission.VEHICLES_READ,
        Permission.VEHICLES_UPDATE,
        Permission.RESERVATIONS_CREATE,
        Permission.RESERVATIONS_READ,
        Permission.RESERVATIONS_UPDATE,
        Permission.RESERVATIONS_CANCEL,
        Permission.MAINTENANCE_CREATE,
        Permission.MAINTENANCE_READ,
        Permission.MAINTENANCE_UPDATE,
        Permission.AUDIT_READ,
        Permission.SYNC_PUSH,
        Permission.SYNC_PULL,
        Permission.USERS_READ,
    },
    "EMPLOYEE": {
        Permission.VEHICLES_READ,
        Permission.VEHICLES_UPDATE_LIMITED,
        Permission.RESERVATIONS_CREATE,
        Permission.RESERVATIONS_READ,
        Permission.MAINTENANCE_READ,
        Permission.SYNC_PUSH,
        Permission.SYNC_PULL,
    },
    "MOBILE_USER": {
        Permission.VEHICLES_READ,
        Permission.RESERVATIONS_READ,
        Permission.MAINTENANCE_READ,
        Permission.SYNC_PULL,
    },
}


def has_permission(role: str, permission: Permission) -> bool:
    """Check if a role has a specific permission."""
    role_perms = ROLE_PERMISSIONS.get(role, set())
    return permission in role_perms


def require_permission(permission: Permission):
    """
    Dependency factory that checks if the current user has the required permission.
    Usage: Depends(require_permission(Permission.VEHICLES_CREATE))
    """
    def checker(current_user: dict):
        role = current_user.get("role", "")
        if not has_permission(role, permission):
            logger.warning(
                "Permission denied: user=%s role=%s required=%s",
                current_user.get("sub", "unknown"),
                role,
                permission.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )
        return current_user
    return checker
