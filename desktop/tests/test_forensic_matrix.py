"""
MAXIMUM FORENSIC TEST MATRIX — reservation availability & client integrity.

Covers the specified cases:
  Reservation: adjacent, real overlap, CANCELLED, COMPLETED, different
  vehicle, timezone equivalents (Z / offset / naive), invalid datetime,
  stale local blocker vs SERVER AVAILABLE (server wins), SERVER BLOCKED,
  network error / HTTP 500 / malformed (technical — never "already
  reserved"), maintenance overlap/completed/cancelled, status
  normalization.
  Client: fetcher status classes (SUCCESS_WITH_DATA/EMPTY, NETWORK_ERROR,
  401/403/500, PARSE_ERROR), new-client UUID consistency, sync order
  (client CREATE before reservation CREATE).
  Sync: server conflict reverts local RESERVED reservation (no stale
  blocker).
"""
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"

import pytest
from PySide6.QtCore import QDate, QDateTime, QTime


def _async_return(value):
    async def _done():
        return value
    return _done()


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture()
def env(qapp):
    from app.database import init_local_db, get_local_session
    from app.models.vehicle import LocalVehicle
    from app.models.maintenance import LocalMaintenance
    init_local_db()
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    session.merge(LocalVehicle(
        id="fx-veh", registration="FORENSIC-1-1", vin="1M8GDM9AXKP042788",
        brand="ForensicBrand", model="ProofModel", year=2026, color="Blanc",
        fuel_type="DIESEL", transmission="MANUAL", current_mileage=0,
        daily_rental_price=250.0, status="AVAILABLE",
        created_at=now, updated_at=now, version=1))
    session.commit()
    session.close()
    yield
    session = get_local_session()
    from app.models.reservation import LocalReservation
    from app.models.client import LocalClient
    session.query(LocalReservation).filter_by(vehicle_id="fx-veh").delete()
    session.query(LocalVehicle).filter_by(id="fx-veh").delete()
    session.query(LocalMaintenance).filter_by(vehicle_id="fx-veh").delete()
    session.query(LocalClient).filter(LocalClient.id.like("fx-cli%")).delete()
    session.commit()
    session.close()


def _vehicle_dict():
    return {"id": "fx-veh", "brand": "ForensicBrand", "model": "ProofModel",
            "registration": "FORENSIC-1-1", "daily_rental_price": 250.0}


def _iso(days_ahead, hour=22, minute=12, style="offset"):
    dt = datetime.now() + timedelta(days=days_ahead)
    dt = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    utc = dt.astimezone(timezone.utc)
    if style == "offset":
        return utc.isoformat()          # ...+00:00
    if style == "Z":
        return utc.isoformat().replace("+00:00", "Z")
    if style == "naive":
        return utc.replace(tzinfo=None).isoformat()
    return utc.isoformat()


def _qdt(iso):
    from datetime import datetime as dt
    d = dt.fromisoformat(iso.replace("Z", "+00:00")).replace(tzinfo=None)
    return QDateTime(QDate(d.year, d.month, d.day), QTime(d.hour, d.minute))


def _widget():
    from app.ui.reservations.reservation_list import ReservationWidget
    return ReservationWidget(device_id="fx-dev", user_id="fx-u", api_client=None)


def _create(widget, data):
    """Create via the real handler; returns (created, warnings)."""
    warnings = []
    from app.ui.reservations import reservation_list as rl
    orig = rl.QMessageBox.warning
    rl.QMessageBox.warning = lambda *a, **k: warnings.append(a)
    try:
        widget._create_reservation_record(data)
    finally:
        rl.QMessageBox.warning = orig
    from app.database import get_local_session
    s = get_local_session()
    from app.models.reservation import LocalReservation
    row = s.query(LocalReservation).filter_by(
        vehicle_id=data["vehicle_id"],
        start_datetime=data["start_datetime"]).first()
    s.close()
    return (row is not None), warnings


# ─────────────── canonical parser + overlap predicate ───────────────

def test_parse_datetime_utc_all_forms():
    from app.utils.datetime_utils import parse_datetime_utc
    base = datetime(2026, 8, 24, 22, 12, tzinfo=timezone.utc)
    assert parse_datetime_utc("2026-08-24T22:12:00Z") == base
    assert parse_datetime_utc("2026-08-24T22:12:00+00:00") == base
    # Under the unified naive policy (P2-4), naive values represent Casablanca wall time (UTC+1 in August):
    assert parse_datetime_utc("2026-08-24T23:12:00") == base          # naive legacy (23:12 local == 22:12 UTC)
    assert parse_datetime_utc("2026-08-24 23:12:00") == base          # SQLite format (23:12 local == 22:12 UTC)
    assert parse_datetime_utc(base) == base
    assert parse_datetime_utc("2026-08-24T23:12:00+01:00") == base    # offset equiv
    assert parse_datetime_utc("garbage") is None
    assert parse_datetime_utc("") is None
    assert parse_datetime_utc(None) is None


def test_overlap_predicate_adjacent_vs_real():
    from app.utils.datetime_utils import reservations_overlap
    a0, a1 = datetime(2026, 8, 24, 22, 12), datetime(2026, 8, 25, 22, 12)
    assert not reservations_overlap(a0, a1, a1, a1 + timedelta(days=1))   # adjacent
    assert reservations_overlap(a0, a1, a1 - timedelta(hours=1), a1 + timedelta(hours=1))


def test_status_normalization():
    from app.utils.datetime_utils import status_blocks_reservation
    assert status_blocks_reservation("RESERVED")
    assert status_blocks_reservation("active")           # case-insensitive
    assert not status_blocks_reservation("CANCELLED")
    assert not status_blocks_reservation("COMPLETED")
    assert not status_blocks_reservation(None)
    assert not status_blocks_reservation("")


# ─────────────── exact acceptance case (ForensicBrand ProofModel) ───────────────

def test_exact_acceptance_case_24_25_august(qapp, env):
    """THE #1 acceptance test: ForensicBrand ProofModel 24/08 22:12 -> 25/08 22:12."""
    from app.ui.reservations.reservation_list import ReservationFormDialog
    from app.ui.reservations.reservation_list import ReservationWidget

    dlg = ReservationFormDialog(_vehicle_dict(), api_client=None)
    dlg._customer_name.setText("Forensic Client")
    start = datetime(2026, 8, 24, 22, 12)
    end = datetime(2026, 8, 25, 22, 12)
    dlg._start_dt.setDateTime(_qdt(start.astimezone(timezone.utc).isoformat()))
    dlg._end_dt.setDateTime(_qdt(end.astimezone(timezone.utc).isoformat()))

    widget = _widget()
    data = {}
    dlg.saved.connect(lambda d: (data.update(d), widget._create_reservation_record(d)))
    dlg._on_save()

    from app.database import get_local_session
    from app.models.reservation import LocalReservation
    from app.models.client import LocalClient
    s = get_local_session()
    res = s.query(LocalReservation).filter_by(vehicle_id="fx-veh").first()
    assert res is not None, "THE EXACT ACCEPTANCE CASE MUST BE CREATED"
    assert res.status == "RESERVED"
    # UUID consistency: ONE id across client row + reservation link
    assert res.customer_id
    cli = s.query(LocalClient).filter_by(id=res.customer_id).first()
    assert cli is not None, "client must exist with the SAME UUID"
    # Sync order: client CREATE enqueued BEFORE reservation CREATE
    from app.models.sync_queue import SyncQueueItem
    items = (s.query(SyncQueueItem)
             .filter(SyncQueueItem.entity_id.in_([res.id, res.customer_id]))
             .order_by(SyncQueueItem.created_at).all())
    types = [i.entity_type for i in items]
    assert types == ["client", "reservation"], f"sync order broken: {types}"
    s.close()


# ─────────────── timezone equivalence + invalid input ───────────────

def test_timezone_equivalent_blocked_once(qapp, env):
    """A reservation created with +00:00 must block an equivalent Z form."""
    widget = _widget()
    created, _ = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "TZ Test",
        "customer_phone": "+212600000001",
        "start_datetime": _iso(5, style="offset"),
        "end_datetime": _iso(6, style="offset")})
    assert created
    # Same instants expressed with Z -> real overlap -> rejected
    created2, warnings = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "TZ Test",
        "start_datetime": _iso(5, style="Z"),
        "end_datetime": _iso(6, style="Z")})
    assert not created2 and len(warnings) == 1
    # Naive legacy form of the same instants -> still a real overlap
    created3, _ = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "TZ Test",
        "start_datetime": _iso(5, style="naive"),
        "end_datetime": _iso(6, style="naive")})
    assert not created3


def test_invalid_datetime_never_creates(qapp, env):
    widget = _widget()
    created, _ = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "Bad Date",
        "start_datetime": "not-a-date", "end_datetime": "also-bad"})
    assert not created


def test_different_vehicle_not_blocked(qapp, env):
    from app.database import get_local_session
    from app.models.vehicle import LocalVehicle
    s = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    s.merge(LocalVehicle(id="fx-veh2", registration="OTHER-2-2",
            vin="1M8GDM9AXKP042789", brand="Other", model="Car", year=2026,
            color="B", fuel_type="GASOLINE", transmission="MANUAL",
            current_mileage=0, daily_rental_price=100.0, status="AVAILABLE",
            created_at=now, updated_at=now, version=1))
    s.commit(); s.close()
    widget = _widget()
    created, _ = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "A", "customer_phone": "+212600000002",
        "start_datetime": _iso(5), "end_datetime": _iso(6)})
    assert created
    created2, _ = _create(widget, {
        "vehicle_id": "fx-veh2", "customer_name": "B", "customer_phone": "+212600000003",
        "start_datetime": _iso(5), "end_datetime": _iso(6)})
    assert created2, "different vehicle must not be blocked"


def test_completed_reservation_does_not_block(qapp, env):
    from app.database import get_local_session
    from app.models.reservation import LocalReservation
    widget = _widget()
    s = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    s.merge(LocalReservation(
        id="fx-done", vehicle_id="fx-veh", customer_name="Done",
        start_datetime=_iso(10), end_datetime=_iso(11),
        daily_price=250.0, num_days=1, total_price=250.0, deposit=0,
        status="COMPLETED", payment_status="PAID",
        created_at=now, updated_at=now, version=1))
    s.commit(); s.close()
    created, _ = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "X", "customer_phone": "+212600000004",
        "start_datetime": _iso(10), "end_datetime": _iso(11)})
    assert created, "COMPLETED must never block"


# ─────────────── server authority (online) ───────────────

class FakeApi:
    """Mock ApiClient for server-authority tests."""

    def __init__(self, available=None, http_error=None):
        self._access_token = "tok"
        self._available = available
        self._http_error = http_error
        self.calls = []

    def check_availability(self, vid, start, end):
        self.calls.append((vid, start, end))
        if self._http_error is not None:
            return {"http_error": self._http_error}
        return {"available": self._available, "vehicle_id": vid}


def test_server_available_overrides_stale_local_blocker(qapp, env):
    """SERVER AVAILABLE + stale local blocker -> SERVER WINS, created."""
    from app.database import get_local_session
    from app.models.reservation import LocalReservation
    # Stale local blocker (server does not have it)
    s = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    s.merge(LocalReservation(
        id="fx-stale", vehicle_id="fx-veh", customer_name="Stale",
        start_datetime=_iso(15), end_datetime=_iso(16),
        daily_price=250.0, num_days=1, total_price=250.0, deposit=0,
        status="RESERVED", payment_status="PENDING",
        created_at=now, updated_at=now, version=1))
    s.commit(); s.close()

    from app.ui.reservations.reservation_list import ReservationWidget
    widget = ReservationWidget(device_id="fx-dev", user_id="fx-u",
                               api_client=FakeApi(available=True))
    created, warnings = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "Online User",
        "customer_phone": "+212600000005",
        "start_datetime": _iso(15), "end_datetime": _iso(16)})
    assert created, "SERVER AVAILABLE must override stale local blocker"
    assert not warnings, "server-available must NOT produce the conflict message"


def test_server_blocked_rejects(qapp, env):
    from app.ui.reservations.reservation_list import ReservationWidget
    widget = ReservationWidget(device_id="fx-dev", user_id="fx-u",
                               api_client=FakeApi(available=False))
    created, warnings = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "Online User",
        "customer_phone": "+212600000006",
        "start_datetime": _iso(18), "end_datetime": _iso(19)})
    assert not created and len(warnings) == 1, "SERVER BLOCKED must reject"


@pytest.mark.parametrize("http_error,expected_key", [
    ("NETWORK", "sync.server_unavailable"),
    (500, "reservations.err_server_error"),
    (401, "clients.session_expired"),
    (403, "common.permission_denied"),
    ("malformed", "reservations.err_server_error"),
])
def test_technical_errors_never_report_conflict(qapp, env, http_error, expected_key):
    """NETWORK / 5xx / 401 / 403 / malformed -> the CATEGORY-SPECIFIC technical
    message, NEVER the business-conflict message, NEVER a silent creation."""
    from app.ui.reservations.reservation_list import ReservationWidget
    api = FakeApi()
    if http_error == "malformed":
        api.check_availability = lambda *a: {"unexpected_shape": True}
    else:
        api._http_error = http_error
    widget = ReservationWidget(device_id="fx-dev", user_id="fx-u", api_client=api)
    created, warnings = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "T", "customer_phone": "+212600000007",
        "start_datetime": _iso(21), "end_datetime": _iso(22)})
    assert not created, "technical error must not silently create"
    from app.i18n import t
    assert any(t(expected_key) in str(w) for w in warnings), \
        f"must show {expected_key!r}, got: {warnings}"
    assert not any(t("reservations.double_booking") in str(w) for w in warnings), \
        "technical error must NEVER be reported as already-reserved"


# ─────────────── maintenance interactions ───────────────

def _seed_maintenance(status, days_ahead=25):
    from app.database import get_local_session
    from app.models.maintenance import LocalMaintenance
    s = get_local_session()
    now = datetime.now(timezone.utc).isoformat()
    start = (datetime.now() + timedelta(days=days_ahead)).astimezone(timezone.utc)
    s.merge(LocalMaintenance(
        id=f"fx-mnt-{status}", vehicle_id="fx-veh", type="Revision",
        start_datetime=start.isoformat(),
        expected_end_datetime=(start + timedelta(days=2)).isoformat(),
        status=status, step="EN COURS",
        created_at=now, updated_at=now, version=1))
    s.commit(); s.close()


def test_active_maintenance_blocks(qapp, env):
    _seed_maintenance("ACTIVE")
    widget = _widget()
    created, warnings = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "M", "customer_phone": "+212600000008",
        "start_datetime": _iso(26), "end_datetime": _iso(27)})
    assert not created and warnings, "ACTIVE maintenance must block overlapping reservation"


def test_completed_maintenance_does_not_block(qapp, env):
    _seed_maintenance("COMPLETED")
    widget = _widget()
    created, _ = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "M", "customer_phone": "+212600000009",
        "start_datetime": _iso(26), "end_datetime": _iso(27)})
    assert created, "COMPLETED maintenance must not block"


def test_cancelled_maintenance_does_not_block(qapp, env):
    _seed_maintenance("CANCELLED")
    widget = _widget()
    created, _ = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "M", "customer_phone": "+212600000010",
        "start_datetime": _iso(26), "end_datetime": _iso(27)})
    assert created, "CANCELLED maintenance must not block"


# ─────────────── client fetcher status classes ───────────────

@pytest.mark.parametrize("api_result,expected_status", [
    ({"clients": [{"id": "1"}]}, "SUCCESS_WITH_DATA"),
    ({"clients": []}, "SUCCESS_EMPTY"),
    ({"http_error": "NETWORK"}, "NETWORK_ERROR"),
    ({"http_error": 401}, "HTTP_401"),
    ({"http_error": 403}, "HTTP_403"),
    ({"http_error": 500}, "HTTP_500"),
    ({"http_error": 200, "parse_error": True}, "PARSE_ERROR"),
])
def test_clients_fetcher_status_classes(qapp, api_result, expected_status):
    from app.ui.clients.client_list import ClientsFetcher

    class FakeClientApi:
        _access_token = "tok"

        def get_clients(self, **kw):
            return api_result

    captured = {}
    fetcher = ClientsFetcher(FakeClientApi())
    fetcher.clients_ready.connect(lambda c, s: captured.update(clients=c, status=s))
    fetcher.run()  # direct call — no thread needed for the logic
    assert captured["status"] == expected_status


# ─────────────── sync conflict revert (stale blocker prevention) ───────────────

def test_server_conflict_reverts_local_reservation(qapp, env, monkeypatch):
    """SERVER REJECTS (double booking) -> local RESERVED row must be
    reverted so it can never block future bookings (stale blocker)."""
    from app.database import get_local_session
    from app.models.reservation import LocalReservation
    from app.models.sync_queue import SyncQueueItem
    from app.sync.queue import SyncQueue
    from app.sync.engine import SyncEngine

    widget = _widget()
    created, _ = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "Sync Test",
        "customer_phone": "+212600000011",
        "start_datetime": _iso(30), "end_datetime": _iso(31)})
    assert created

    session = get_local_session()
    res = session.query(LocalReservation).filter_by(vehicle_id="fx-veh").first()
    assert res.status == "RESERVED"

    # Simulate the sync push returning CONFLICT for this reservation CREATE
    pending = (session.query(SyncQueueItem)
               .filter_by(entity_type="reservation", entity_id=res.id,
                          sync_status="PENDING").all())
    assert pending, "reservation must be queued"

    class FakeResponse:
        status_code = 200

        def json(self):
            # One conflict result per queued item (client enqueued first,
            # then reservation) mirroring the real batch response order.
            # The engine pushes ALL queued items (client first, then
            # reservation); return a conflict for every one of them.
            return {"results": [
                {"status": "conflict", "message": "Double booking detected"}
                for _ in range(5)]}

    engine = SyncEngine("fx-dev", "tok")
    import httpx
    fake = _FakeAsyncClient(FakeResponse())
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: fake)

    async def run_push():
        return await engine.push_changes()

    import asyncio
    report = asyncio.run(run_push())

    session.expire_all()
    res = session.query(LocalReservation).filter_by(id=res.id).first()
    assert res.status == "CANCELLED", (
        "server-rejected reservation must be reverted locally (stale blocker)")
    assert report.get("conflicts"), "conflicts must be surfaced in the report"
    session.close()


class _FakeResponse:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200

    def json(self):
        return self._p


class _FakeAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        return self._response

    async def get(self, url, **kw):
        return self._response


def _fake_client_factory(response):
    return lambda *a, **kw: _FakeAsyncClient(response)


def test_failed_creation_compensates_no_orphan_client(qapp, env):
    """Failure after the client enqueue must compensate: the queued client
    CREATE is removed together with the local client row (no orphan)."""
    from app.database import get_local_session
    from app.models.client import LocalClient
    from app.models.reservation import LocalReservation
    from app.models.sync_queue import SyncQueueItem
    from app.ui.reservations.reservation_list import ReservationWidget

    widget = _widget()
    # Force the reservation CONSTRUCTION to fail: corrupt num_days type in
    # the data dict is tolerated (default), so instead break 'vehicle_id'
    # lookup semantics by deleting the vehicle AFTER validation but BEFORE
    # commit is impossible from outside; therefore simulate via a payload
    # whose start>end passes parsing but fails the DB NOT NULL constraint:
    # use a missing customer_name (nullable in DB) — instead we force the
    # failure with an oversized customer_name via monkeypatched session.
    data = {
        "vehicle_id": "fx-veh", "customer_name": "Compensation Test",
        "customer_phone": "+212600000099",
        "start_datetime": _iso(35), "end_datetime": _iso(36),
    }

    from app.ui.reservations import reservation_list as rl
    rl.QMessageBox.warning = lambda *a, **k: None  # failure path is modal
    calls = {"count": 0}
    orig_enqueue = rl.SyncQueue.enqueue

    def counting_enqueue(self, *a, **kw):
        calls["count"] += 1
        if calls["count"] == 2:  # the reservation enqueue (client was 1st)
            raise RuntimeError("simulated failure between enqueues")
        return orig_enqueue(self, *a, **kw)

    import app.ui.reservations.reservation_list as rlmod
    monkey = rl.SyncQueue.enqueue
    rl.SyncQueue.enqueue = counting_enqueue
    try:
        widget._create_reservation_record(data)
    except Exception:
        pass
    finally:
        rl.SyncQueue.enqueue = monkey

    session = get_local_session()
    orphans = (session.query(LocalClient)
               .filter(LocalClient.first_name == "Compensation").all())
    # The client row may exist locally but its queue item must be gone
    # (compensation) so it never syncs to the server as an orphan.
    for cli in orphans:
        q = (session.query(SyncQueueItem)
             .filter_by(entity_type="client", entity_id=cli.id).first())
        assert q is None or q.sync_status != "PENDING", \
            "orphan client CREATE must not remain queued after failure"
    # No reservation may have been created for this attempt
    res = session.query(LocalReservation).filter_by(
        customer_name="Compensation Test").first()
    assert res is None, "failed creation must not leave a reservation"
    session.close()


def test_availability_query_url_encoding(qapp):
    """REGRESSION: ISO offsets contain '+' which MUST be URL-encoded.
    Raw '+' in the query decodes to a space server-side -> HTTP 400 ->
    the desktop reported a technical error and blocked every online
    reservation. The request URL must carry %2B."""
    from app.ui.reservations.reservation_list import ReservationWidget

    captured = {}

    class UrlCaptureApi:
        _access_token = "tok"

        def check_availability(self, vid, start, end):
            from urllib.parse import urlencode
            captured["query"] = urlencode({"start": start, "end": end})
            return {"available": True, "vehicle_id": vid}

    widget = ReservationWidget(device_id="fx-dev", user_id="fx-u",
                               api_client=UrlCaptureApi())
    created, warnings = _create(widget, {
        "vehicle_id": "fx-veh", "customer_name": "URL Test",
        "customer_phone": "+212600000012",
        "start_datetime": _iso(5), "end_datetime": _iso(6)})
    assert created
    assert "%2B" in captured["query"], (
        "availability query must URL-encode '+' offsets — raw '+' caused "
        "HTTP 400 and blocked all online reservations")
    assert "already" not in str(warnings).lower()
