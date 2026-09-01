"""ClientDetailsDialog identity documents: four slots (CIN recto/verso,
licence recto/verso), each centered by the LAYOUT, aspect ratio always
preserved, never stretched, correct across window resize and RTL.
"""
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QColor


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def seeded_client():
    from app.database import init_local_db, get_local_session
    from app.models.client import LocalClient
    init_local_db()
    s = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    s.merge(LocalClient(
        id="cli-doc-1", first_name="Nadia", last_name="Alaoui",
        phone="+212600000000", cin_number="AB123456", status="ACTIVE",
        identity_card_image="/static/uploads/clients/cin_front.jpg",
        identity_card_image_back="/static/uploads/clients/cin_back.jpg",
        driving_license_image="/static/uploads/clients/lic_front.jpg",
        created_at=now, updated_at=now, version=1,
    ))
    s.commit()
    s.close()
    return {"id": "cli-doc-1", "first_name": "Nadia", "last_name": "Alaoui"}


def _pixmap(w, h, color="#336699"):
    pm = QPixmap(w, h)
    pm.fill(QColor(color))
    return pm


def _open(qapp, request, row, rtl=False):
    from app.i18n import set_language
    from app.ui.clients.client_details import ClientDetailsDialog
    set_language("ar" if rtl else "fr")
    dlg = ClientDetailsDialog(row, api_client=None)
    request.addfinalizer(lambda: (dlg.close(), dlg.deleteLater(), qapp.processEvents(), set_language("fr")))
    dlg.resize(1080, 720)
    dlg.show()
    qapp.processEvents()
    return dlg


def _assert_fits_and_ratio(label, src_w, src_h):
    pm = label.pixmap()
    assert pm is not None and not pm.isNull()
    assert pm.width() <= label.width() + 1
    assert pm.height() <= label.height() + 1
    src_ratio = src_w / src_h
    out_ratio = pm.width() / pm.height()
    assert abs(src_ratio - out_ratio) / src_ratio < 0.02  # aspect ratio preserved
    assert label.alignment() & Qt.AlignmentFlag.AlignCenter


def test_four_document_slots_exist(qapp, request, seeded_client):
    dlg = _open(qapp, request, seeded_client)
    assert set(dlg._doc_thumbs) == {
        "identity_card_image", "identity_card_image_back",
        "driving_license_image", "driving_license_image_back",
    }


def test_landscape_and_portrait_images_centered_no_distortion(qapp, request, seeded_client):
    dlg = _open(qapp, request, seeded_client)
    wide = _pixmap(1600, 900)
    tall = _pixmap(900, 1600)
    dlg._doc_thumbs["identity_card_image"].setPixmap(wide)
    dlg._doc_thumbs["identity_card_image_back"].setPixmap(tall)
    qapp.processEvents()
    _assert_fits_and_ratio(dlg._doc_thumbs["identity_card_image"], 1600, 900)
    _assert_fits_and_ratio(dlg._doc_thumbs["identity_card_image_back"], 900, 1600)


def test_resize_keeps_aspect_ratio(qapp, request, seeded_client):
    dlg = _open(qapp, request, seeded_client)
    lbl = dlg._doc_thumbs["identity_card_image"]
    lbl.setPixmap(_pixmap(1600, 900))
    qapp.processEvents()
    dlg.resize(1400, 900)
    qapp.processEvents()
    _assert_fits_and_ratio(lbl, 1600, 900)
    dlg.resize(700, 520)
    qapp.processEvents()
    _assert_fits_and_ratio(lbl, 1600, 900)


def test_missing_verso_shows_placeholder(qapp, request, seeded_client):
    dlg = _open(qapp, request, seeded_client)
    back = dlg._doc_thumbs["driving_license_image_back"]
    # no image assigned -> keeps the "document unavailable" placeholder text
    assert back.pixmap() is None or back.pixmap().isNull()
    assert back.text() != ""


def test_rtl_preserves_recto_verso_semantics(qapp, request, seeded_client):
    dlg = _open(qapp, request, seeded_client, rtl=True)
    from app.i18n import t
    # recto slot still keyed to the front image, caption is the recto caption
    assert dlg._doc_captions["identity_card_image"].text() == t("clients.docs_cin_recto")
    assert dlg._doc_captions["identity_card_image_back"].text() == t("clients.docs_cin_verso")
    # grid host forces LTR column order regardless of RTL dialog direction
    host = dlg._doc_thumbs["identity_card_image"].parentWidget()
    while host is not None and host.layoutDirection() != Qt.LayoutDirection.LeftToRight:
        host = host.parentWidget()
    assert host is not None
