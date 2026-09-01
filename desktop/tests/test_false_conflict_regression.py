import pytest
import os
from datetime import datetime, timezone, timedelta
from PySide6.QtCore import QDateTime, QTime
from PySide6.QtWidgets import QMessageBox, QApplication

from app.database import get_local_session
from app.models.reservation import LocalReservation
from app.ui.reservations.reservation_list import ReservationWidget
from app.services.api_client import ApiClient

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app

@pytest.fixture()
def env(qapp):
    from app.database import init_local_db
    init_local_db()

@pytest.fixture()
def widget(qapp, env):
    return ReservationWidget("device_id", "user_id", api_client=ApiClient("http://mock"))

def _future(days_ahead, hour=9):
    dt = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    return dt.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()

def test_A_date_picker_current_time_regression(qapp, env):
    from app.ui.reservations.reservation_list import ReservationFormDialog
    w = ReservationFormDialog({"id": "v1"})
    # When initialized, start_dt should be exactly 09:00 local
    start = w._start_dt.dateTime()
    assert start.time().hour() == 9
    assert start.time().minute() == 0
    assert start.time().second() == 0

def test_B_server_available(widget, monkeypatch):
    monkeypatch.setattr(widget._api, "check_availability", lambda v, s, e: {"available": True})
    monkeypatch.setattr(widget._api, "_access_token", "fake-token")
    
    warns = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warns.append(text))
    
    data = {"vehicle_id": "v1", "start_datetime": _future(1), "end_datetime": _future(3)}
    widget._create_reservation_record(data)
    assert len(warns) == 0

def test_C_server_blocked(widget, monkeypatch):
    monkeypatch.setattr(widget._api, "check_availability", lambda v, s, e: {"available": False})
    monkeypatch.setattr(widget._api, "_access_token", "fake-token")
    
    warns = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warns.append(text))
    
    data = {"vehicle_id": "v1", "start_datetime": _future(1), "end_datetime": _future(3)}
    widget._create_reservation_record(data)
    assert len(warns) == 1
    assert "Ce véhicule est déjà réservé" in warns[0]

def test_D_api_timeout(widget, monkeypatch):
    monkeypatch.setattr(widget._api, "check_availability", lambda v, s, e: None)
    monkeypatch.setattr(widget._api, "_access_token", "fake-token")
    
    warns = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warns.append(text))
    
    data = {"vehicle_id": "v1", "start_datetime": _future(1), "end_datetime": _future(3)}
    widget._create_reservation_record(data)
    assert len(warns) == 1
    assert "Serveur injoignable" in warns[0]

def test_E_api_http_500(widget, monkeypatch):
    monkeypatch.setattr(widget._api, "check_availability", lambda v, s, e: {"http_error": 500})
    monkeypatch.setattr(widget._api, "_access_token", "fake-token")

    warns = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warns.append(text))

    data = {"vehicle_id": "v1", "start_datetime": _future(1), "end_datetime": _future(3)}
    widget._create_reservation_record(data)
    assert len(warns) == 1
    # 5xx is its own category — a server error, never a conflict, never a silent create.
    from app.i18n import t
    assert t("reservations.err_server_error") in warns[0]
    assert t("reservations.double_booking") not in warns[0]

def test_F_stale_sqlite_reservation_with_server_available(widget, monkeypatch):
    # Server says available!
    monkeypatch.setattr(widget._api, "check_availability", lambda v, s, e: {"available": True})
    monkeypatch.setattr(widget._api, "_access_token", "fake-token")
    
    # But local cache has a stale reservation that overlaps!
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    session.add(LocalReservation(
        id="stale", vehicle_id="v1", start_datetime=_future(1), end_datetime=_future(3),
        status="RESERVED", version=1, daily_price=10.0, num_days=2, total_price=20.0, created_at=now, updated_at=now
    ))
    session.commit()
    
    warns = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warns.append(text))
    
    data = {"vehicle_id": "v1", "start_datetime": _future(1), "end_datetime": _future(3)}
    widget._create_reservation_record(data)
    # Stale cache MUST NOT override authoritative server!
    assert len(warns) == 0

def test_G_boundary(widget, monkeypatch):
    widget._api = None
    
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    session.add(LocalReservation(
        id="r1", vehicle_id="v1", start_datetime=_future(1, hour=10), end_datetime=_future(1, hour=12),
        status="RESERVED", version=1, daily_price=10.0, num_days=2, total_price=20.0, created_at=now, updated_at=now
    ))
    session.commit()
    
    warns = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warns.append(text))
    
    data = {"vehicle_id": "v1", "start_datetime": _future(1, hour=12), "end_datetime": _future(1, hour=14)}
    widget._create_reservation_record(data)
    assert len(warns) == 0

def test_H_real_overlap(widget, monkeypatch):
    widget._api = None
    
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    session.add(LocalReservation(
        id="r1", vehicle_id="v1", start_datetime=_future(1, hour=10), end_datetime=_future(1, hour=12),
        status="RESERVED", version=1, daily_price=10.0, num_days=2, total_price=20.0, created_at=now, updated_at=now
    ))
    session.commit()
    
    warns = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warns.append(text))
    
    data = {"vehicle_id": "v1", "start_datetime": _future(1, hour=11), "end_datetime": _future(1, hour=14)}
    widget._create_reservation_record(data)
    assert len(warns) == 1

def test_I_future_reservation(widget, monkeypatch):
    widget._api = None
    
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    session.add(LocalReservation(
        id="r1", vehicle_id="v1", start_datetime=_future(10), end_datetime=_future(15),
        status="RESERVED", version=1, daily_price=10.0, num_days=2, total_price=20.0, created_at=now, updated_at=now
    ))
    session.commit()
    
    warns = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warns.append(text))
    
    data = {"vehicle_id": "v1", "start_datetime": _future(1), "end_datetime": _future(5)}
    widget._create_reservation_record(data)
    assert len(warns) == 0

def test_J_expired_reservation(widget, monkeypatch):
    widget._api = None
    
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    session.add(LocalReservation(
        id="r1", vehicle_id="v1", start_datetime=_future(-5), end_datetime=_future(-1),
        status="RESERVED", version=1, daily_price=10.0, num_days=2, total_price=20.0, created_at=now, updated_at=now
    ))
    session.commit()
    
    warns = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warns.append(text))
    
    data = {"vehicle_id": "v1", "start_datetime": _future(1), "end_datetime": _future(5)}
    widget._create_reservation_record(data)
    assert len(warns) == 0
