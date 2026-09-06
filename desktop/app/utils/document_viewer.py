"""
Document viewer utility for ATELIER BERLIN LOCATION CAR.
Opens client documents (images and PDFs) using the system default application.
"""
import os
import sys
import logging
import pathlib
import tempfile
from pathlib import Path
from typing import Optional

from urllib.parse import urlparse

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

logger = logging.getLogger(__name__)

# A document reference reaches this module from the server, and the field that
# carries it (``client.identity_card_image``) is writable by any authenticated
# operator. It is therefore UNTRUSTED input, and two things must never follow
# from it: leaking the bearer token to a host of the writer's choosing, and
# handing the operating system a file whose type the writer picked.
#
# _same_host  — the Authorization header goes out only to the API we log in to.
# _SAFE_SUFFIXES — the temp file gets an extension derived from what the bytes
#                  actually are, so a reference ending in ".exe"/".hta"/".bat"
#                  cannot become an executable that QDesktopServices launches.
_SAFE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}

_MAGIC = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"%PDF-", ".pdf"),
)


def _same_host(candidate: str, base: str) -> bool:
    """True when *candidate* points at the same scheme/host/port as *base*."""
    try:
        c, b = urlparse(candidate), urlparse(base)
    except ValueError:
        return False
    return (c.scheme, c.hostname, c.port) == (b.scheme, b.hostname, b.port)


def _suffix_for(content: bytes, url: str) -> str:
    """Pick a temp-file extension from the CONTENT, never from the URL alone."""
    for magic, suffix in _MAGIC:
        if content.startswith(magic):
            return suffix
    if content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP":
        return ".webp"
    declared = pathlib.Path(urlparse(url).path).suffix.lower()
    return declared if declared in _SAFE_SUFFIXES else ".bin"


def view_document(url_or_path: str, api_client=None, parent=None) -> bool:
    """Open a document (image or PDF) in the system's native viewer.

    Supports local file paths and remote URLs. Remote documents are
    downloaded with authentication to a temporary file and launched locally.
    """
    if not url_or_path:
        if parent:
            QMessageBox.information(parent, "Information", "Aucun document associé.")
        return False

    url_str = str(url_or_path).strip()

    # Case 1: Local file exists directly
    if os.path.exists(url_str):
        abs_path = os.path.abspath(url_str)
        return QDesktopServices.openUrl(QUrl.fromLocalFile(abs_path))

    # Case 2: Remote URL or static path
    if url_str.startswith("http://") or url_str.startswith("https://") or url_str.startswith("/"):
        from app.config import API_BASE_URL
        base = api_client._base_url if (api_client and hasattr(api_client, "_base_url")) else API_BASE_URL
        if not (url_str.startswith("http://") or url_str.startswith("https://")):
            full_url = f"{base.rstrip('/')}/{url_str.lstrip('/')}"
        else:
            full_url = url_str

        # Download to a temporary file so the native PDF reader or image viewer can open it
        # Refuse to touch a document hosted anywhere but our own API. This is
        # what stops a reference planted in the database from turning into
        # either a token leak or an outbound request to an attacker's host.
        if not _same_host(full_url, base):
            logger.warning("Refusing document from an untrusted host: %s", urlparse(full_url).netloc)
            if parent:
                QMessageBox.warning(parent, "Erreur", "Document refusé : hôte non autorisé.")
            return False

        try:
            import httpx
            headers = {}
            if api_client and getattr(api_client, "_access_token", None):
                headers["Authorization"] = f"Bearer {api_client._access_token}"

            with httpx.Client(timeout=15.0, follow_redirects=False) as client:
                resp = client.get(full_url, headers=headers)
                if resp.status_code == 200:
                    suffix = _suffix_for(resp.content, full_url)
                    if suffix not in _SAFE_SUFFIXES:
                        logger.warning("Refusing document of an unsupported type: %s", full_url)
                        if parent:
                            QMessageBox.warning(parent, "Erreur", "Document refusé : type de fichier non pris en charge.")
                        return False
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp_path = tmp.name
                        tmp.write(resp.content)
                    return QDesktopServices.openUrl(QUrl.fromLocalFile(tmp_path))
                logger.warning("Failed to download document (%s): %s", resp.status_code, full_url)
        except Exception as e:
            logger.warning("Error fetching remote document for viewing: %s", e)

        return False

    # Case 3: Relative path in app or data dir
    from app.config import DATA_DIR
    candidate = DATA_DIR / url_str
    if candidate.exists():
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate.resolve())))

    if parent:
        QMessageBox.warning(parent, "Erreur", f"Impossible d'ouvrir le document : {url_str}")
    return False
