"""Regression: SyncEngine.pull_changes() must not raise, and must apply the
15-second cursor-rewind margin, once ``_last_sync`` is set.

Root cause of the v1.1.0 P0: ``engine.py`` used ``timedelta`` in ``pull_changes``
to compute ``since = _last_sync - 15s`` but only imported ``datetime, timezone``.
Every pull after the first (``_last_sync`` populated) raised
``NameError: name 'timedelta' is not defined`` — caught only at the thread level,
so the desktop silently stopped pulling server changes. No test exercised this
path (``test_sync_client_pull.py`` only covers ``apply_pulled_items``).
"""
import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from app.database import init_local_db
import app.sync.engine as engine_mod
from app.sync.engine import SyncEngine


@pytest.fixture(autouse=True)
def _db():
    init_local_db()


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Captures the JSON body of the /sync/pull POST and returns an empty change set."""

    last_body = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.last_body = json
        return _FakeResponse(
            {"items": [], "server_time": "2026-09-04T10:00:00+00:00"}
        )


def test_pull_changes_after_first_sync_does_not_raise_and_rewinds_cursor(monkeypatch):
    monkeypatch.setattr(engine_mod.httpx, "AsyncClient", _FakeAsyncClient)

    eng = SyncEngine(device_id="dev", access_token="tok", refresh_token="rtok")
    last_sync = datetime(2026, 9, 4, 9, 0, 0, tzinfo=timezone.utc)
    eng._last_sync = last_sync

    result = asyncio.run(eng.pull_changes())

    assert result["status"] == "ok", result
    sent_since = datetime.fromisoformat(_FakeAsyncClient.last_body["since"])
    assert sent_since == last_sync - timedelta(seconds=15), (
        f"expected 15s rewind, got {sent_since!r}"
    )


def test_pull_changes_first_ever_sync_uses_epoch_floor(monkeypatch):
    monkeypatch.setattr(engine_mod.httpx, "AsyncClient", _FakeAsyncClient)

    eng = SyncEngine(device_id="dev", access_token="tok", refresh_token="rtok")
    assert eng._last_sync is None

    result = asyncio.run(eng.pull_changes())

    assert result["status"] == "ok"
    sent_since = datetime.fromisoformat(_FakeAsyncClient.last_body["since"])
    assert sent_since.year == 2000
