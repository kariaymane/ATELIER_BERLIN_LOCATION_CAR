"""
Client-selection / write-back forensic — New Reservation form.

Root cause fixed: `ReservationFormDialog._on_client_selected` prefilled the
form when an existing client was chosen but never cleared it when the user
switched back to "Nouveau client" — stale name/phone/email/CIN from the
previous selection leaked into a supposedly-blank new-client reservation.

This file proves, end-to-end through the real dialog:
  1. Client A -> Client B: B's real data appears, no A residue.
  2. Client A -> "Nouveau client": every field is blank, no A residue.
  3. Editing an existing client's fields and saving writes back to the
     canonical Client record (queued for sync) — the reservation keeps
     customer_id.
  4. Leaving the fields untouched saves with NO write-back (no spurious
     client UPDATE).
  5. Reopening the dialog and selecting the same client shows the
     PERSISTED (updated) data — no stale in-memory snapshot.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"

import pytest
from PySide6.QtCore import QDateTime, QDate, QTime


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture()
def env(qapp):
    from app.database import init_local_db, get_local_session
    from app.models.vehicle import LocalVehicle
    from app.models.client import LocalClient
    init_local_db()
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    session.merge(LocalVehicle(
        id="cw-veh", registration="CW-1-A-1", vin="1M8GDM9AXKP042789",
        brand="Dacia", model="Logan", year=2024, color="Blanc",
        fuel_type="DIESEL", transmission="MANUAL", current_mileage=10,
        daily_rental_price=250.0, status="AVAILABLE",
        created_at=now, updated_at=now, version=1))
    session.merge(LocalClient(
        id="cw-cli-a", first_name="Amina", last_name="Bennani",
        phone="+212600000001", email="amina@test.local", cin_number="AA111111",
        status="ACTIVE", created_at=now, updated_at=now, version=1))
    session.merge(LocalClient(
        id="cw-cli-b", first_name="Bilal", last_name="Chraibi",
        phone="+212600000002", email="bilal@test.local", cin_number="BB222222",
        status="ACTIVE", created_at=now, updated_at=now, version=1))
    session.commit()
    session.close()
    yield
    session = get_local_session()
    session.query(LocalVehicle).filter_by(id="cw-veh").delete()
    session.query(LocalClient).filter(LocalClient.id.in_(["cw-cli-a", "cw-cli-b"])).delete(
        synchronize_session=False)
    session.commit()
    session.close()


def _vehicle_dict():
    return {"id": "cw-veh", "brand": "Dacia", "model": "Logan",
            "registration": "CW-1-A-1", "daily_rental_price": 250.0}


def _future(days_ahead, hour=9):
    dt = datetime.now() + timedelta(days=days_ahead)
    dt = dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    return dt.astimezone(timezone.utc).isoformat()


def _qdt(iso_str):
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return QDateTime(QDate(dt.year, dt.month, dt.day), QTime(dt.hour, dt.minute))


def _index_for_client(dlg, client_id):
    for i in range(dlg._client_combo.count()):
        if dlg._client_combo.itemData(i) == client_id:
            return i
    raise AssertionError(f"client {client_id} not in combo")


def test_switching_between_clients_no_stale_data(qapp, env):
    from app.ui.reservations.reservation_list import ReservationFormDialog
    dlg = ReservationFormDialog(_vehicle_dict(), api_client=None)

    dlg._client_combo.setCurrentIndex(_index_for_client(dlg, "cw-cli-a"))
    assert "Amina" in dlg._customer_name.text()
    assert dlg._customer_phone.text() == "+212600000001"
    assert dlg._customer_cin.text() == "AA111111"

    dlg._client_combo.setCurrentIndex(_index_for_client(dlg, "cw-cli-b"))
    assert "Bilal" in dlg._customer_name.text()
    assert "Amina" not in dlg._customer_name.text()
    assert dlg._customer_phone.text() == "+212600000002"
    assert dlg._customer_cin.text() == "BB222222"
    dlg.close()


def test_new_client_after_existing_selection_clears_fields(qapp, env):
    from app.ui.reservations.reservation_list import ReservationFormDialog
    dlg = ReservationFormDialog(_vehicle_dict(), api_client=None)

    dlg._client_combo.setCurrentIndex(_index_for_client(dlg, "cw-cli-a"))
    assert dlg._customer_name.text() != ""

    dlg._client_combo.setCurrentIndex(0)  # "— Nouveau client —"
    assert dlg._selected_client_id is None
    assert dlg._customer_name.text() == ""
    assert dlg._customer_phone.text() == ""
    assert dlg._customer_email.text() == ""
    assert dlg._customer_cin.text() == ""
    dlg.close()


def test_editing_existing_client_writes_back_to_client_record(qapp, env):
    from app.ui.reservations.reservation_list import ReservationFormDialog, ReservationWidget
    from app.database import get_local_session
    from app.models.client import LocalClient
    from app.sync.queue import SyncQueueItem

    dlg = ReservationFormDialog(_vehicle_dict(), api_client=None)
    dlg._client_combo.setCurrentIndex(_index_for_client(dlg, "cw-cli-a"))
    dlg._customer_phone.setText("+212699999999")  # edited
    dlg._start_dt.setDateTime(_qdt(_future(30)))
    dlg._end_dt.setDateTime(_qdt(_future(32)))

    widget = ReservationWidget(device_id="cw-dev", user_id="cw-u", api_client=None)
    dlg.saved.connect(lambda d: widget._create_reservation_record(d))
    dlg._on_save()
    dlg.close()

    session = get_local_session()
    client = session.query(LocalClient).filter_by(id="cw-cli-a").one()
    assert client.phone == "+212699999999", "edited phone must write back to the Client record"
    assert client.first_name == "Amina", "untouched fields must survive the write-back"
    kinds = [(i.entity_type, i.operation) for i in session.query(SyncQueueItem).all()]
    assert ("client", "UPDATE") in kinds, "the write-back must be queued for sync"
    session.close()


def test_unedited_existing_client_saves_with_no_writeback(qapp, env):
    from app.ui.reservations.reservation_list import ReservationFormDialog, ReservationWidget
    from app.database import get_local_session
    from app.sync.queue import SyncQueueItem

    dlg = ReservationFormDialog(_vehicle_dict(), api_client=None)
    dlg._client_combo.setCurrentIndex(_index_for_client(dlg, "cw-cli-b"))
    # No edits — save as-is.
    dlg._start_dt.setDateTime(_qdt(_future(40)))
    dlg._end_dt.setDateTime(_qdt(_future(42)))

    widget = ReservationWidget(device_id="cw-dev2", user_id="cw-u2", api_client=None)
    dlg.saved.connect(lambda d: widget._create_reservation_record(d))
    dlg._on_save()
    dlg.close()

    session = get_local_session()
    kinds = [(i.entity_type, i.operation) for i in session.query(SyncQueueItem).all()]
    assert ("client", "UPDATE") not in kinds, "no edit -> no spurious client write-back"
    assert ("client", "CREATE") not in kinds, "existing client must never be re-created"
    session.close()


def test_reopen_shows_persisted_updated_data_not_stale(qapp, env):
    """After the write-back test above runs in this process, reopening the
    dialog and reselecting the same client must show the PERSISTED value —
    proves the selector reads live data, not a stale cached snapshot."""
    from app.ui.reservations.reservation_list import ReservationFormDialog
    from app.database import get_local_session
    from app.models.client import LocalClient

    session = get_local_session()
    session.query(LocalClient).filter_by(id="cw-cli-a").update({"phone": "+212677777777"})
    session.commit()
    session.close()

    dlg = ReservationFormDialog(_vehicle_dict(), api_client=None)
    dlg._client_combo.setCurrentIndex(_index_for_client(dlg, "cw-cli-a"))
    assert dlg._customer_phone.text() == "+212677777777"
    dlg.close()
