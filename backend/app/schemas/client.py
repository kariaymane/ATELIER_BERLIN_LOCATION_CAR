import re

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime

# Document fields hold a reference produced by POST /clients/upload-image, which
# always returns "/static/uploads/clients/<uuid><ext>". Accepting anything else
# lets an operator store an absolute URL that desktop clients would then fetch —
# sending the bearer token to a host of the operator's choosing and opening
# whatever came back. Pin the shape here so only our own upload path can be
# stored; the desktop applies the matching host check on the way out.
_DOC_REF = re.compile(r"^/static/uploads/(clients|vehicles)/[A-Za-z0-9_-]+\.(jpg|jpeg|png|webp|pdf)$")

_DOC_FIELDS = (
    "identity_card_image",
    "identity_card_image_back",
    "driving_license_image",
    "driving_license_image_back",
    "contract_image",
    "photo_url",
)

# Re-exported so the offline push path in SyncService applies the same rule.
# One definition, both entry points — otherwise sync becomes the way around it.
DOCUMENT_FIELDS = frozenset(_DOC_FIELDS)


def is_own_upload_ref(value: str) -> bool:
    """True when *value* is a reference this API's upload endpoint produced."""
    return bool(_DOC_REF.match(value))


def _validate_document_ref(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return value
    if not _DOC_REF.match(value):
        raise ValueError(
            "Référence de document invalide : seuls les chemins /static/uploads/... "
            "produits par le téléversement sont acceptés."
        )
    return value


class ClientCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = None
    cin_number: Optional[str] = Field(None, max_length=50)
    identity_card_image: Optional[str] = None
    identity_card_image_back: Optional[str] = None
    license_number: Optional[str] = Field(None, max_length=50)
    driving_license_image: Optional[str] = None
    driving_license_image_back: Optional[str] = None
    contract_image: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None

    _check_document_refs = field_validator(*_DOC_FIELDS)(_validate_document_ref)

class ClientUpdate(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = None
    cin_number: Optional[str] = Field(None, max_length=50)
    identity_card_image: Optional[str] = None
    identity_card_image_back: Optional[str] = None
    license_number: Optional[str] = Field(None, max_length=50)
    driving_license_image: Optional[str] = None
    driving_license_image_back: Optional[str] = None
    contract_image: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = Field(None, max_length=20)

    _check_document_refs = field_validator(*_DOC_FIELDS)(_validate_document_ref)

class ClientResponse(BaseModel):
    id: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    cin_number: Optional[str] = None
    identity_card_image: Optional[str] = None
    identity_card_image_back: Optional[str] = None
    license_number: Optional[str] = None
    driving_license_image: Optional[str] = None
    driving_license_image_back: Optional[str] = None
    contract_image: Optional[str] = None
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
