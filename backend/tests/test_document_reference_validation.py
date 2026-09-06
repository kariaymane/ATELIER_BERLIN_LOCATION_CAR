"""
A client document field must only ever hold a reference this API produced.

The field is writable by any authenticated operator, and desktop clients fetch
whatever it contains with the logged-in user's bearer token attached. If an
absolute URL could be stored, an operator could point a colleague's desktop at
a host they control and collect that token, then serve back a file of their own
choosing. Pinning the accepted shape at the schema boundary is what stops it.
"""
import pytest
from pydantic import ValidationError

from app.schemas.client import ClientCreate, ClientUpdate

VALID = "/static/uploads/clients/2f8a1c9e4b7d40f1a1b2c3d4e5f60718.jpg"


def _create(**over):
    return ClientCreate(first_name="A", last_name="B", **over)


def test_accepts_a_reference_the_upload_endpoint_produced():
    assert _create(identity_card_image=VALID).identity_card_image == VALID


def test_accepts_absent_and_empty_references():
    assert _create().identity_card_image is None
    assert _create(identity_card_image="").identity_card_image == ""


@pytest.mark.parametrize("hostile", [
    "https://evil.example.com/steal.jpg",          # token exfiltration target
    "http://evil.example.com/steal.jpg",
    "//evil.example.com/steal.jpg",                # protocol-relative
    "/static/uploads/clients/payload.exe",         # executable the OS would launch
    "/static/uploads/clients/payload.hta",
    "/static/uploads/../../etc/passwd",            # traversal
    "/etc/passwd",
    "file:///etc/passwd",
    "/static/uploads/other/x.jpg",                 # outside the upload dirs
])
def test_rejects_anything_else(hostile):
    with pytest.raises(ValidationError):
        _create(identity_card_image=hostile)


@pytest.mark.parametrize("field", [
    "identity_card_image",
    "identity_card_image_back",
    "driving_license_image",
    "driving_license_image_back",
    "contract_image",
    "photo_url",
])
def test_every_document_field_is_guarded_on_create_and_update(field):
    assert getattr(_create(**{field: VALID}), field) == VALID
    with pytest.raises(ValidationError):
        _create(**{field: "https://evil.example.com/x.jpg"})
    with pytest.raises(ValidationError):
        ClientUpdate(**{field: "https://evil.example.com/x.jpg"})


def test_the_sync_push_path_shares_one_rule_with_the_schema():
    """The offline push path must not be a way around the schema guard.

    SyncService applies fields from a raw dict, so it cannot rely on Pydantic.
    It imports the same predicate instead — this pins that they stay one rule.
    """
    from app.schemas.client import DOCUMENT_FIELDS, is_own_upload_ref
    from app.services import sync_service

    assert sync_service.is_own_upload_ref is is_own_upload_ref
    assert sync_service.DOCUMENT_FIELDS is DOCUMENT_FIELDS

    # Every field Pydantic guards is guarded on the push path too.
    assert DOCUMENT_FIELDS == {
        "identity_card_image", "identity_card_image_back",
        "driving_license_image", "driving_license_image_back",
        "contract_image", "photo_url",
    }

    assert is_own_upload_ref(VALID)
    assert not is_own_upload_ref("https://evil.example.com/steal.jpg")
    assert not is_own_upload_ref("/static/uploads/clients/payload.exe")
