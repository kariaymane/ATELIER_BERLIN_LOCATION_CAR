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


@router.websocket("/ws")
async def websocket_events_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time synchronization and notifications.
    Clients connect to receive live events as they happen.
    """
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
    since: Optional[str] = Query(None, description="ISO timestamp to filter events after"),
    limit: int = Query(50, ge=1, le=100)
):
    """
    Fetch recent events for polling fallback or catch-up sync.
    """
    items = broadcaster.get_recent_events(since=since, limit=limit)
    return {"status": "ok", "count": len(items), "events": items}


@router.get("/stream")
async def sse_events_stream(request: Request):
    """
    Server-Sent Events (SSE) stream for clients that prefer SSE over WebSockets.
    """
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
