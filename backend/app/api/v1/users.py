"""
User management API endpoints.
All operations require ADMIN role unless otherwise specified.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database import get_db
from app.dependencies import get_current_user, require_perm, get_language
from app.auth.rbac import Permission
from app.schemas.user import UserCreate, UserUpdate, UserResponse, UserListResponse
from app.services.user_service import UserService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.USERS_CREATE)),
    lang: str = Depends(get_language),
):
    """Create a new user. Requires ADMIN role."""
    service = UserService(db)
    result = await service.create_user(
        data=body,
        created_by=UUID(current_user["sub"]),
        lang=lang,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    user = result["user"]
    return UserResponse(
        id=str(user.id),
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        version=user.version,
    )


@router.get("/", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.USERS_READ)),
):
    """List users with pagination. Requires ADMIN or MANAGER role."""
    service = UserService(db)
    result = await service.list_users(page=page, page_size=page_size)
    return UserListResponse(
        users=[
            UserResponse(
                id=str(u.id),
                email=u.email,
                username=u.username,
                full_name=u.full_name,
                role=u.role,
                is_active=u.is_active,
                created_at=u.created_at,
                updated_at=u.updated_at,
                version=u.version,
            )
            for u in result["users"]
        ],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get current user profile."""
    service = UserService(db)
    result = await service.get_user(UUID(current_user["sub"]))

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"],
        )

    user = result["user"]
    return UserResponse(
        id=str(user.id),
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        version=user.version,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.USERS_READ)),
    lang: str = Depends(get_language),
):
    """Get user by ID. Requires ADMIN or MANAGER role."""
    service = UserService(db)
    result = await service.get_user(user_id, lang=lang)

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"],
        )

    user = result["user"]
    return UserResponse(
        id=str(user.id),
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        version=user.version,
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.USERS_UPDATE)),
    lang: str = Depends(get_language),
):
    """Update a user. Requires ADMIN role."""
    service = UserService(db)
    result = await service.update_user(
        user_id=user_id,
        data=body,
        updated_by=UUID(current_user["sub"]),
        lang=lang,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    user = result["user"]
    return UserResponse(
        id=str(user.id),
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        version=user.version,
    )
