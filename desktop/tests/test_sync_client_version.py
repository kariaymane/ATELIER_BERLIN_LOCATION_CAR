import pytest
import asyncio
import uuid
from unittest.mock import AsyncMock, patch
from app.database import init_local_db, get_local_session
from app.models.client import LocalClient
from app.sync.engine import SyncEngine
from app.sync.queue import SyncQueue

@pytest.fixture(autouse=True)
def setup_db():
    init_local_db()
    session = get_local_session()
    yield session
    session.close()

@pytest.mark.asyncio
async def test_push_client_version_lookup(setup_db):
    session = setup_db
    # create a client with a specific version
    client = LocalClient(id="c99", first_name="Test", version=5)
    session.add(client)
    session.commit()

    # enqueue a client UPDATE operation
    device_id = "test-device-push"
    user_id = str(uuid.uuid4())
    queue = SyncQueue(session, device_id, user_id)
    payload = {"first_name": "Test"}
    queue.enqueue("client", "c99", "UPDATE", payload)
    session.commit()

    # mock httpx.AsyncClient.post to capture the payload sent
    async def mock_post(*args, **kwargs):
        class MockResponse:
            status_code = 200
            def json(self):
                return {"results": [{"status": "ok", "server_version": 6}]}
        return MockResponse()

    with patch('httpx.AsyncClient.post', new=AsyncMock(side_effect=mock_post)) as mocked_post:
        engine = SyncEngine(device_id=device_id, access_token="dummy", refresh_token=None)
        result = await engine.push_changes()
        assert mocked_post.called
        sent_json = mocked_post.call_args[1]['json']
        assert len(sent_json['items']) == 1
        # version should be the client's version (5)
        assert sent_json['items'][0]['version'] == 5
        assert result['status'] == "ok"
        assert result['pushed'] == 1
