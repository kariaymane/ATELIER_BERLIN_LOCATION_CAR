"""BUG 1 — reservation creation wrongly showed "Serveur injoignable".

Root cause: the fly.dev backend cold-starts; the first availability check
timed out (10 s) and `_request` returned None → the UI showed the generic
"server unreachable" message and blocked creation. Additionally every
non-200 (401/403/409/422/5xx) was collapsed into the same message.

Fixes verified here:
  1. ApiClient retries a read-timeout with a widened timeout.
  2. The reservation UI reports the PRECISE category and never shows a
     business error as a transport error (or vice-versa).
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from PySide6.QtWidgets import QApplication, QMessageBox

from app.database import init_local_db, get_local_session
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.ui.reservations.reservation_list import ReservationWidget
from app.i18n import t


@pytest.fixture(autouse=True)
def clean_db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _future(days, hour=9):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0).isoformat()


class _Api:
    def __init__(self, result):
        self._result = result
        self._access_token = "tok"
        self.calls = 0

    def check_availability(self, vid, s, e):
        self.calls += 1
        return self._result() if callable(self._result) else self._result


def _seed_vehicle(vid="v1"):
    s = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    s.merge(LocalVehicle(id=vid, registration="B1", vin="VINB1", brand="T", model="C",
                         year=2024, color="N", fuel_type="D", transmission="A",
                         status="AVAILABLE", created_at=now, updated_at=now, version=1))
    s.commit(); s.close()


def _run(qapp, api, monkeypatch, vid="v1"):
    _seed_vehicle(vid)
    w = ReservationWidget(device_id="d", user_id="u", api_client=api)
    warns = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: warns.append(a[-1])))
    w._create_reservation_record({
        "vehicle_id": vid, "customer_name": "X", "customer_phone": "+212600000001",
        "start_datetime": _future(2), "end_datetime": _future(4),
    })
    s = get_local_session()
    n = s.query(LocalReservation).count()
    s.close()
    return warns, n


@pytest.mark.parametrize("resp,expect_key,expect_created", [
    ({"available": True},                 None,                              True),
    ({"available": False, "reason": "RESERVATION"}, "reservations.double_booking", False),
    ({"available": False, "reason": "MAINTENANCE"}, "reservations.in_maintenance", False),
    ({"http_error": 409},                 "reservations.double_booking",      False),
    ({"http_error": 401},                 "clients.session_expired",          False),
    ({"http_error": 403},                 "common.permission_denied",         False),
    ({"http_error": 422},                 "reservations.err_invalid_data",    False),
    ({"http_error": 400},                 "reservations.err_invalid_data",    False),
    ({"http_error": 500},                 "reservations.err_server_error",    False),
    ({"http_error": "timeout", "transport": True}, "sync.server_unavailable", False),
    (None,                                "sync.server_unavailable",          False),
])
def test_error_category_is_preserved(qapp, monkeypatch, resp, expect_key, expect_created):
    warns, n = _run(qapp, _Api(resp), monkeypatch)
    if expect_created:
        assert n == 1 and warns == []
    else:
        assert n == 0
        assert any(t(expect_key) in str(x) for x in warns), (expect_key, warns)
        assert not any(t("sync.server_unavailable") in str(x) for x in warns) or expect_key == "sync.server_unavailable"


def test_404_vehicle_not_synced_falls_back_to_local_and_creates(qapp, monkeypatch):
    # Vehicle exists locally but the server 404s it (created offline, not pushed).
    warns, n = _run(qapp, _Api({"http_error": 404}), monkeypatch)
    assert n == 1, "offline-created vehicle must still be reservable via local check"
    assert warns == []


def test_404_still_blocks_on_real_local_overlap(qapp, monkeypatch):
    _seed_vehicle("v1")
    s = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    s.add(LocalReservation(id="r0", vehicle_id="v1", customer_name="Y",
                           start_datetime=_future(2), end_datetime=_future(4),
                           daily_price=1, num_days=2, total_price=2, deposit=0,
                           status="RESERVED", payment_status="PENDING",
                           created_at=now, updated_at=now, version=1))
    s.commit(); s.close()
    w = ReservationWidget(device_id="d", user_id="u", api_client=_Api({"http_error": 404}))
    warns = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: warns.append(a[-1])))
    w._create_reservation_record({
        "vehicle_id": "v1", "customer_name": "Z", "customer_phone": "+212600000002",
        "start_datetime": _future(2), "end_datetime": _future(4),
    })
    s = get_local_session(); n = s.query(LocalReservation).count(); s.close()
    assert n == 1  # only the pre-seeded one
    assert any(t("reservations.double_booking") in str(x) for x in warns)


def test_apiclient_retries_read_timeout(monkeypatch):
    """ApiClient._request retries a read timeout with a widened timeout,
    then succeeds — the cold-start case that produced BUG 1."""
    import httpx
    from app.services.api_client import ApiClient

    api = ApiClient("http://x", timeout=1.0)
    calls = {"n": 0}

    class _Resp:
        status_code = 200

        def json(self):
            return {"available": True}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ReadTimeout("cold start")
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    r = api._request("get", "/x", retries=2)
    assert r is not None and r.status_code == 200
    assert calls["n"] == 2, "must have retried once after the timeout"
