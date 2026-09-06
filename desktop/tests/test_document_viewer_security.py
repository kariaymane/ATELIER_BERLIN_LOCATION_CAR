"""
The desktop must not turn a server-supplied document reference into either a
token leak or a launched executable.

``view_document`` receives whatever is stored on the client record. That value
is writable by any authenticated operator, so these two properties have to hold
on the client side as well, independently of the server-side schema guard.
"""
import pytest

from app.utils.document_viewer import _same_host, _suffix_for, _SAFE_SUFFIXES

BASE = "https://car-rental-system.fly.dev"

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF = b"%PDF-1.7\n" + b"\x00" * 32
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32
MZ = b"MZ\x90\x00" + b"\x00" * 32  # a Windows executable


@pytest.mark.parametrize("url", [
    "https://car-rental-system.fly.dev/static/uploads/clients/a.jpg",
    "https://car-rental-system.fly.dev:443/x.jpg",
])
def test_our_own_api_is_trusted(url):
    assert _same_host(url, "https://car-rental-system.fly.dev:443") or _same_host(url, BASE)


@pytest.mark.parametrize("url", [
    "https://evil.example.com/steal.jpg",
    "http://car-rental-system.fly.dev/x.jpg",              # scheme downgrade
    "https://car-rental-system.fly.dev.evil.com/x.jpg",    # suffix confusion
    "https://evil.com/?x=car-rental-system.fly.dev",
])
def test_no_other_host_is_trusted(url):
    assert not _same_host(url, BASE), "bearer token would have been sent to this host"


@pytest.mark.parametrize("content,expected", [
    (JPEG, ".jpg"), (PNG, ".png"), (PDF, ".pdf"), (WEBP, ".webp"),
])
def test_extension_comes_from_the_bytes(content, expected):
    assert _suffix_for(content, "https://x/whatever.bin") == expected


@pytest.mark.parametrize("url", [
    "https://x/payload.exe", "https://x/payload.hta", "https://x/payload.bat",
    "https://x/payload.ps1", "https://x/payload.sh",
])
def test_an_executable_never_gets_an_executable_extension(url):
    suffix = _suffix_for(MZ, url)
    assert suffix == ".bin"
    assert suffix not in _SAFE_SUFFIXES, "caller must refuse this, not launch it"


def test_a_url_extension_alone_cannot_pick_the_type():
    # Bytes say PDF; the URL claims .exe. The bytes win.
    assert _suffix_for(PDF, "https://x/invoice.exe") == ".pdf"
