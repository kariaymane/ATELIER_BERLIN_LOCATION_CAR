from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
import uuid
from pathlib import Path
from typing import Optional

from app.database import get_db
from app.dependencies import get_current_user, require_perm, get_language
from app.auth.rbac import Permission
from app.schemas.client import ClientCreate, ClientUpdate, ClientResponse, ClientListResponse
from app.services.client_service import ClientService

router = APIRouter(prefix="/clients", tags=["Clients"])

@router.post("/upload-image")
async def upload_client_image(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_CREATE)),
):
    """Upload a client photo, CIN document, or driving license image."""
    MAX_SIZE = 10 * 1024 * 1024  # 10MB
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le fichier est trop volumineux (max 10 MB).",
        )

    # Magic bytes validation
    is_jpeg = content.startswith(b'\xff\xd8\xff')
    is_png = content.startswith(b'\x89PNG\r\n\x1a\n')
    is_webp = content.startswith(b'RIFF') and len(content) >= 12 and content[8:12] == b'WEBP'

    if not (is_jpeg or is_png or is_webp):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fichier image invalide. Seuls JPG, PNG, WEBP sont autorisés.",
        )

    upload_dir = Path("uploads/clients")
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = ".jpg"
    if is_png:
        ext = ".png"
    elif is_webp:
        ext = ".webp"
    filename = f"{uuid.uuid4().hex}{ext}"
    target_path = upload_dir / filename

    with open(target_path, "wb") as buffer:
        buffer.write(content)

    return {"image_url": f"/static/uploads/clients/{filename}"}

def _to_response(c) -> ClientResponse:
    return ClientResponse(
        id=str(c.id),
        first_name=c.first_name,
        last_name=c.last_name,
        email=c.email,
        phone=c.phone,
        cin_number=getattr(c, "cin_number", None),
        identity_card_image=c.identity_card_image,
        license_number=getattr(c, "license_number", None),
        driving_license_image=c.driving_license_image,
        photo_url=getattr(c, "photo_url", None),
        notes=getattr(c, "notes", None),
        status=getattr(c, "status", "ACTIVE"),
        created_at=c.created_at,
        updated_at=c.updated_at,
        version=c.version,
    )

@router.post("", include_in_schema=False, response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    body: ClientCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_CREATE)),
    lang: str = Depends(get_language),
):
    service = ClientService(db)
    result = await service.create_client(body, created_by=UUID(current_user["sub"]), lang=lang)
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return _to_response(result["client"])

@router.get("", include_in_schema=False, response_model=ClientListResponse)
@router.get("/", response_model=ClientListResponse)
async def list_clients(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_READ)),
):
    service = ClientService(db)
    result = await service.list_clients(page=page, page_size=page_size, search=search, status=status_filter)
    return ClientListResponse(
        clients=[_to_response(c) for c in result["clients"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )

@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_READ)),
    lang: str = Depends(get_language),
):
    service = ClientService(db)
    result = await service.get_client(client_id, lang=lang)
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["error"])
    return _to_response(result["client"])

@router.put("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: UUID,
    body: ClientUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_CREATE)),
    lang: str = Depends(get_language),
):
    service = ClientService(db)
    result = await service.update_client(client_id, body, updated_by=UUID(current_user["sub"]), lang=lang)
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return _to_response(result["client"])

@router.delete("/{client_id}", status_code=status.HTTP_200_OK)
async def delete_client(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.VEHICLES_DELETE)),
    lang: str = Depends(get_language),
):
    service = ClientService(db)
    result = await service.delete_client(client_id, deleted_by=UUID(current_user["sub"]), lang=lang)
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["error"])
    return result

@router.get("/{client_id}/history")
async def get_client_history(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_READ)),
):
    service = ClientService(db)
    history = await service.get_client_history(client_id)
    return {"history": history, "total": len(history)}

@router.get("/{client_id}/rentals")
async def get_client_rentals_report(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_perm(Permission.RESERVATIONS_READ)),
):
    """Canonical client rental report: summary KPIs, rental rows, vehicle breakdown.

    Business rule: CANCELLED rentals are reported but excluded from
    totals; days use the server-stored canonical duration (num_days).
    """
    service = ClientService(db)
    report = await service.get_client_rentals_report(client_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client introuvable")
    return report
