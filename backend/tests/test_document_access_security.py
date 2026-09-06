"""
Client-document security matrix.

The product stores identity documents (CIN, driving licence, contract). These
tests pin what actually protects them, so the guarantee is a verified fact
rather than an assumption:

  * the API that reveals a document's URL is authenticated and RBAC-gated;
  * upload is RBAC-gated, size-capped and magic-byte validated;
  * the stored filename is server-generated randomness — the client never
    influences the path, so there is no traversal and no IDOR/enumeration;
  * the static mount refuses directory listing and path traversal.

KNOWN AND DELIBERATE (documented, not asserted as "denied"): a document's bytes
are served from /static/uploads/... without an Authorization header. Access
control there is the unguessable uuid4 path, because the Android client opens
documents with an external ACTION_VIEW intent that cannot carry a bearer token.
``test_static_document_bytes_are_reachable_by_url_alone`` records that
truthfully so a future change cannot quietly assume otherwise.
"""
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff" + b"\x00" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"\x00" * 64
ELF = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 64
DOS_EXE = b"MZ\x90\x00" + b"\x00" * 64
SCRIPT = b"#!/bin/sh\nrm -rf /\n"


@pytest.mark.asyncio
class TestDocumentUploadAuthorization:
    async def test_upload_without_a_token_is_denied(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/clients/upload-image", files={"file": ("x.png", PNG, "image/png")}
        )
        assert r.status_code in (401, 403)

    async def test_upload_with_an_invalid_token_is_denied(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/clients/upload-image",
            files={"file": ("x.png", PNG, "image/png")},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert r.status_code in (401, 403)

    async def test_read_only_role_cannot_upload_a_document(self, client: AsyncClient):
        """MOBILE_USER has no RESERVATIONS_CREATE -> no document upload."""
        from app.dependencies import get_jwt_handler
        token = get_jwt_handler().create_access_token(
            user_id=str(uuid.uuid4()), role="MOBILE_USER"
        )
        r = await client.post(
            "/api/v1/clients/upload-image",
            files={"file": ("x.png", PNG, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    async def test_authorized_role_may_upload(self, client: AsyncClient, admin_token):
        r = await client.post(
            "/api/v1/clients/upload-image",
            files={"file": ("x.png", PNG, "image/png")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        assert r.json()["image_url"].startswith("/static/uploads/clients/")


@pytest.mark.asyncio
class TestDocumentUploadValidation:
    @pytest.mark.parametrize(
        "payload,ext", [(JPEG, ".jpg"), (PNG, ".png"), (WEBP, ".webp"), (PDF, ".pdf")]
    )
    async def test_accepted_types_are_stored_with_a_type_derived_extension(
        self, client: AsyncClient, admin_token, payload, ext
    ):
        r = await client.post(
            "/api/v1/clients/upload-image",
            files={"file": ("whatever.bin", payload, "application/octet-stream")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        # The extension follows the BYTES, never the submitted filename.
        assert r.json()["image_url"].endswith(ext)

    @pytest.mark.parametrize("payload", [ELF, DOS_EXE, SCRIPT, b"", b"plain text"])
    async def test_executable_and_untrusted_content_is_rejected(
        self, client: AsyncClient, admin_token, payload
    ):
        r = await client.post(
            "/api/v1/clients/upload-image",
            files={"file": ("evil.png", payload, "image/png")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 400, "content-type must not override magic bytes"

    async def test_a_php_or_exe_name_cannot_survive_onto_disk(
        self, client: AsyncClient, admin_token
    ):
        r = await client.post(
            "/api/v1/clients/upload-image",
            files={"file": ("shell.php", PNG, "image/png")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        url = r.json()["image_url"]
        assert url.endswith(".png") and "php" not in url

    async def test_a_traversal_filename_cannot_escape_the_upload_directory(
        self, client: AsyncClient, admin_token
    ):
        r = await client.post(
            "/api/v1/clients/upload-image",
            files={"file": ("../../../../etc/cron.d/x.png", PNG, "image/png")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        url = r.json()["image_url"]
        assert ".." not in url
        # uuid4().hex + extension — nothing the caller supplied.
        name = url.rsplit("/", 1)[-1]
        stem = name.rsplit(".", 1)[0]
        assert len(stem) == 32 and int(stem, 16) >= 0

    async def test_stored_names_are_unguessable_and_never_collide(
        self, client: AsyncClient, admin_token
    ):
        urls = set()
        for _ in range(5):
            r = await client.post(
                "/api/v1/clients/upload-image",
                files={"file": ("same-name.png", PNG, "image/png")},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            urls.add(r.json()["image_url"])
        assert len(urls) == 5, "identical uploads must not overwrite each other"


@pytest.mark.asyncio
class TestDocumentReferenceExposure:
    async def test_client_records_are_not_readable_without_a_token(
        self, client: AsyncClient
    ):
        """The URL of a document is only learnable through an authorized call."""
        r = await client.get("/api/v1/clients/")
        assert r.status_code in (401, 403)

    async def test_client_records_reject_an_invalid_token(self, client: AsyncClient):
        r = await client.get(
            "/api/v1/clients/", headers={"Authorization": "Bearer forged.token.value"}
        )
        assert r.status_code == 401

    async def test_uuid_substitution_on_a_client_id_does_not_leak_a_record(
        self, client: AsyncClient, admin_token
    ):
        r = await client.get(
            f"/api/v1/clients/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 404, "a guessed id must not return someone's documents"


@pytest.mark.asyncio
class TestStaticMountHardening:
    @pytest.mark.parametrize(
        "path",
        [
            "/static/uploads/",
            "/static/uploads/clients/",
            "/static/uploads/../.env",
            "/static/uploads/../../.env",
            "/static/uploads/clients/../../../etc/passwd",
            "/static/uploads/%2e%2e%2f%2e%2e%2f.env",
            "/static/uploads/....//....//.env",
        ],
    )
    async def test_no_listing_and_no_traversal(self, client: AsyncClient, path):
        r = await client.get(path)
        assert r.status_code in (403, 404), f"{path} -> {r.status_code}"
        assert b"JWT_SECRET" not in r.content
        assert b"POSTGRES_PASSWORD" not in r.content

    async def test_unknown_document_path_is_a_plain_404(self, client: AsyncClient):
        r = await client.get(f"/static/uploads/clients/{uuid.uuid4().hex}.jpg")
        assert r.status_code == 404

    async def test_static_document_bytes_are_reachable_by_url_alone(
        self, client: AsyncClient, admin_token, tmp_path, monkeypatch
    ):
        """DOCUMENTS THE ACTUAL GUARANTEE — a capability URL, not a bearer token.

        The bytes behind an uploaded document are served by the StaticFiles
        mount with no Authorization check. What protects them is that the path
        is a 128-bit uuid4 that only an authorized API response reveals.

        This is deliberate: the Android client opens documents with an external
        ACTION_VIEW intent, which cannot attach a bearer token. If document
        access is ever moved behind authentication, this test must be updated
        together with the mobile document viewer — it exists so that change is
        a conscious one.
        """
        r = await client.post(
            "/api/v1/clients/upload-image",
            files={"file": ("cin.png", PNG, "image/png")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        url = r.json()["image_url"]
        stored = Path("uploads/clients") / url.rsplit("/", 1)[-1]
        try:
            assert stored.exists()
            anon = await client.get(url)  # deliberately no Authorization header
            assert anon.status_code == 200
            assert anon.content == PNG
        finally:
            stored.unlink(missing_ok=True)
