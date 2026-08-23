"""
Realtime events authentication tests.

Verifies that WebSocket, SSE and /events/recent endpoints enforce JWT
authentication using the existing JWT handler:

    valid token       -> ACCEPT
    missing token     -> REJECT
    invalid token     -> REJECT
    expired token     -> REJECT
    malformed token   -> REJECT
    forged token      -> REJECT
    refresh token     -> REJECT (only access tokens grant realtime access)

Also verifies authenticated event delivery, reconnect after network loss,
and that no business events leak to anonymous clients.
"""
import pytest
from starlette.testclient import TestClient

from app.main import app
from app.services.event_broadcaster import broadcaster


@pytest.fixture
def sync_client():
    """Starlette TestClient for WebSocket + HTTP tests against the ASGI app."""
    with TestClient(app) as c:
        yield c


def _ws_url(token=None):
    url = "/api/v1/events/ws"
    if token is not None:
        url += f"?token={token}"
    return url


class TestWebSocketAuth:
    def test_valid_token_accepted(self, sync_client, admin_token):
        with sync_client.websocket_connect(_ws_url(admin_token)) as ws:
            msg = ws.receive_json()
            assert msg["event_type"] == "CONNECTED"

    def test_valid_token_via_authorization_header(self, sync_client, admin_token):
        # Starlette TestClient passes extra headers to the WS handshake.
        with sync_client.websocket_connect(
            "/api/v1/events/ws", headers={"Authorization": f"Bearer {admin_token}"}
        ) as ws:
            msg = ws.receive_json()
            assert msg["event_type"] == "CONNECTED"

    def test_missing_token_rejected(self, sync_client):
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with sync_client.websocket_connect(_ws_url()):
                pass
        assert exc_info.value.code == 4401

    def test_invalid_garbage_token_rejected(self, sync_client):
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with sync_client.websocket_connect(_ws_url("not-a-real-token")):
                pass
        assert exc_info.value.code == 4401

    def test_expired_token_rejected(self, sync_client, admin_user):
        from datetime import timedelta
        from app.auth.jwt_handler import JWTHandler
        from app.config import get_settings
        settings = get_settings()
        expired_handler = JWTHandler(
            secret=settings.JWT_SECRET,
            refresh_secret=settings.JWT_REFRESH_SECRET,
            access_expire_minutes=-1,  # already expired
        )
        token = expired_handler.create_access_token(
            user_id=str(admin_user.id), role=admin_user.role
        )
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with sync_client.websocket_connect(_ws_url(token)):
                pass
        assert exc_info.value.code == 4401

    def test_malformed_token_rejected(self, sync_client):
        from starlette.websockets import WebSocketDisconnect
        malformed = "eyJhbGciOiJIUzI1NiJ9.not-base64!!"
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with sync_client.websocket_connect(_ws_url(malformed)):
                pass
        assert exc_info.value.code == 4401

    def test_forged_token_rejected(self, sync_client, admin_user):
        """Token signed with a different secret must be rejected."""
        from app.auth.jwt_handler import JWTHandler
        forger = JWTHandler(
            secret="attacker-owned-secret",
            refresh_secret="attacker-owned-refresh",
        )
        token = forger.create_access_token(user_id=str(admin_user.id), role="ADMIN")
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with sync_client.websocket_connect(_ws_url(token)):
                pass
        assert exc_info.value.code == 4401

    def test_refresh_token_not_valid_for_realtime(self, sync_client, admin_user):
        """A refresh token must never grant realtime access."""
        from app.dependencies import get_jwt_handler
        refresh_token, _ = get_jwt_handler().create_refresh_token(
            user_id=str(admin_user.id)
        )
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with sync_client.websocket_connect(_ws_url(refresh_token)):
                pass
        assert exc_info.value.code == 4401

    def test_employee_valid_token_accepted(self, sync_client, employee_token):
        with sync_client.websocket_connect(_ws_url(employee_token)) as ws:
            msg = ws.receive_json()
            assert msg["event_type"] == "CONNECTED"


class TestRecentEventsAuth:
    @pytest.mark.asyncio
    async def test_missing_token_gets_401_no_leakage(self, client, admin_token):
        await broadcaster.broadcast_event(
            event_type="UPDATED",
            entity_type="reservation",
            entity_id="leak-test-1",
            message="CONFIDENTIAL reservation data",
            data={"customer_name": "Secret Customer"},
        )
        resp = await client.get("/api/v1/events/recent")
        assert resp.status_code == 401
        body = resp.json()
        serialized = str(body)
        assert "Secret Customer" not in serialized
        assert "CONFIDENTIAL" not in serialized

    @pytest.mark.asyncio
    async def test_invalid_token_gets_401(self, client):
        resp = await client.get(
            "/api/v1/events/recent",
            headers={"Authorization": "Bearer garbage-token"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_token_gets_events(self, client, admin_token):
        await broadcaster.broadcast_event(
            event_type="UPDATED",
            entity_type="vehicle",
            entity_id="veh-auth-1",
            message="Vehicle updated",
        )
        resp = await client.get(
            "/api/v1/events/recent",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert any(ev.get("entity_id") == "veh-auth-1" for ev in data["events"])

    @pytest.mark.asyncio
    async def test_refresh_token_gets_401(self, client, admin_user):
        from app.dependencies import get_jwt_handler
        refresh_token, _ = get_jwt_handler().create_refresh_token(
            user_id=str(admin_user.id)
        )
        resp = await client.get(
            "/api/v1/events/recent",
            headers={"Authorization": f"Bearer {refresh_token}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_forged_token_gets_401(self, client, admin_user):
        from app.auth.jwt_handler import JWTHandler
        forger = JWTHandler(secret="attacker-secret", refresh_secret="x")
        token = forger.create_access_token(user_id=str(admin_user.id), role="ADMIN")
        resp = await client.get(
            "/api/v1/events/recent",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401


class TestSSEAuth:
    @pytest.mark.asyncio
    async def test_missing_token_sse_401(self, client):
        resp = await client.get("/api/v1/events/stream")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_sse_401(self, client):
        resp = await client.get(
            "/api/v1/events/stream",
            headers={"Authorization": "Bearer bad"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_token_sse_accepted(self, admin_token):
        # The SSE stream never completes, so call the endpoint handler
        # directly: a valid token must produce a StreamingResponse (not 401).
        from types import MappingProxyType

        class _FakeRequest:
            def __init__(self, headers):
                self.headers = MappingProxyType(headers)

        from app.api.v1.events import sse_events_stream
        response = await sse_events_stream(
            _FakeRequest({"Authorization": f"Bearer {admin_token}"})
        )
        assert response.media_type == "text/event-stream"


class TestReconnectAndDelivery:
    def test_reconnect_after_disconnect_with_valid_token(
        self, sync_client, admin_token
    ):
        """Simulate network loss: disconnect then reconnect with valid token."""
        try:
            with sync_client.websocket_connect(_ws_url(admin_token)) as ws:
                assert ws.receive_json()["event_type"] == "CONNECTED"
        finally:
            pass

        with sync_client.websocket_connect(_ws_url(admin_token)) as ws2:
            assert ws2.receive_json()["event_type"] == "CONNECTED"

    def test_authenticated_event_delivery_via_ws(self, sync_client, admin_token):
        """Events broadcast server-side reach authenticated WebSocket clients."""
        with sync_client.websocket_connect(_ws_url(admin_token)) as ws:
            greeting = ws.receive_json()
            assert greeting["event_type"] == "CONNECTED"

            # Broadcast on the app's own event loop via the TestClient portal.
            sync_client.portal.call(
                broadcaster.broadcast_event,
                "CREATED",
                "reservation",
                "ws-delivery-1",
                "Reservation created",
            )

            found = False
            for _ in range(10):
                msg = ws.receive_json()
                if msg.get("event_type") == "CREATED":
                    assert msg["entity_id"] == "ws-delivery-1"
                    found = True
                    break
            assert found, "Authenticated client did not receive broadcast event"
