"""
Real-time event broadcaster for syncing events across Desktop, Mobile, and Web clients.
Provides WebSocket, SSE, and recent event history capabilities.
"""
import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Set, Dict, Any, List
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class EventBroadcaster:
    """Singleton managing active WebSocket/SSE connections and broadcasting events."""

    def __init__(self, max_history: int = 100):
        self._active_sockets: Set[WebSocket] = set()
        self._event_history: deque = deque(maxlen=max_history)
        self._lock = asyncio.Lock()

    async def connect_socket(self, websocket: WebSocket):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self._active_sockets.add(websocket)
        logger.info("Client connected to Realtime Event Broadcaster (Total: %d)", len(self._active_sockets))

    async def disconnect_socket(self, websocket: WebSocket):
        """Unregister a disconnected WebSocket."""
        async with self._lock:
            self._active_sockets.discard(websocket)
        logger.info("Client disconnected from Realtime Event Broadcaster (Total: %d)", len(self._active_sockets))

    async def broadcast_event(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        message: str,
        origin: str = "API",
        data: Optional[Dict[str, Any]] = None,
        vehicle_id: Optional[str] = None,
        vehicle_registration: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record and broadcast an event to all connected clients.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        event = {
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "message": message,
            "origin": origin,
            "vehicle_id": str(vehicle_id) if vehicle_id else None,
            "vehicle_registration": vehicle_registration,
            "timestamp": now_iso,
            "data": data or {},
        }

        # Store in recent history
        self._event_history.append(event)
        logger.info("[REALTIME EVENT] %s: %s (Origin: %s)", event_type, message, origin)

        # Broadcast to all open WebSocket connections
        dead_sockets = set()
        async with self._lock:
            sockets_to_notify = list(self._active_sockets)

        for ws in sockets_to_notify:
            try:
                await ws.send_text(json.dumps(event))
            except Exception as e:
                logger.warning("Failed to send event to WebSocket client: %s", e)
                dead_sockets.add(ws)

        if dead_sockets:
            async with self._lock:
                for dead in dead_sockets:
                    self._active_sockets.discard(dead)

        return event

    def get_recent_events(self, since: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent events optionally filtered by timestamp."""
        events = list(self._event_history)
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                events = [
                    e for e in events
                    if datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")) > since_dt
                ]
            except Exception:
                pass
        return events[-limit:]


# Global broadcaster instance
broadcaster = EventBroadcaster()
