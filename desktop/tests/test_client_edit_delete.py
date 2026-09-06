"""
Client window: modification and deletion.

Rules verified here (they mirror the backend contract in
``backend/tests/test_client_edit_delete.py``):

EDITION
  - Editing writes back to the SAME client_id — never a second client.
  - Untouched fields are not sent; the server leaves them alone.
  - An emptied optional field is sent as None — an explicit CLEAR.
  - first_name / last_name are refused when emptied (NOT NULL columns).
  - Documents can be added, replaced and removed independently: removing the
    CIN verso never disturbs the CIN recto.
  - The committed change reaches the local cache immediately.

DELETION
  - A client with reservations is DEACTIVATED (history preserved).
  - A client with none is physically DELETED.

DOCUMENT ROWS
  - A document row never renders a file path, and [Voir] keeps a fixed width
    so nothing can cover it or push it off the row.
"""
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"

import pytest
from PySide6.QtWidgets import QPushButton, QTextEdit


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


CLIENT_ID = "cli-edit-1"


@pytest.fixture()
def seeded_client():
    from app.database import init_local_db, get_local_session
    from app.models.client import LocalClient
    from app.models.reservation import LocalReservation
    init_local_db()
    s = get_local_session()
    s.query(LocalReservation).delete()
    s.query(LocalClient).delete()
    now = datetime.now(timezone.utc).isoformat()
    s.merge(LocalClient(
        id=CLIENT_ID, first_name="Sami", last_name="Alami",
        phone="0600000000", email="sami@example.test",
        address="12 Rue des Orangers, Casablanca",
        cin_number="AB123456", license_number="L-99", status="ACTIVE",
        identity_card_image="/static/uploads/clients/cin_r.jpg",
        identity_card_image_back="/static/uploads/clients/cin_v.jpg",
        driving_license_image="/static/uploads/clients/lic_r.jpg",
        contract_image="/static/uploads/clients/contrat.pdf",
        notes="Client fidèle",
        created_at=now, updated_at=now, version=1,
    ))
    s.commit()
    s.close()
    return {
        "id": CLIENT_ID, "first_name": "Sami", "last_name": "Alami",
        "phone": "0600000000", "email": "sami@example.test",
        "address": "12 Rue des Orangers, Casablanca",
        "cin_number": "AB123456", "license_number": "L-99",
        "identity_card_image": "/static/uploads/clients/cin_r.jpg",
        "identity_card_image_back": "/static/uploads/clients/cin_v.jpg",
        "driving_license_image": "/static/uploads/clients/lic_r.jpg",
        "driving_license_image_back": None,
        "contract_image": "/static/uploads/clients/contrat.pdf",
        "notes": "Client fidèle", "status": "ACTIVE",
    }


class FakeApi:
    """Records what the dialog sends to the canonical endpoints."""

    def __init__(self, delete_result=None):
        self.updates = []
        self.deletes = []
        self.uploads = []
        self._delete_result = delete_result or {"strategy": "DELETED"}
        self._access_token = "t"

    def update_client(self, cid, data):
        self.updates.append((cid, dict(data)))
        return {"id": cid, **data}

    def delete_client(self, cid):
        self.deletes.append(cid)
        return self._delete_result

    def upload_client_image(self, path):
        self.uploads.append(path)
        return {"image_url": f"/static/uploads/clients/uploaded_{len(self.uploads)}.jpg"}


def _edit(qapp, request, row, api=None):
    from app.i18n import set_language
    from app.ui.clients.client_edit import ClientEditDialog
    set_language("fr")
    dlg = ClientEditDialog(row, api_client=api,
                           device_id="dev-1", user_id="usr-1")
    request.addfinalizer(lambda: (dlg.close(), dlg.deleteLater(), qapp.processEvents()))
    dlg.show()
    qapp.processEvents()
    return dlg


def _local_client():
    from app.database import get_local_session
    from app.models.client import LocalClient
    s = get_local_session()
    try:
        return s.query(LocalClient).filter_by(id=CLIENT_ID).one_or_none()
    finally:
        s.close()


# ── Edition ───────────────────────────────────────────────────────────

def test_all_client_fields_are_prefilled(qapp, request, seeded_client):
    dlg = _edit(qapp, request, seeded_client)
    assert dlg._inputs["first_name"].text() == "Sami"
    assert dlg._inputs["last_name"].text() == "Alami"
    assert dlg._inputs["phone"].text() == "0600000000"
    assert dlg._inputs["address"].text() == "12 Rue des Orangers, Casablanca"
    assert dlg._inputs["email"].text() == "sami@example.test"
    assert dlg._inputs["cin_number"].text() == "AB123456"
    assert dlg._inputs["license_number"].text() == "L-99"
    assert dlg._inputs["notes"].toPlainText() == "Client fidèle"


def test_edit_updates_the_same_client_id(qapp, request, seeded_client):
    api = FakeApi()
    dlg = _edit(qapp, request, seeded_client, api)
    dlg._inputs["phone"].setText("0611111111")
    dlg._on_save()

    assert len(api.updates) == 1
    cid, payload = api.updates[0]
    assert cid == CLIENT_ID, "the edit must target the original client_id"
    assert payload == {"phone": "0611111111"}, "only what changed is sent"
    assert _local_client().phone == "0611111111"


def test_edit_never_creates_a_second_client(qapp, request, seeded_client):
    from app.database import get_local_session
    from app.models.client import LocalClient
    api = FakeApi()
    dlg = _edit(qapp, request, seeded_client, api)
    dlg._inputs["phone"].setText("0622222222")
    dlg._on_save()

    s = get_local_session()
    try:
        assert s.query(LocalClient).count() == 1
    finally:
        s.close()


def test_untouched_fields_are_not_sent(qapp, request, seeded_client):
    api = FakeApi()
    dlg = _edit(qapp, request, seeded_client, api)
    dlg._inputs["address"].setText("99 Boulevard Zerktouni, Casablanca")
    dlg._on_save()
    _cid, payload = api.updates[0]
    assert set(payload) == {"address"}


def test_emptied_optional_field_is_sent_as_an_explicit_clear(
    qapp, request, seeded_client
):
    api = FakeApi()
    dlg = _edit(qapp, request, seeded_client, api)
    dlg._inputs["email"].setText("")
    dlg._on_save()
    _cid, payload = api.updates[0]
    assert payload == {"email": None}, "emptying a field must CLEAR it"
    assert _local_client().email is None


def test_emptied_name_is_refused(qapp, request, seeded_client, monkeypatch):
    """A client can never be left nameless — and nothing is sent."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    api = FakeApi()
    dlg = _edit(qapp, request, seeded_client, api)
    dlg._inputs["first_name"].setText("   ")
    dlg._on_save()
    assert api.updates == []
    assert _local_client().first_name == "Sami"


# ── Documents ─────────────────────────────────────────────────────────

def test_five_document_slots_are_editable(qapp, request, seeded_client):
    dlg = _edit(qapp, request, seeded_client)
    assert set(dlg._doc_intent) == {
        "identity_card_image", "identity_card_image_back",
        "driving_license_image", "driving_license_image_back",
        "contract_image",
    }


def test_removing_one_document_leaves_the_others_alone(
    qapp, request, seeded_client
):
    api = FakeApi()
    dlg = _edit(qapp, request, seeded_client, api)
    dlg._remove_document("identity_card_image_back")
    dlg._on_save()

    _cid, payload = api.updates[0]
    assert payload == {"identity_card_image_back": None}
    row = _local_client()
    assert row.identity_card_image_back is None
    assert row.identity_card_image == "/static/uploads/clients/cin_r.jpg", \
        "removing the verso must never remove the recto"
    assert row.contract_image == "/static/uploads/clients/contrat.pdf"


def test_adding_a_document_uploads_and_stores_the_server_url(
    qapp, request, seeded_client, tmp_path
):
    api = FakeApi()
    dlg = _edit(qapp, request, seeded_client, api)
    local = tmp_path / "permis_verso.jpg"
    local.write_bytes(b"\xff\xd8\xffdata")
    dlg._doc_intent["driving_license_image_back"] = ("SET", str(local))
    dlg._on_save()

    assert api.uploads == [str(local)]
    _cid, payload = api.updates[0]
    assert payload["driving_license_image_back"].startswith("/static/uploads/clients/")
    assert _local_client().driving_license_image_back == \
        payload["driving_license_image_back"]


def test_removing_a_not_yet_saved_choice_cancels_it(qapp, request, seeded_client):
    dlg = _edit(qapp, request, seeded_client)
    dlg._doc_intent["contract_image"] = ("SET", "/tmp/whatever.pdf")
    dlg._remove_document("contract_image")
    assert dlg._doc_intent["contract_image"] is None, \
        "undoing a fresh pick must not schedule a deletion of the stored one"


def test_document_rows_never_render_a_file_path(qapp, request, seeded_client):
    """The path must never appear as text: it is what used to cover [Voir]."""
    dlg = _edit(qapp, request, seeded_client)
    stored_paths = [
        "/static/uploads/clients/cin_r.jpg",
        "/static/uploads/clients/cin_v.jpg",
        "/static/uploads/clients/lic_r.jpg",
        "/static/uploads/clients/contrat.pdf",
    ]
    from PySide6.QtWidgets import QLabel
    texts = [w.text() for w in dlg.findChildren(QLabel)]
    texts += [b.text() for b in dlg.findChildren(QPushButton)]
    for path in stored_paths:
        assert not any(path in txt for txt in texts)
        assert not any(path.split("/")[-1] in txt for txt in texts)


def test_view_button_keeps_a_fixed_width_and_stays_visible(
    qapp, request, seeded_client
):
    dlg = _edit(qapp, request, seeded_client)
    view_buttons = [b for b in dlg.findChildren(QPushButton) if "Voir" in b.text()]
    assert len(view_buttons) == 5, "one [Voir] per document slot"
    for b in view_buttons:
        assert b.isVisible()
        assert b.width() == 90, "a fixed width — nothing can squeeze it away"
        assert b.isEnabled()


def test_state_label_reports_presence_not_a_path(qapp, request, seeded_client):
    from app.i18n import t
    dlg = _edit(qapp, request, seeded_client)
    assert t("clients.doc_present") in dlg._doc_state_labels["identity_card_image"].text()
    assert dlg._doc_state_labels["driving_license_image_back"].text() == \
        t("clients.doc_absent")


# ── Deletion ──────────────────────────────────────────────────────────

def _details(qapp, request, row, api):
    from app.i18n import set_language
    from app.ui.clients.client_details import ClientDetailsDialog
    set_language("fr")
    dlg = ClientDetailsDialog(row, api_client=api,
                              device_id="dev-1", user_id="usr-1")
    request.addfinalizer(lambda: (dlg.close(), dlg.deleteLater(), qapp.processEvents()))
    return dlg


def test_details_window_offers_edit_and_delete(qapp, request, seeded_client):
    dlg = _details(qapp, request, seeded_client, None)
    from app.i18n import t
    labels = [b.text() for b in dlg.findChildren(QPushButton)]
    assert any(t("clients.edit_client") in x for x in labels)
    assert any(t("clients.delete_client") in x for x in labels)


def test_client_without_reservations_is_physically_deleted(
    qapp, request, seeded_client, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    api = FakeApi(delete_result={"strategy": "DELETED"})
    dlg = _details(qapp, request, seeded_client, api)
    dlg._on_delete_client()

    assert api.deletes == [CLIENT_ID]
    assert _local_client() is None


def test_client_with_reservations_is_deactivated_not_destroyed(
    qapp, request, seeded_client, monkeypatch
):
    from app.database import get_local_session
    from app.models.reservation import LocalReservation
    from PySide6.QtWidgets import QMessageBox

    now = datetime.now(timezone.utc)
    s = get_local_session()
    s.merge(LocalReservation(
        id="res-del-1", vehicle_id="veh-1", customer_id=CLIENT_ID,
        customer_name="Sami Alami", customer_phone="0600000000",
        start_datetime=now.isoformat(), end_datetime=now.isoformat(),
        daily_price=400.0, num_days=3, total_price=1200.0, deposit=0.0,
        payment_status="PENDING", status="ACTIVE",
        created_at=now.isoformat(), updated_at=now.isoformat(), version=1,
    ))
    s.commit()
    s.close()

    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    api = FakeApi(delete_result={"strategy": "DEACTIVATED", "linked_reservations": 1})
    dlg = _details(qapp, request, seeded_client, api)
    assert dlg._count_local_reservations() == 1
    dlg._on_delete_client()

    row = _local_client()
    assert row is not None, "a client with history is never destroyed"
    assert row.status == "INACTIVE"

    s = get_local_session()
    try:
        kept = s.query(LocalReservation).filter_by(id="res-del-1").one_or_none()
        assert kept is not None and kept.customer_id == CLIENT_ID
    finally:
        s.close()


def test_delete_is_abandoned_when_the_user_declines(
    qapp, request, seeded_client, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.No)
    api = FakeApi()
    dlg = _details(qapp, request, seeded_client, api)
    dlg._on_delete_client()
    assert api.deletes == []
    assert _local_client() is not None

def test_a_pdf_document_reports_presence_instead_of_a_dead_spinner(
    qapp, request, seeded_client
):
    """The signed contract is normally a PDF, which has no image preview.

    The slot must say the document is on file — never sit on a loading state
    that can never resolve — and [Voir] must still open it.
    """
    from app.i18n import t
    from app.ui.clients.client_details import ClientDetailsDialog
    dlg = ClientDetailsDialog(seeded_client, api_client=None)
    request.addfinalizer(lambda: (dlg.close(), dlg.deleteLater(), qapp.processEvents()))
    dlg.show()
    qapp.processEvents()

    contract = dlg._doc_thumbs["contract_image"]
    assert "⏳" not in contract.text()
    assert t("clients.doc_present") in contract.text()

    # An image slot still goes through the thumbnail cache.
    assert "⏳" in dlg._doc_thumbs["identity_card_image"].text() or \
        dlg._doc_thumbs["identity_card_image"].full_pixmap is not None


def test_an_empty_slot_states_the_document_is_missing(
    qapp, request, seeded_client
):
    from app.i18n import t
    from app.ui.clients.client_details import ClientDetailsDialog
    row = dict(seeded_client, driving_license_image_back=None)
    dlg = ClientDetailsDialog(row, api_client=None)
    request.addfinalizer(lambda: (dlg.close(), dlg.deleteLater(), qapp.processEvents()))
    dlg.show()
    qapp.processEvents()
    assert dlg._doc_thumbs["driving_license_image_back"].text() == t("clients.doc_missing")

# ── Server outcomes are not collapsed ─────────────────────────────────

def test_a_server_refusal_writes_nothing_locally_and_queues_nothing(
    qapp, request, seeded_client, monkeypatch
):
    """Replaying a write the server already refused would fail again and would
    leave the cache disagreeing with PostgreSQL."""
    from PySide6.QtWidgets import QMessageBox
    from app.database import get_local_session
    from app.models.sync_queue import SyncQueueItem
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    class RefusingApi(FakeApi):
        def update_client(self, cid, data):
            self.updates.append((cid, dict(data)))
            return {"error": "Numéro de téléphone déjà utilisé"}

    api = RefusingApi()
    dlg = _edit(qapp, request, seeded_client, api)
    dlg._inputs["phone"].setText("0633333333")
    dlg._on_save()

    assert _local_client().phone == "0600000000", \
        "a refused write must not reach the local mirror"
    s = get_local_session()
    try:
        queued = s.query(SyncQueueItem).filter_by(entity_id=CLIENT_ID).count()
        assert queued == 0, "a refused write must not be queued for retry"
    finally:
        s.close()


def test_an_unreachable_server_writes_locally_and_queues_the_change(
    qapp, request, seeded_client
):
    from app.database import get_local_session
    from app.models.sync_queue import SyncQueueItem

    class OfflineApi(FakeApi):
        def update_client(self, cid, data):
            return None  # network failure

    api = OfflineApi()
    dlg = _edit(qapp, request, seeded_client, api)
    dlg._inputs["phone"].setText("0644444444")
    dlg._on_save()

    assert _local_client().phone == "0644444444"
    s = get_local_session()
    try:
        items = s.query(SyncQueueItem).filter_by(
            entity_id=CLIENT_ID, operation="UPDATE").all()
        assert len(items) == 1, "the change must be queued for PostgreSQL"
    finally:
        s.close()


def test_an_accepted_write_queues_nothing(qapp, request, seeded_client):
    from app.database import get_local_session
    from app.models.sync_queue import SyncQueueItem
    api = FakeApi()
    dlg = _edit(qapp, request, seeded_client, api)
    dlg._inputs["phone"].setText("0655555555")
    dlg._on_save()

    assert _local_client().phone == "0655555555"
    s = get_local_session()
    try:
        assert s.query(SyncQueueItem).filter_by(entity_id=CLIENT_ID).count() == 0
    finally:
        s.close()

def test_a_refused_delete_changes_nothing_and_queues_nothing(
    qapp, request, seeded_client, monkeypatch
):
    """A 403 must not be replayed forever — the client stays untouched."""
    from PySide6.QtWidgets import QMessageBox
    from app.database import get_local_session
    from app.models.sync_queue import SyncQueueItem
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    class ForbiddenApi(FakeApi):
        def delete_client(self, cid):
            self.deletes.append(cid)
            return {"http_error": 403}

    api = ForbiddenApi()
    dlg = _details(qapp, request, seeded_client, api)
    dlg._on_delete_client()

    row = _local_client()
    assert row is not None and row.status == "ACTIVE"
    s = get_local_session()
    try:
        assert s.query(SyncQueueItem).filter_by(
            entity_id=CLIENT_ID, operation="DELETE").count() == 0
    finally:
        s.close()


def test_an_unreachable_server_queues_the_delete(
    qapp, request, seeded_client, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox
    from app.database import get_local_session
    from app.models.sync_queue import SyncQueueItem
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    class OfflineApi(FakeApi):
        def delete_client(self, cid):
            return {"http_error": "NETWORK"}

    api = OfflineApi()
    dlg = _details(qapp, request, seeded_client, api)
    dlg._on_delete_client()

    assert _local_client() is None, "no reservations -> physical delete locally"
    s = get_local_session()
    try:
        assert s.query(SyncQueueItem).filter_by(
            entity_id=CLIENT_ID, operation="DELETE").count() == 1
    finally:
        s.close()

def test_a_queued_change_carries_the_real_device_and_user_identity(
    qapp, request, seeded_client
):
    """The ApiClient does not hold this identity — MainWindow does. A queued
    item stamped 'desktop'/'' would mis-attribute the push and the audit log."""
    from app.database import get_local_session
    from app.models.sync_queue import SyncQueueItem

    class OfflineApi(FakeApi):
        def update_client(self, cid, data):
            return None

    dlg = _edit(qapp, request, seeded_client, OfflineApi())
    dlg._inputs["phone"].setText("0666666666")
    dlg._on_save()

    s = get_local_session()
    try:
        item = s.query(SyncQueueItem).filter_by(entity_id=CLIENT_ID).one()
        assert item.device_id == "dev-1"
        assert item.user_id == "usr-1"
    finally:
        s.close()

def test_an_offline_document_add_registers_a_pending_upload(
    qapp, request, seeded_client, tmp_path
):
    """Offline, the file is stored as a `pending_uploads/...` marker. Without a
    registered pending upload the marker would reach PostgreSQL and the
    document would never actually exist server-side."""
    from app.database import get_local_session
    from app.models.pending_upload import LocalPendingUpload

    class OfflineApi(FakeApi):
        def upload_client_image(self, path):
            return None          # cannot upload right now

        def update_client(self, cid, data):
            return None          # unreachable

    local = tmp_path / "contrat_signe.pdf"
    local.write_bytes(b"%PDF-1.4 data")
    dlg = _edit(qapp, request, seeded_client, OfflineApi())
    dlg._doc_intent["contract_image"] = ("SET", str(local))
    dlg._on_save()

    stored = _local_client().contract_image
    assert stored.startswith("pending_uploads/")

    s = get_local_session()
    try:
        pending = s.query(LocalPendingUpload).filter_by(marker=stored).all()
        assert len(pending) == 1, "the marker must be registered for upload"
        assert pending[0].entity_type == "client"
        assert pending[0].field_name == "contract_image"
    finally:
        s.close()


def test_the_upload_processor_resolves_every_client_document_column(
    qapp, request, seeded_client
):
    """Including `contract_image` — a column the processor did not know about."""
    from app.database import get_local_session
    from app.models.client import LocalClient
    from app.sync.uploads import replace_marker_in_entities

    marker = "pending_uploads/deadbeef.pdf"
    s = get_local_session()
    row = s.query(LocalClient).filter_by(id=CLIENT_ID).one()
    row.contract_image = marker
    s.commit()

    replace_marker_in_entities(s, marker, "/static/uploads/clients/real.pdf")
    s.close()

    assert _local_client().contract_image == "/static/uploads/clients/real.pdf"
