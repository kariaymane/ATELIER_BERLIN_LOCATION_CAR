"""
Real-time Events Client for Desktop application.
Uses Qt WebSockets with auto-reconnection and HTTP polling fallback.
"""
import json
import logging
from typing import Optional
from PySide6.QtCore import QObject, Signal, QTimer, QUrl
from PySide6.QtWebSockets import QWebSocket
from PySide6.QtNetwork import QNetworkRequest
import requests

from app.config import API_BASE_URL, API_VERSION

logger = logging.getLogger(__name__)


class RealtimeEventsClient(QObject):
    """
    Client connecting to the FastAPI Real-time WebSocket event stream.
    Emits event_received(dict) when an action occurs from Mobile or API.
    """

    event_received = Signal(dict)
    connection_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ws = QWebSocket()
        self._is_connected = False
        self._last_event_time: Optional[str] = None

        # Determine ws:// url from API_BASE_URL
        ws_base = API_BASE_URL.replace("http://", "ws://").replace("https://", "wss://")
        self._ws_url = f"{ws_base}/api/{API_VERSION}/events/ws"
        self._http_recent_url = f"{API_BASE_URL}/api/{API_VERSION}/events/recent"

        # Wire Qt WebSocket signals
        self._ws.connected.connect(self._on_ws_connected)
        self._ws.disconnected.connect(self._on_ws_disconnected)
        self._ws.textMessageReceived.connect(self._on_message_received)
        self._ws.errorOccurred.connect(self._on_ws_error)

        # Reconnect timer
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(4000)
        self._reconnect_timer.timeout.connect(self._try_connect)

        # Polling fallback timer
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self._poll_recent_events)

    def start(self):
        """Start listening for real-time events."""
        logger.info("Starting Real-time Events Client connecting to %s", self._ws_url)
        self._try_connect()
        self._poll_timer.start()

    def stop(self):
        """Stop listening and close connections."""
        self._reconnect_timer.stop()
        self._poll_timer.stop()
        if self._ws.isValid():
            self._ws.close()

    def _try_connect(self):
        if not self._is_connected:
            try:
                self._ws.open(QUrl(self._ws_url))
            except Exception as e:
                logger.debug("WebSocket connect attempt failed: %s", e)

    def _on_ws_connected(self):
        logger.info("WebSocket connected successfully to %s", self._ws_url)
        self._is_connected = True
        self._reconnect_timer.stop()
        self.connection_changed.emit(True)

    def _on_ws_disconnected(self):
        logger.info("WebSocket disconnected from %s", self._ws_url)
        self._is_connected = False
        self.connection_changed.emit(False)
        self._reconnect_timer.start()

    def _on_ws_error(self, error_code):
        logger.debug("WebSocket error %s: %s", error_code, self._ws.errorString())
        self._is_connected = False
        self._reconnect_timer.start()

    def _on_message_received(self, text: str):
        try:
            event = json.loads(text)
            event_type = event.get("event_type", "")
            if event_type == "CONNECTED":
                logger.info("Realtime Events Stream active: %s", event.get("message"))
                return
            if event_type == "PONG":
                return

            self._last_event_time = event.get("timestamp")
            logger.info("Real-time event received via WebSocket: %s", event.get("message"))
            self.event_received.emit(event)
        except Exception as e:
            logger.error("Error processing WebSocket message: %s", e)

    def _poll_recent_events(self):
        """Polling fallback when WebSocket is offline or for catch-up."""
        if self._is_connected:
            return  # WebSocket is handling live stream

        try:
            params = {}
            if self._last_event_time:
                params["since"] = self._last_event_time
            params["limit"] = 10

            resp = requests.get(self._http_recent_url, params=params, timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                for ev in data.get("events", []):
                    self._last_event_time = ev.get("timestamp")
                    logger.info("Real-time event received via Polling: %s", ev.get("message"))
                    self.event_received.emit(ev)
        except Exception:
            pass  # Quiet during network disconnect
