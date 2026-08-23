"""
Real-time Events API router — WebSocket, SSE, and polling endpoints.
"""
import asyncio
import json
import logging
from typing import Optional, List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.responses import StreamingResponse

from app.services.event_broadcaster import broadcaster

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["Realtime Events"])


def _extract_bearer_token(request_or_ws) -> Optional[str]:
    """Extract a bearer token from the Authorization header or `?token=` query param."""
    auth = request_or_ws.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    token_param = request_or_ws.query_params.get("token")
    return token_param.strip() if token_param else None


def _require_valid_token(token: Optional[str]) -> Optional[dict]:
    """Require a valid access token for realtime access.

    Uses the existing JWT handler (single source of truth for authentication).
    Returns the decoded payload on success, or None when the token is missing,
    malformed, forged, expired, or is a refresh token instead of an access token.
    """
    if not token:
        logger.warning("Rejected realtime connection without a token")
        return None
    from app.dependencies import get_jwt_handler
    payload = get_jwt_handler().verify_access_token(token)
    if not payload:
        logger.warning("Rejected realtime connection with invalid/expired token")
        return None
    return payload


@router.websocket("/ws")
async def websocket_events_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time synchronization and notifications.
    Authentication is REQUIRED: clients must send a valid access token via
    the Authorization header (Bearer) or `?token=` query parameter.
    Missing, invalid, expired, malformed or forged tokens are rejected (4401).
    """
    payload = _require_valid_token(_extract_bearer_token(websocket))
    if not payload:
        await websocket.close(code=4401)
        return

    await broadcaster.connect_socket(websocket)
    try:
        # Send initial connected greeting with recent events
        recent = broadcaster.get_recent_events(limit=10)
        await websocket.send_text(json.dumps({
            "event_type": "CONNECTED",
            "message": "Connected to Realtime Events Stream",
            "recent_events": recent
        }))

        # Keep connection alive while listening for client pings
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "PING":
                    await websocket.send_text(json.dumps({"type": "PONG"}))
            except Exception as e:
                logger.warning(f"WebSocket decode error: {e}, payload: {data}")
    except WebSocketDisconnect:
        await broadcaster.disconnect_socket(websocket)
    except Exception as e:
        logger.warning("WebSocket exception: %s", e)
        await broadcaster.disconnect_socket(websocket)


@router.get("/recent")
async def get_recent_events(
    request: Request,
    since: Optional[str] = Query(None, description="ISO timestamp to filter events after"),
    limit: int = Query(50, ge=1, le=100)
):
    """
    Fetch recent events for polling fallback or catch-up sync.
    Authentication is REQUIRED: requests without a valid bearer token get 401.
    No business events leak to anonymous clients.
    """
    if not _require_valid_token(_extract_bearer_token(request)):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Authentication required")
    items = broadcaster.get_recent_events(since=since, limit=limit)
    return {"status": "ok", "count": len(items), "events": items}


@router.get("/stream")
async def sse_events_stream(request: Request):
    """
    Server-Sent Events (SSE) stream for clients that prefer SSE over WebSockets.
    Authentication is REQUIRED: requests without a valid bearer token get 401.
    """
    if not _require_valid_token(_extract_bearer_token(request)):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Authentication required")
    async def event_generator():
        last_seen = None
        while True:
            if await request.is_disconnected():
                break

            events = broadcaster.get_recent_events(since=last_seen, limit=10)
            for ev in events:
                last_seen = ev["timestamp"]
                yield f"data: {json.dumps(ev)}\n\n"

            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
