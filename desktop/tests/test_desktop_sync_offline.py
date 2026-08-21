import pytest
import uuid
import json
from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.sync_queue import SyncQueueItem
from app.sync.queue import SyncQueue
from app.sync.engine import SyncEngine


@pytest.fixture(autouse=True)
def setup_db():
    init_local_db()
    session = get_local_session()
    yield session
    session.close()


def test_offline_queue_enqueuing_and_idempotency(setup_db):
    session = setup_db
    device_id = "test-device-desk-01"
    user_id = str(uuid.uuid4())
    queue = SyncQueue(session, device_id, user_id)

    v_id = str(uuid.uuid4())
    payload = {
        "id": v_id,
        "registration": "99999-A-1",
        "brand": "Porsche",
        "model": "Cayenne",
        "daily_rental_price": 2000.0,
        "status": "AVAILABLE"
    }

    # Enqueue CREATE
    item = queue.enqueue("vehicle", v_id, "CREATE", payload)
    assert item is not None
    assert item.sync_status == "PENDING"
    assert item.idempotency_key is not None

    pending = queue.get_pending()
    assert len(pending) == 1
    assert pending[0].entity_id == v_id
    assert json.loads(pending[0].payload)["brand"] == "Porsche"

    # Mark synced
    queue.mark_synced(item.id)
    pending_after = queue.get_pending()
    assert len(pending_after) == 0

    # Cleanup
    session.query(SyncQueueItem).filter_by(id=item.id).delete()
    session.commit()


@pytest.mark.asyncio
async def test_sync_engine_offline_handling():
    engine = SyncEngine(device_id="desk-dev-99")
    # Without server reachable on dummy port, check_connection returns False
    engine._base_url = "http://127.0.0.1:59999"
    is_conn = await engine.check_connection()
    assert is_conn is False
    assert engine.is_online is False
