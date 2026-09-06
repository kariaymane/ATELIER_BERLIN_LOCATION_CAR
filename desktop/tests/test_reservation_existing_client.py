"""
New reservation with an EXISTING client.

Rules proven end-to-end through the real ``ReservationFormDialog``:

  1. Selecting an existing client immediately loads its FULL record —
     nom, prénom, CIN, téléphone, adresse, email, permis — not a subset.
  2. Its already-stored DOCUMENTS come with it: the user never has to
     re-import a scan the client already has on file.
  3. The reservation reuses that client_id. A new client is created only
     when the user actually chose "Nouveau client".
  4. The saved reservation carries `reservation.customer_id == client.id`.
  5. A document row never renders a file path, and [Voir] is the only
     control that opens a document — it stays visible and full-width no
     matter how long the stored filename is.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"

import pytest
from PySide6.QtCore import QDateTime, QDate, QTime
from PySide6.QtWidgets import QPushButton, QLabel

# Deliberately long generated filenames — this is what used to stretch the
# chooser button across the row and push [Voir] out of reach.
DOCS = {
    "identity_card_image": "/static/uploads/clients/9f2c1b7e4a8d3c6f0b5e2a91ddccbb.jpg",
    "identity_card_image_back": "/static/uploads/clients/1a2b3c4d5e6f7a8b9c0d1e2f3a4b.jpg",
    "driving_license_image": "/static/uploads/clients/aabbccddeeff001122334455667788.jpg",
    "driving_license_image_back": "/static/uploads/clients/ffeeddccbbaa998877665544332211.jpg",
}


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def env(qapp):
    from app.database import init_local_db, get_local_session
    from app.models.vehicle import LocalVehicle
    from app.models.client import LocalClient
    from app.models.reservation import LocalReservation
    init_local_db()
    s = get_local_session()
    s.query(LocalReservation).delete()
    s.query(LocalClient).delete()
    now = datetime.now(timezone.utc).isoformat()
    s.merge(LocalVehicle(
        id="rec-veh", registration="RE-1-A-1", vin="1M8GDM9AXKP042790",
        brand="BMW", model="320d", year=2024, color="Noir",
        fuel_type="DIESEL", transmission="AUTOMATIC", current_mileage=10,
        daily_rental_price=400.0, status="AVAILABLE",
        created_at=now, updated_at=now, version=1))
    s.merge(LocalClient(
        id="rec-cli", first_name="Sami", last_name="Alami",
        phone="0600000000", email="sami@example.test",
        address="12 Rue des Orangers, Casablanca",
        cin_number="AB123456", license_number="PC-2019-445566",
        notes="Client fidèle", status="ACTIVE",
        created_at=now, updated_at=now, version=1, **DOCS))
    s.commit()
    s.close()
    yield
    s = get_local_session()
    s.query(LocalReservation).delete()
    s.query(LocalClient).delete()
    s.query(LocalVehicle).filter_by(id="rec-veh").delete()
    s.commit()
    s.close()


def _vehicle_dict():
    return {"id": "rec-veh", "brand": "BMW", "model": "320d",
            "registration": "RE-1-A-1", "daily_rental_price": 400.0}


def _dialog(request):
    from app.ui.reservations.reservation_list import ReservationFormDialog
    dlg = ReservationFormDialog(_vehicle_dict(), api_client=None)
    request.addfinalizer(dlg.close)
    return dlg


def _select(dlg, client_id):
    for i in range(dlg._client_combo.count()):
        if dlg._client_combo.itemData(i) == client_id:
            dlg._client_combo.setCurrentIndex(i)
            return
    raise AssertionError(f"client {client_id} not offered in the combo")


# ── 1. The full record is loaded ─────────────────────────────────────────


def test_selecting_an_existing_client_loads_every_field(qapp, env, request):
    dlg = _dialog(request)
    _select(dlg, "rec-cli")

    assert dlg._customer_name.text() == "Sami Alami"
    assert dlg._customer_phone.text() == "0600000000"
    assert dlg._customer_address.text() == "12 Rue des Orangers, Casablanca"
    assert dlg._customer_email.text() == "sami@example.test"
    assert dlg._customer_cin.text() == "AB123456"


def test_no_field_is_left_empty_by_the_selection(qapp, env, request):
    """A selection must never produce a half-filled client."""
    dlg = _dialog(request)
    _select(dlg, "rec-cli")
    for widget in (dlg._customer_name, dlg._customer_phone,
                   dlg._customer_address, dlg._customer_email,
                   dlg._customer_cin):
        assert widget.text().strip() != ""


# ── 2. The stored documents come with the client ─────────────────────────


def test_existing_documents_are_recovered_not_re_asked(qapp, env, request):
    dlg = _dialog(request)
    _select(dlg, "rec-cli")

    assert dlg._id_card_path == DOCS["identity_card_image"]
    assert dlg._id_card_back_path == DOCS["identity_card_image_back"]
    assert dlg._license_path == DOCS["driving_license_image"]
    assert dlg._license_back_path == DOCS["driving_license_image_back"]


def test_document_rows_report_presence_without_showing_a_path(
    qapp, env, request
):
    from app.i18n import t
    dlg = _dialog(request)
    _select(dlg, "rec-cli")

    for attr in ("_id_card_path", "_id_card_back_path",
                 "_license_path", "_license_back_path"):
        assert t("clients.doc_present") in dlg._doc_state_labels[attr].text()

    texts = [w.text() for w in dlg.findChildren(QLabel)]
    texts += [b.text() for b in dlg.findChildren(QPushButton)]
    for path in DOCS.values():
        assert not any(path in txt for txt in texts)
        assert not any(path.rsplit("/", 1)[-1] in txt for txt in texts), \
            "the generated filename must never become a widget label"


def test_view_button_is_the_only_opener_and_keeps_its_width(
    qapp, env, request
):
    dlg = _dialog(request)
    _select(dlg, "rec-cli")
    dlg.resize(900, 700)
    dlg.show()
    qapp.processEvents()

    view_buttons = [b for b in dlg.findChildren(QPushButton) if "Voir" in b.text()]
    assert len(view_buttons) == 4, "one [Voir] per document row"
    for b in view_buttons:
        assert b.isVisible() and b.isEnabled()
        assert b.width() == 90
        assert b.mapTo(dlg, b.rect().topLeft()).x() + b.width() <= dlg.width() + 1


def test_switching_back_to_new_client_clears_the_documents(qapp, env, request):
    from app.i18n import t
    dlg = _dialog(request)
    _select(dlg, "rec-cli")
    dlg._client_combo.setCurrentIndex(0)  # "Nouveau client"

    assert dlg._id_card_path == ""
    assert dlg._license_back_path == ""
    assert dlg._customer_address.text() == ""
    for attr in ("_id_card_path", "_license_back_path"):
        assert dlg._doc_state_labels[attr].text() == t("clients.doc_absent")


# ── 3 & 4. The same client_id is reused ──────────────────────────────────


def _fill_dates(dlg):
    start = datetime.now() + timedelta(days=5)
    end = start + timedelta(days=3)
    dlg._start_dt.setDateTime(QDateTime(
        QDate(start.year, start.month, start.day), QTime(9, 0)))
    dlg._end_dt.setDateTime(QDateTime(
        QDate(end.year, end.month, end.day), QTime(9, 0)))


def test_saving_emits_the_existing_client_id(qapp, env, request):
    dlg = _dialog(request)
    _select(dlg, "rec-cli")
    _fill_dates(dlg)

    captured = {}
    dlg.saved.connect(lambda payload: captured.update(payload))
    dlg._on_save()

    assert captured["customer_id"] == "rec-cli", \
        "an existing client must be REUSED, never re-created"
    assert captured["customer_name"] == "Sami Alami"
    assert captured["customer_address"] == "12 Rue des Orangers, Casablanca"


def test_untouched_existing_client_triggers_no_write_back(qapp, env, request):
    dlg = _dialog(request)
    _select(dlg, "rec-cli")
    _fill_dates(dlg)

    captured = {}
    dlg.saved.connect(lambda payload: captured.update(payload))
    dlg._on_save()

    assert captured["client_field_updates"] is None, \
        "leaving the form untouched must not queue a spurious client UPDATE"


def test_editing_an_existing_client_writes_back_including_the_address(
    qapp, env, request
):
    dlg = _dialog(request)
    _select(dlg, "rec-cli")
    dlg._customer_address.setText("99 Boulevard Zerktouni, Casablanca")
    _fill_dates(dlg)

    captured = {}
    dlg.saved.connect(lambda payload: captured.update(payload))
    dlg._on_save()

    updates = captured["client_field_updates"]
    assert updates is not None
    assert updates["address"] == "99 Boulevard Zerktouni, Casablanca"
    assert captured["customer_id"] == "rec-cli", \
        "an edit must still target the SAME client"


def test_new_client_selection_emits_no_customer_id(qapp, env, request):
    dlg = _dialog(request)
    dlg._client_combo.setCurrentIndex(0)
    dlg._customer_name.setText("Nouveau Passant")
    dlg._customer_phone.setText("0655555555")
    _fill_dates(dlg)

    captured = {}
    dlg.saved.connect(lambda payload: captured.update(payload))
    dlg._on_save()

    assert captured["customer_id"] is None, \
        "only an explicit 'Nouveau client' creates a client"


def test_inactive_clients_are_not_offered(qapp, env, request):
    """A deleted (deactivated) client must not come back in the picker."""
    from app.database import get_local_session
    from app.models.client import LocalClient
    s = get_local_session()
    row = s.query(LocalClient).filter_by(id="rec-cli").one()
    row.status = "INACTIVE"
    s.commit()
    s.close()

    dlg = _dialog(request)
    offered = [dlg._client_combo.itemData(i)
               for i in range(dlg._client_combo.count())]
    assert "rec-cli" not in offered
