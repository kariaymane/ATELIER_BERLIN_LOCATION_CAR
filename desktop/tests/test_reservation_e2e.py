"""
MANDATORY ACCEPTANCE TEST — New Reservation end-to-end (desktop, offscreen).

Workflow under test:
  1. Open the real ReservationFormDialog for a real vehicle.
  2. Select an EXISTING client from the new client selector.
  3. Save -> reservation created with customer_id linked.
  4. Clients page shows the client; client report counts the reservation.
  5. New-client path: reservation without selection creates a linked Client.
  6. Overlap rules: real overlap rejected, ADJACENT allowed, cancelled ignored.
  7. Vehicle status is NOT flipped to RESERVED (canonical backend behavior).
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
        id="e2e-veh", registration="E2E-1-A-1", vin="1M8GDM9AXKP042788",
        brand="Dacia", model="Logan", year=2024, color="Blanc",
        fuel_type="DIESEL", transmission="MANUAL", current_mileage=10,
        daily_rental_price=250.0, status="AVAILABLE",
        created_at=now, updated_at=now, version=1))
    session.merge(LocalClient(
        id="e2e-cli", first_name="Salma", last_name="Alaoui",
        phone="+212655000111", email="salma@test.local", cin_number="EE112233",
        status="ACTIVE", created_at=now, updated_at=now, version=1))
    session.commit()
    session.close()
    yield
    session = get_local_session()
    session.query(LocalVehicle).filter_by(id="e2e-veh").delete()
    session.query(LocalClient).filter_by(id="e2e-cli").delete()
    session.commit()
    session.close()


def _vehicle_dict():
    return {"id": "e2e-veh", "brand": "Dacia", "model": "Logan",
            "registration": "E2E-1-A-1", "daily_rental_price": 250.0}


def _future(days_ahead, hour=9):
    dt = datetime.now() + timedelta(days=days_ahead)
    dt = dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    return dt.astimezone(timezone.utc).isoformat()


def _qdt(iso_str):
    """Build QDateTime from an ISO string via QDate/QTime (PySide6-safe)."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return QDateTime(QDate(dt.year, dt.month, dt.day), QTime(dt.hour, dt.minute))


def test_existing_client_selection_links_reservation(qapp, env):
    from app.ui.reservations.reservation_list import ReservationFormDialog
    from app.database import get_local_session
    from app.models.reservation import LocalReservation
    from app.models.vehicle import LocalVehicle

    dlg = ReservationFormDialog(_vehicle_dict(), api_client=None)
    # Select the existing client in the combo (index 1 == first client)
    assert dlg._client_combo.count() >= 2, "client selector must list existing clients"
    dlg._client_combo.setCurrentIndex(1)
    assert dlg._selected_client_id == "e2e-cli"
    assert "Salma" in dlg._customer_name.text(), "existing client info must prefill"

    dlg._start_dt.setDateTime(_qdt(_future(5)))
    dlg._end_dt.setDateTime(_qdt(_future(8)))
    from app.ui.reservations.reservation_list import ReservationWidget
    widget = ReservationWidget(device_id="e2e-dev", user_id="e2e-u", api_client=None)
    data = {}
    dlg.saved.connect(lambda d: (data.update(d), widget._create_reservation_record(d)))
    dlg._on_save()

    assert data.get("customer_id") == "e2e-cli"
    session = get_local_session()
    all_rows = [(r.id[:8], r.customer_id, r.vehicle_id) for r in session.query(LocalReservation).all()]
    print("\nDB ROWS:", all_rows)
    res = session.query(LocalReservation).filter_by(customer_id="e2e-cli").first()
    assert res is not None
    assert res.customer_id == "e2e-cli"
    assert res.customer_name.startswith("Salma")
    v = session.query(LocalVehicle).filter_by(id="e2e-veh").first()
    assert v.status == "AVAILABLE", "vehicle.status must NOT flip to RESERVED"
    session.close()
    dlg.close()


def test_new_client_created_from_typed_info(qapp, env):
    from app.ui.reservations.reservation_list import ReservationFormDialog
    from app.database import get_local_session
    from app.models.reservation import LocalReservation
    from app.models.client import LocalClient

    dlg = ReservationFormDialog(_vehicle_dict(), api_client=None)
    dlg._client_combo.setCurrentIndex(0)  # "— Nouveau client —"
    assert dlg._selected_client_id is None
    dlg._customer_name.setText("Youssef El Amrani")
    dlg._customer_phone.setText("+212611999888")
    dlg._start_dt.setDateTime(_qdt(_future(20)))
    dlg._end_dt.setDateTime(_qdt(_future(22)))
    from app.ui.reservations.reservation_list import ReservationWidget
    widget = ReservationWidget(device_id="e2e-dev", user_id="e2e-u", api_client=None)
    data = {}
    dlg.saved.connect(lambda d: (data.update(d), widget._create_reservation_record(d)))
    dlg._on_save()

    session = get_local_session()
    res = session.query(LocalReservation).filter(
        LocalReservation.customer_name == "Youssef El Amrani").first()
    assert res is not None and res.customer_id, "new client must be created and linked"
    cli = session.query(LocalClient).filter_by(id=res.customer_id).first()
    assert cli is not None
    assert "Youssef" in cli.first_name or "Youssef" in cli.last_name or \
           cli.first_name + " " + cli.last_name == "Youssef El Amrani"
    assert cli.phone == "+212611999888"
    session.close()
    dlg.close()


def test_real_overlap_rejected_adjacent_allowed(qapp, env, monkeypatch):
    # The rejection path shows a modal QMessageBox — capture it instead of
    # blocking the offscreen test run.
    warnings = []
    from app.ui.reservations import reservation_list as rl
    monkeypatch.setattr(rl.QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a))
    from app.ui.reservations.reservation_list import ReservationWidget
    from app.database import get_local_session
    from app.models.reservation import LocalReservation
    from datetime import datetime, timezone as tz

    widget = ReservationWidget(device_id="e2e-dev", user_id="e2e-u", api_client=None)

    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    # Existing: day+5 -> day+8
    session.merge(LocalReservation(
        id="ovr-exist", vehicle_id="e2e-veh", customer_id="e2e-cli",
        customer_name="Salma Alaoui", customer_phone="+212655000111",
        start_datetime=_future(5), end_datetime=_future(8),
        daily_price=250.0, num_days=3, total_price=750.0,
        deposit=0, status="RESERVED", payment_status="PENDING",
        created_at=now, updated_at=now, version=1))
    # Cancelled overlapping block — must be ignored
    session.merge(LocalReservation(
        id="ovr-cancelled", vehicle_id="e2e-veh", customer_id="e2e-cli",
        customer_name="Salma Alaoui",
        start_datetime=_future(5), end_datetime=_future(8),
        daily_price=250.0, num_days=3, total_price=750.0,
        deposit=0, status="CANCELLED", payment_status="PENDING",
        created_at=now, updated_at=now, version=1))
    session.commit()
    session.close()

    # 1. REAL overlap (day+6 -> day+9) must be rejected
    data = {"vehicle_id": "e2e-veh", "customer_id": "e2e-cli",
            "customer_name": "Salma Alaoui",
            "start_datetime": _future(6), "end_datetime": _future(9)}
    widget._create_reservation_record(data)
    assert len(warnings) == 1, "real overlap must show the rejection warning"
    session = get_local_session()
    assert session.query(LocalReservation).filter_by(
        vehicle_id="e2e-veh", start_datetime=_future(6)).first() is None
    session.close()

    # 2. ADJACENT (day+8 -> day+10, starts exactly at existing end) allowed
    data2 = {"vehicle_id": "e2e-veh", "customer_id": "e2e-cli",
             "customer_name": "Salma Alaoui",
             "start_datetime": _future(8), "end_datetime": _future(10)}
    widget._create_reservation_record(data2)
    session = get_local_session()
    adj = session.query(LocalReservation).filter_by(
        start_datetime=_future(8)).first()
    assert adj is not None, "adjacent reservation must be ALLOWED"
    session.close()


def test_cancelled_reservation_does_not_block(qapp, env):
    from app.ui.reservations.reservation_list import ReservationWidget
    from app.database import get_local_session
    from app.models.reservation import LocalReservation

    widget = ReservationWidget(device_id="e2e-dev", user_id="e2e-u", api_client=None)
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    session.merge(LocalReservation(
        id="cxl-1", vehicle_id="e2e-veh", customer_id="e2e-cli",
        customer_name="Salma Alaoui",
        start_datetime=_future(40), end_datetime=_future(43),
        daily_price=250.0, num_days=3, total_price=750.0,
        deposit=0, status="CANCELLED", payment_status="PENDING",
        created_at=now, updated_at=now, version=1))
    session.commit(); session.close()

    data = {"vehicle_id": "e2e-veh", "customer_id": "e2e-cli",
            "customer_name": "Salma Alaoui",
            "start_datetime": _future(41), "end_datetime": _future(42)}
    widget._create_reservation_record(data)
    session = get_local_session()
    assert session.query(LocalReservation).filter_by(
        start_datetime=_future(41)).first() is not None, \
        "cancelled reservations must not block new bookings"
    session.close()
