"""
FastAPI dependencies for authentication, database sessions, and services.
"""
from typing import Optional
from fastapi import Depends, HTTPException, status, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth.jwt_handler import JWTHandler
from app.auth.rbac import Permission, has_permission
from app.config import get_settings
import logging

logger = logging.getLogger(__name__)

security = HTTPBearer()

_jwt_handler: Optional[JWTHandler] = None


def get_jwt_handler() -> JWTHandler:
    """Get or create JWT handler singleton."""
    global _jwt_handler
    if _jwt_handler is None:
        settings = get_settings()
        _jwt_handler = JWTHandler(
            secret=settings.JWT_SECRET,
            refresh_secret=settings.JWT_REFRESH_SECRET,
            algorithm=settings.JWT_ALGORITHM,
            access_expire_minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
            refresh_expire_days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS,
        )
    return _jwt_handler


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Dependency that extracts and validates the current user from JWT.
    Returns the token payload (sub, role, etc.).
    Never trusts the client — always verifies server-side.
    """
    jwt_handler = get_jwt_handler()
    payload = jwt_handler.verify_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def require_role(*roles: str):
    """Dependency factory that checks if user has one of the required roles."""
    async def checker(current_user: dict = Depends(get_current_user)):
        if current_user.get("role") not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user
    return checker


def require_perm(permission: Permission):
    """Dependency factory that checks if user has a specific permission."""
    async def checker(current_user: dict = Depends(get_current_user)):
        if not has_permission(current_user.get("role", ""), permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user
    return checker


def get_language(accept_language: Optional[str] = Header(None, alias="Accept-Language")) -> str:
    """Extract preferred language from Accept-Language header."""
    if accept_language:
        lang = accept_language.split(",")[0].split("-")[0].strip().lower()
        if lang in ("ar", "fr"):
            return lang
    return "fr"


def get_client_ip(request: Request) -> str:
    """Get client IP, respecting X-Forwarded-For from reverse proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
