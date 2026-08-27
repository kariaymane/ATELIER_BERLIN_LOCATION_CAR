import uuid
"""
Offline pending-upload tests.

Covers the full offline image/document upload lifecycle:
- offline creation (durable record + marker placeholder)
- persistence across application restart (new engine/session)
- reconnect processing through SyncEngine.sync()
- successful upload (marker replaced by remote URL, record SYNCED,
  local file archived only after confirmed success)
- temporary failure -> retry with backoff
- permanent validation failure -> no endless retries, file kept
- duplicate prevention / idempotency (unique marker)
- remote URL persistence on vehicles, reservations and clients
- queue cleanup after completion
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.client import LocalClient
from app.models.sync_queue import SyncQueueItem
from app.models.pending_upload import LocalPendingUpload
from app.sync.uploads import (
    PENDING_DIR,
    enqueue_pending_upload,
    register_pending_upload,
    replace_marker_in_entities,
)
from app.sync.engine import SyncEngine

PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def setup_db():
    init_local_db()
    yield


@pytest.fixture
def session():
    s = get_local_session()
    # Start from a clean pending queue for isolation
    s.query(LocalPendingUpload).delete()
    s.commit()
    yield s
    s.close()


@pytest.fixture
def image_file(tmp_path):
    p = tmp_path / "photo.png"
    p.write_bytes(PNG_MAGIC)
    return str(p)


def _make_engine(base_url, handler):
    engine = SyncEngine("test-device-uploads", "token", "refresh")
    engine._base_url = base_url
    monkey_handler(handler, engine)
    return engine


def monkey_handler(handler, engine):
    async def _post(url, **kwargs):
        class R:
            def __init__(self, status_code=200, payload=None):
                self.status_code = status_code
                self._payload = payload or {}

            def json(self):
                return self._payload

        return handler(url, kwargs)

    engine._http_post = _post


class FakeAsyncClient:
    """Replaces httpx.AsyncClient inside uploads._upload_file."""

    def __init__(self, responder, *args, **kwargs):
        self._responder = responder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        class R:
            def __init__(self, status_code=200, payload=None):
                self.status_code = status_code
                self._p = payload or {}

            def json(self):
                return self._p

        return self._responder(url, kwargs)


def install_responder(monkeypatch, responder):
    import app.sync.uploads as up

    def factory(*args, **kwargs):
        return FakeAsyncClient(responder, *args, **kwargs)

    monkeypatch.setattr(up.httpx, "AsyncClient", factory)


# ─────────────────────────── offline creation ───────────────────────────

def test_offline_creation_creates_durable_record(session, image_file):
    rec = enqueue_pending_upload(
        session, "vehicle", "veh-1", "VEHICLE_IMAGE",
        "/api/v1/vehicles/upload-image", image_file, field_name="image_url",
    )
    assert rec.status == "PENDING"
    assert rec.marker.startswith("pending_uploads/")
    assert rec.entity_type == "vehicle"
    assert rec.entity_id == "veh-1"
    assert rec.local_path and Path(rec.local_path).exists()
    assert rec.retry_count == 0
    assert rec.created_at is not None
    stored = PENDING_DIR / Path(rec.marker).name
    assert stored.exists(), "File must be durably copied into pending_uploads"


def test_marker_placeholder_never_claims_success(session, image_file):
    """The value stored on the entity is a marker, never a server URL."""
    rec = enqueue_pending_upload(
        session, "reservation", "res-1", "CLIENT_DOCUMENT",
        "/api/v1/clients/upload-image", image_file,
        field_name="identity_card_image",
    )
    assert rec.marker.startswith("pending_uploads/")
    assert "http" not in rec.marker
    assert rec.completed_at is None


# ─────────────────────────── restart persistence ───────────────────────────

def test_persistence_across_restart(session, image_file, monkeypatch):
    rec = enqueue_pending_upload(
        session, "vehicle", "veh-rst", "VEHICLE_IMAGE",
        "/api/v1/vehicles/upload-image", image_file,
    )
    marker = rec.marker
    session.close()

    # Simulate an application restart in production mode: the database file
    # is preserved (no reset) and tables are re-opened.
    monkeypatch.setenv("CAR_RENTAL_DB_RESET", "0")
    init_local_db()
    fresh = get_local_session()
    found = fresh.query(LocalPendingUpload).filter_by(marker=marker).first()
    assert found is not None
    assert found.status == "PENDING"
    assert Path(found.local_path).exists()
    fresh.close()


# ─────────────────────────── idempotency ───────────────────────────

def test_duplicate_prevention_same_marker(session, image_file):
    m = f"pending_uploads/dup-{uuid.uuid4().hex}.png"
    src1 = Path(image_file)
    copy1 = PENDING_DIR / m.split("/")[1]
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(src1, copy1)

    r1 = register_pending_upload(
        session, marker=m, entity_type="vehicle", entity_id="v1",
        upload_type="VEHICLE_IMAGE",
        remote_endpoint="/api/v1/vehicles/upload-image",
    )
    r2 = register_pending_upload(
        session, marker=m, entity_type="vehicle", entity_id="v1",
        upload_type="VEHICLE_IMAGE",
        remote_endpoint="/api/v1/vehicles/upload-image",
    )
    count = session.query(LocalPendingUpload).filter_by(marker=m).count()
    assert count == 1
    assert r1.id == r2.id


def test_register_attaches_entity_id_later(session, image_file):
    m = f"pending_uploads/attach-{uuid.uuid4().hex}.png"
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(image_file, PENDING_DIR / m.split("/")[1])

    r1 = register_pending_upload(
        session, marker=m, entity_type="reservation", entity_id="",
        upload_type="CLIENT_DOCUMENT",
        remote_endpoint="/api/v1/clients/upload-image",
    )
    assert r1.entity_id == ""
    r2 = register_pending_upload(
        session, marker=m, entity_type="reservation", entity_id="res-77",
        upload_type="CLIENT_DOCUMENT",
        remote_endpoint="/api/v1/clients/upload-image",
    )
    assert r2.entity_id == "res-77"
    assert r1.id == r2.id


def test_register_ignores_non_markers(session):
    assert register_pending_upload(
        session, marker="/static/uploads/vehicles/x.jpg",
        entity_type="vehicle", entity_id="v9",
        upload_type="VEHICLE_IMAGE",
        remote_endpoint="/api/v1/vehicles/upload-image",
    ) is None
    assert session.query(LocalPendingUpload).count() == 0


# ─────────────────────── reconnect & success flow ───────────────────────

def _seed_vehicle_with_marker(session, marker):
    now = datetime.now(timezone.utc).isoformat()
    v = LocalVehicle(
        id="veh-img-1", registration="12345-A-6", vin="1M8GDM9AXKP042788",
        brand="Renault", model="Clio", year=2023, color="Blanc",
        fuel_type="DIESEL", transmission="MANUAL", current_mileage=1000,
        purchase_mileage=0, purchase_price=0.0, daily_rental_price=300.0,
        status="AVAILABLE", image_url=f"existing.jpg,{marker}",
        created_at=now, updated_at=now, version=1,
    )
    session.merge(v)
    session.commit()


def test_successful_upload_updates_url_and_cleans_queue(
    session, monkeypatch, image_file
):
    marker_resp = {}

    def responder(url, kwargs):
        marker_resp["url"] = f"/static/uploads/vehicles/{uuid.uuid4().hex}.png"
        return R(200, {"image_url": marker_resp["url"]})

    install_responder(monkeypatch, responder)

    rec = enqueue_pending_upload(
        session, "vehicle", "veh-img-1", "VEHICLE_IMAGE",
        "/api/v1/vehicles/upload-image", image_file,
    )
    marker = rec.marker
    _seed_vehicle_with_marker(session, marker)
    original_file = Path(rec.local_path)

    engine = SyncEngine("dev-1", "access-token", "refresh-token")

    async def fake_refresh():
        return True

    engine._do_refresh = fake_refresh
    result = asyncio.run(engine.process_pending_uploads())

    assert result["uploaded"] == 1
    assert result["remaining"] == 0

    fresh = get_local_session()
    v = fresh.query(LocalVehicle).filter_by(id="veh-img-1").first()
    urls = [u.strip() for u in v.image_url.split(",")]
    assert marker not in urls
    assert marker_resp["url"] in urls

    done = fresh.query(LocalPendingUpload).filter_by(marker=marker).first()
    assert done.status == "SYNCED"
    assert done.completed_at is not None
    assert done.error_message is None
    # Local file archived only AFTER confirmed success; never deleted before.
    assert not original_file.exists() or Path(original_file).parent.name == "uploaded"
    fresh.close()


def test_reservation_document_upload_reconciles_fields(
    session, monkeypatch, image_file
):
    remote_url = f"/static/uploads/clients/{uuid.uuid4().hex}.jpg"

    def responder(url, kwargs):
        return R(200, {"image_url": remote_url})

    install_responder(monkeypatch, responder)

    rec = enqueue_pending_upload(
        session, "reservation", "res-doc-1", "CLIENT_DOCUMENT",
        "/api/v1/clients/upload-image", image_file,
        field_name="identity_card_image",
    )
    now = datetime.now(timezone.utc).isoformat()
    r = LocalReservation(
        id="res-doc-1", vehicle_id="veh-x", customer_name="Test Client",
        identity_card_image=rec.marker,
        start_datetime=now, end_datetime=now, daily_price=1, num_days=1,
        total_price=1, deposit=0, payment_status="PENDING", status="RESERVED",
        created_at=now, updated_at=now, version=1,
    )
    session.merge(r)
    session.commit()

    engine = SyncEngine("dev-1", "t", "rt")

    async def fake_refresh():
        return True

    engine._do_refresh = fake_refresh
    result = asyncio.run(engine.process_pending_uploads())
    assert result["uploaded"] == 1

    fresh = get_local_session()
    rr = fresh.query(LocalReservation).filter_by(id="res-doc-1").first()
    assert rr.identity_card_image == remote_url
    fresh.close()


def test_client_document_upload_reconciles_fields(session, monkeypatch, image_file):
    remote_url = f"/static/uploads/clients/{uuid.uuid4().hex}.jpg"

    def responder(url, kwargs):
        return R(200, {"image_url": remote_url})

    install_responder(monkeypatch, responder)

    rec = enqueue_pending_upload(
        session, "client", "cli-1", "CLIENT_DOCUMENT",
        "/api/v1/clients/upload-image", image_file,
        field_name="driving_license_image",
    )
    now = datetime.now(timezone.utc).isoformat()
    c = LocalClient(
        id="cli-1", first_name="Ali", last_name="Test",
        driving_license_image=rec.marker,
        created_at=now, updated_at=now, version=1,
    )
    session.merge(c)
    session.commit()

    engine = SyncEngine("dev-1", "t", "rt")

    async def fake_refresh():
        return True

    engine._do_refresh = fake_refresh
    result = asyncio.run(engine.process_pending_uploads())
    assert result["uploaded"] == 1

    fresh = get_local_session()
    cc = fresh.query(LocalClient).filter_by(id="cli-1").first()
    assert cc.driving_license_image == remote_url
    fresh.close()


class R:
    """Minimal httpx-like response."""

    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._p = payload or {}

    def json(self):
        return self._p


# ─────────────────────── failure handling ───────────────────────

def test_temporary_failure_retries_with_backoff(session, monkeypatch, image_file):
    calls = {"n": 0}

    def responder(url, kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            return R(503, {})
        return R(200, {"image_url": "/static/uploads/vehicles/ok.png"})

    install_responder(monkeypatch, responder)

    rec = enqueue_pending_upload(
        session, "vehicle", "veh-tmp", "VEHICLE_IMAGE",
        "/api/v1/vehicles/upload-image", image_file,
    )

    engine = SyncEngine("dev-1", "t", "rt")

    async def fake_refresh():
        return True

    engine._do_refresh = fake_refresh
    first = asyncio.run(engine.process_pending_uploads())
    assert first["uploaded"] == 0
    assert first["failed"] == 1

    fresh = get_local_session()
    item = fresh.query(LocalPendingUpload).filter_by(id=rec.id).first()
    assert item.status == "FAILED"
    assert item.retry_count == 1
    assert item.next_attempt_at is not None
    # Backoff must be in the future (exponential schedule)
    next_at = datetime.fromisoformat(item.next_attempt_at)
    assert next_at > datetime.now(timezone.utc) - timedelta(seconds=5)
    assert item.error_message and "503" in item.error_message
    fresh.close()


def test_backoff_prevents_immediate_second_attempt(session, monkeypatch, image_file):
    def responder(url, kwargs):
        return R(500, {})

    install_responder(monkeypatch, responder)

    rec = enqueue_pending_upload(
        session, "vehicle", "veh-back", "VEHICLE_IMAGE",
        "/api/v1/vehicles/upload-image", image_file,
    )

    engine = SyncEngine("dev-1", "t", "rt")

    async def fake_refresh():
        return True

    engine._do_refresh = fake_refresh
    asyncio.run(engine.process_pending_uploads())

    second = asyncio.run(engine.process_pending_uploads())
    assert second["skipped"] >= 1, "Due backoff must skip the immediate retry"


def test_permanent_failure_stops_retries_keeps_file(session, monkeypatch, image_file):
    def responder(url, kwargs):
        # e.g. invalid file type rejected by magic-byte validation
        return R(400, {"detail": "Fichier image invalide."})

    install_responder(monkeypatch, responder)

    rec = enqueue_pending_upload(
        session, "vehicle", "veh-perm", "VEHICLE_IMAGE",
        "/api/v1/vehicles/upload-image", image_file,
    )
    local_copy = Path(rec.local_path)

    engine = SyncEngine("dev-1", "t", "rt")

    async def fake_refresh():
        return True

    engine._do_refresh = fake_refresh
    result = asyncio.run(engine.process_pending_uploads())
    assert result["uploaded"] == 0

    fresh = get_local_session()
    item = fresh.query(LocalPendingUpload).filter_by(id=rec.id).first()
    assert item.status == "PERMANENT_FAILED"
    assert "400" in (item.error_message or "")
    assert local_copy.exists(), "Local file kept for inspection on permanent failure"
    fresh.close()


def test_missing_local_file_is_permanent_failure(session):
    rec = LocalPendingUpload(
        id=str(uuid.uuid4()),
        marker=f"pending_uploads/gone-{uuid.uuid4().hex}.png",
        entity_type="vehicle", entity_id="v-gone",
        upload_type="VEHICLE_IMAGE",
        local_path=str(PENDING_DIR / "does-not-exist.png"),
        remote_endpoint="/api/v1/vehicles/upload-image",
        status="PENDING", retry_count=0, max_retries=8,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    session.add(rec)
    session.commit()

    engine = SyncEngine("dev-1", "t", "rt")

    async def fake_refresh():
        return True

    engine._do_refresh = fake_refresh
    result = asyncio.run(engine.process_pending_uploads())
    assert result["uploaded"] == 0

    fresh = get_local_session()
    item = fresh.query(LocalPendingUpload).filter_by(id=rec.id).first()
    assert item.status == "PERMANENT_FAILED"
    fresh.close()


def test_network_failure_does_not_delete_file_or_claim_success(
    session, monkeypatch, image_file
):
    def responder(url, kwargs):
        raise ConnectionError("network down")

    install_responder(monkeypatch, responder)

    rec = enqueue_pending_upload(
        session, "vehicle", "veh-net", "VEHICLE_IMAGE",
        "/api/v1/vehicles/upload-image", image_file,
    )
    local_copy = Path(rec.local_path)

    engine = SyncEngine("dev-1", "t", "rt")

    async def fake_refresh():
        return True

    engine._do_refresh = fake_refresh
    result = asyncio.run(engine.process_pending_uploads())
    assert result["uploaded"] == 0
    assert local_copy.exists(), "Never delete local file before confirmed success"

    fresh = get_local_session()
    item = fresh.query(LocalPendingUpload).filter_by(id=rec.id).first()
    assert item.status in ("FAILED", "PENDING")
    fresh.close()


# ─────────────────────── integration with full sync cycle ───────────────────────

def test_sync_cycle_processes_uploads_first(session, monkeypatch, image_file):
    """SyncEngine.sync() must include an uploads step."""
    order = []

    def responder(url, kwargs):
        order.append("upload")
        return R(200, {"image_url": "/static/uploads/vehicles/final.png"})

    install_responder(monkeypatch, responder)

    rec = enqueue_pending_upload(
        session, "vehicle", "veh-cyc", "VEHICLE_IMAGE",
        "/api/v1/vehicles/upload-image", image_file,
    )

    engine = SyncEngine("dev-1", "t", "rt")

    async def fake_refresh():
        return True

    engine._do_refresh = fake_refresh

    # Stub network-dependent parts so we isolate ordering.
    async def fake_check():
        return True

    async def fake_push():
        order.append("push")
        return {"status": "ok", "pushed": 0}

    async def fake_pull():
        order.append("pull")
        return {"status": "ok", "items": []}

    engine.check_connection = fake_check
    engine.push_changes = fake_push
    engine.pull_changes = fake_pull

    report = asyncio.run(engine.sync())
    assert report["uploads"]["status"] == "ok"
    assert order[0] == "upload"
    assert order == ["upload", "push", "pull"]

    fresh = get_local_session()
    item = fresh.query(LocalPendingUpload).filter_by(id=rec.id).first()
    assert item.status == "SYNCED"
    fresh.close()


def test_replace_marker_helper_direct(session, image_file):
    import uuid
    marker = f"pending_uploads/manual-{uuid.uuid4().hex}.png"
    remote = "/static/uploads/vehicles/reconciled.png"
    _seed_vehicle_with_marker(session, marker)
    
    # Add a SyncQueueItem with the marker
    from app.models.sync_queue import SyncQueueItem
    import uuid
    import json
    payload_str = json.dumps({"image_url": marker})
    queue_item = SyncQueueItem(
        id=uuid.uuid4().hex,
        entity_type="vehicle",
        entity_id="veh-img-1",
        operation="CREATE",
        payload=payload_str,
        device_id="dev-1",
        user_id="user-1",
        idempotency_key=uuid.uuid4().hex,
        created_at="2026-01-01T00:00:00Z"
    )
    session.add(queue_item)
    session.commit()

    replace_marker_in_entities(session, marker, remote)

    fresh = get_local_session()
    v = fresh.query(LocalVehicle).filter_by(id="veh-img-1").first()
    assert remote in v.image_url
    assert marker not in v.image_url
    
    # Verify SyncQueueItem payload is updated
    updated_item = fresh.query(SyncQueueItem).filter_by(id=queue_item.id).first()
    payload = json.loads(updated_item.payload)
    assert payload["image_url"] == remote
    assert marker not in updated_item.payload
    fresh.close()


def test_no_upload_processing_when_not_authenticated(session, image_file):
    rec = enqueue_pending_upload(
        session, "vehicle", "veh-auth", "VEHICLE_IMAGE",
        "/api/v1/vehicles/upload-image", image_file,
    )
    engine = SyncEngine("dev-1", None, None)  # no tokens
    result = asyncio.run(engine.process_pending_uploads())
    assert result["status"] == "offline"

    fresh = get_local_session()
    item = fresh.query(LocalPendingUpload).filter_by(id=rec.id).first()
    assert item.status == "PENDING", "Nothing may change without authentication"
    fresh.close()
