"""
Client windows responsiveness — the Clients half of the layout audit.

The Client details window and the Client edition window must stay usable at
every resolution the Desktop targets, and must not break at narrower ones.
Concretely, at each size:

  - the [Voir] button of every document slot stays visible, enabled, inside
    the window, and keeps its full width — nothing may cover it or push it
    off the row;
  - no file path is ever rendered as text (a long generated filename is what
    used to stretch a row and hide [Voir]);
  - the identity fields and the Modifier / Supprimer actions stay inside the
    window;
  - nothing overflows horizontally: no child widget extends past the right
    edge of its window.

Everything runs offscreen; the assertions are about geometry, not pixels.
"""
import os
import sys
from datetime import datetime, timezone

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("CAR_RENTAL_DB_RESET", "1")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QLabel  # noqa: E402

# The resolutions the Desktop targets, plus narrower ones where nothing may
# break even though they are not a target.
RESOLUTIONS = [(1280, 720), (1366, 768), (1600, 900), (1920, 1080)]
EXTREME = [(1024, 600), (900, 560)]

STORED_DOCS = {
    "identity_card_image": "/static/uploads/clients/9f2c1b7e4a8d3c6f0b5e2a91.jpg",
    "identity_card_image_back": "/static/uploads/clients/1a2b3c4d5e6f7a8b9c0d1e2f.jpg",
    "driving_license_image": "/static/uploads/clients/aabbccddeeff00112233445566.jpg",
    "driving_license_image_back": "/static/uploads/clients/ffeeddccbbaa99887766554433.jpg",
    "contract_image": "/static/uploads/clients/00112233445566778899aabbcc.pdf",
}


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def client_row():
    from app.database import init_local_db, get_local_session
    from app.models.client import LocalClient
    init_local_db()
    s = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    s.merge(LocalClient(
        id="cli-resp-1", first_name="Abdelmajid", last_name="El Fassi Fihri",
        phone="+212661234567", email="abdelmajid.elfassifihri@exemple.local",
        address="145 Boulevard Mohammed Zerktouni, Résidence Al Anwar, Casablanca",
        cin_number="BK987654", license_number="PC-2019-445566", status="ACTIVE",
        notes="Client professionnel — facturation société",
        created_at=now, updated_at=now, version=1, **STORED_DOCS,
    ))
    s.commit()
    s.close()
    return {"id": "cli-resp-1", "first_name": "Abdelmajid",
            "last_name": "El Fassi Fihri",
            "phone": "+212661234567",
            "email": "abdelmajid.elfassifihri@exemple.local",
            "address": "145 Boulevard Mohammed Zerktouni, "
                       "Résidence Al Anwar, Casablanca",
            "cin_number": "BK987654", "license_number": "PC-2019-445566",
            "notes": "Client professionnel — facturation société",
            "status": "ACTIVE", **STORED_DOCS}


def _details(qapp, request, row, width, height):
    from app.i18n import set_language
    from app.ui.clients.client_details import ClientDetailsDialog
    set_language("fr")
    dlg = ClientDetailsDialog(row, api_client=None)
    request.addfinalizer(lambda: (dlg.close(), dlg.deleteLater(), qapp.processEvents()))
    dlg.resize(width, height)
    dlg.show()
    qapp.processEvents()
    return dlg


def _edit(qapp, request, row, width, height):
    from app.i18n import set_language
    from app.ui.clients.client_edit import ClientEditDialog
    set_language("fr")
    dlg = ClientEditDialog(row, api_client=None)
    request.addfinalizer(lambda: (dlg.close(), dlg.deleteLater(), qapp.processEvents()))
    dlg.resize(width, height)
    dlg.show()
    qapp.processEvents()
    return dlg


def _view_buttons(dlg):
    return [b for b in dlg.findChildren(QPushButton) if "Voir" in b.text()]


def _assert_no_horizontal_overflow(dlg):
    """No child may extend past the right edge of the window."""
    limit = dlg.width()
    for child in dlg.findChildren(QPushButton) + dlg.findChildren(QLabel):
        if not child.isVisible():
            continue
        right = child.mapTo(dlg, child.rect().topRight()).x()
        assert right <= limit + 1, (
            f"{type(child).__name__} '{child.text()[:30]}' overflows: "
            f"right={right} > window width={limit}")


# ── Client details window ────────────────────────────────────────────────


@pytest.mark.parametrize("width,height", RESOLUTIONS + EXTREME)
def test_details_view_buttons_stay_usable(qapp, request, client_row, width, height):
    dlg = _details(qapp, request, client_row, width, height)
    buttons = _view_buttons(dlg)
    assert len(buttons) == 5, "one [Voir] per document slot"
    for b in buttons:
        assert b.isVisible() and b.isEnabled()
        assert b.width() > 0 and b.height() > 0
        top_left = b.mapTo(dlg, b.rect().topLeft())
        assert top_left.x() >= 0 and top_left.y() >= 0
        assert top_left.x() + b.width() <= dlg.width() + 1


@pytest.mark.parametrize("width,height", RESOLUTIONS + EXTREME)
def test_details_never_renders_a_document_path(
    qapp, request, client_row, width, height
):
    dlg = _details(qapp, request, client_row, width, height)
    texts = [w.text() for w in dlg.findChildren(QLabel)]
    texts += [b.text() for b in dlg.findChildren(QPushButton)]
    for path in STORED_DOCS.values():
        assert not any(path in txt for txt in texts)
        assert not any(path.rsplit("/", 1)[-1] in txt for txt in texts)


@pytest.mark.parametrize("width,height", RESOLUTIONS + EXTREME)
def test_details_edit_and_delete_actions_stay_on_screen(
    qapp, request, client_row, width, height
):
    from app.i18n import t
    dlg = _details(qapp, request, client_row, width, height)
    wanted = (t("clients.edit_client"), t("clients.delete_client"))
    found = [b for b in dlg.findChildren(QPushButton)
             if any(w in b.text() for w in wanted)]
    assert len(found) == 2
    for b in found:
        assert b.isVisible() and b.isEnabled()
        assert b.mapTo(dlg, b.rect().topLeft()).x() + b.width() <= dlg.width() + 1


@pytest.mark.parametrize("width,height", RESOLUTIONS + EXTREME)
def test_details_has_no_horizontal_overflow(
    qapp, request, client_row, width, height
):
    _assert_no_horizontal_overflow(_details(qapp, request, client_row, width, height))


# ── Client edition window ────────────────────────────────────────────────


@pytest.mark.parametrize("width,height", [(1280, 720), (1024, 600), (900, 560)])
def test_edit_view_buttons_keep_their_width(
    qapp, request, client_row, width, height
):
    """A long stored filename must never squeeze [Voir] — it is not rendered,
    and the button's width is fixed regardless of the window size."""
    dlg = _edit(qapp, request, client_row, width, height)
    buttons = _view_buttons(dlg)
    assert len(buttons) == 5
    for b in buttons:
        assert b.isVisible() and b.isEnabled()
        assert b.width() == 90


@pytest.mark.parametrize("width,height", [(1280, 720), (1024, 600), (900, 560)])
def test_edit_never_renders_a_document_path(
    qapp, request, client_row, width, height
):
    dlg = _edit(qapp, request, client_row, width, height)
    texts = [w.text() for w in dlg.findChildren(QLabel)]
    texts += [b.text() for b in dlg.findChildren(QPushButton)]
    for path in STORED_DOCS.values():
        assert not any(path in txt for txt in texts)
        assert not any(path.rsplit("/", 1)[-1] in txt for txt in texts)


@pytest.mark.parametrize("width,height", [(1280, 720), (1024, 600), (900, 560)])
def test_edit_has_no_horizontal_overflow(
    qapp, request, client_row, width, height
):
    _assert_no_horizontal_overflow(_edit(qapp, request, client_row, width, height))


def test_edit_scrolls_rather_than_clipping_on_a_short_window(
    qapp, request, client_row
):
    """Every field must remain reachable on a short screen."""
    from PySide6.QtWidgets import QScrollArea
    dlg = _edit(qapp, request, client_row, 900, 420)
    scrolls = dlg.findChildren(QScrollArea)
    assert scrolls, "the edition form must live in a scroll area"
    assert scrolls[0].widgetResizable()
