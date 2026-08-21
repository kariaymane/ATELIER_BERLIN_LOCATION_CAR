"""
Authentication API endpoints.
Rate-limited login, token refresh, logout, password change.
"""
from fastapi import APIRouter, Depends, Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_jwt_handler, get_current_user, get_language, get_client_ip
from app.schemas.auth import (
    LoginRequest, LoginResponse,
    RefreshRequest, RefreshResponse,
    PasswordChangeRequest, LogoutRequest,
)
from app.services.auth_service import AuthService
from app.security.middleware import limiter
from uuid import UUID
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
    lang: str = Depends(get_language),
):
    """
    Authenticate user and return JWT tokens.
    Rate-limited to 10 requests per minute per IP.
    """
    jwt_handler = get_jwt_handler()
    service = AuthService(db, jwt_handler)
    ip = get_client_ip(request)

    result = await service.login(
        email=body.email,
        password=body.password,
        device_id=body.device_id,
        ip_address=ip,
        lang=lang,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result["error"],
        )

    return result


@router.post("/refresh", response_model=RefreshResponse)
@limiter.limit("20/minute")
async def refresh(
    request: Request,
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    lang: str = Depends(get_language),
):
    """Refresh access token using a valid refresh token."""
    jwt_handler = get_jwt_handler()
    service = AuthService(db, jwt_handler)

    result = await service.refresh_tokens(
        refresh_token=body.refresh_token,
        device_id=body.device_id,
        lang=lang,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result["error"],
        )

    return result


@router.post("/logout")
async def logout(
    request: Request,
    body: LogoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    lang: str = Depends(get_language),
):
    """Logout by revoking the refresh token."""
    jwt_handler = get_jwt_handler()
    service = AuthService(db, jwt_handler)
    ip = get_client_ip(request)

    result = await service.logout(
        refresh_token=body.refresh_token,
        user_id=UUID(current_user["sub"]),
        ip_address=ip,
        lang=lang,
    )

    return result


@router.post("/change-password")
async def change_password(
    request: Request,
    body: PasswordChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    lang: str = Depends(get_language),
):
    """Change the current user's password."""
    ip = get_client_ip(request)
    jwt_handler = get_jwt_handler()
    service = AuthService(db, jwt_handler)

    result = await service.change_password(
        user_id=UUID(current_user["sub"]),
        current_password=body.current_password,
        new_password=body.new_password,
        ip_address=ip,
        lang=lang,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    return result
