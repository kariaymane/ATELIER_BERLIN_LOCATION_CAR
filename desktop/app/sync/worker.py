import json
import logging
from datetime import datetime, timezone
from PySide6.QtCore import QThread, Signal

from app.database import get_local_session
from app.sync.queue import SyncQueue
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.services.api_client import ApiClient

logger = logging.getLogger(__name__)

class SyncWorker(QThread):
    sync_finished = Signal(bool, list)  # is_online, pulled_items
    sync_status_changed = Signal(str)

    def __init__(self, api_client: ApiClient, device_id: str, user_id: str):
        super().__init__()
        self._api = api_client
        self._device_id = device_id
        self._user_id = user_id

    def run(self):
        if not self._api._access_token:
            self.sync_status_changed.emit("offline")
            self.sync_finished.emit(False, [])
            return

        self.sync_status_changed.emit("syncing")
        session = get_local_session()
        pulled_items = []
        is_online = False
        try:
            queue = SyncQueue(session, self._device_id, self._user_id)
            pending = queue.get_pending()

            # PUSH
            if pending:
                items = []
                for item in pending:
                    version = 1
                    try:
                        if item.entity_type == "vehicle":
                            v = session.query(LocalVehicle).filter_by(id=item.entity_id).first()
                            if v: version = v.version
                        elif item.entity_type == "reservation":
                            r = session.query(LocalReservation).filter_by(id=item.entity_id).first()
                            if r: version = r.version
                        elif item.entity_type == "maintenance":
                            m = session.query(LocalMaintenance).filter_by(id=item.entity_id).first()
                            if m: version = m.version
                    except Exception as e:
                        logger.error("Error fetching version for %s: %s", item.entity_id, e)

                    payload = json.loads(item.payload)
                    payload["version"] = version

                    items.append({
                        "entity_type": item.entity_type,
                        "entity_id": item.entity_id,
                        "operation": item.operation,
                        "payload": payload,
                        "device_id": item.device_id,
                        "idempotency_key": item.idempotency_key,
                        "timestamp": item.created_at,
                        "version": version,
                    })

                response = self._api._request("post", "/api/v1/sync/push", json={"items": items})
                if response:
                    if response.status_code == 200:
                        results = response.json().get("results", [])
                        for i, result in enumerate(results):
                            if i < len(pending):
                                status = result.get("status", "error")
                                if status == "ok":
                                    queue.mark_synced(pending[i].id)
                                    server_version = result.get("server_version")
                                    if server_version and pending[i].entity_type == "vehicle":
                                        v = session.query(LocalVehicle).filter_by(id=pending[i].entity_id).first()
                                        if v:
                                            v.version = server_version
                                            session.commit()
                                elif status == "conflict":
                                    queue.mark_conflict(pending[i].id, result.get("message", "Conflict"))
                                else:
                                    queue.mark_failed(pending[i].id, result.get("message", "Error"))
                        logger.info("Pushed %d items to server", len(pending))
                    elif response.status_code == 401:
                        self._api._do_refresh()

            # PULL
            since = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
            response = self._api._request(
                "post", "/api/v1/sync/pull",
                json={"since": since, "device_id": self._device_id}
            )

            if response:
                if response.status_code == 200:
                    data = response.json()
                    pulled_items = data.get("items", [])
                    is_online = True
                elif response.status_code == 401:
                    self._api._do_refresh()
                    is_online = True
            else:
                is_online = False

        except Exception as e:
            logger.error("Sync error in thread: %s", e)
            is_online = False
        finally:
            session.close()

        status_str = "online" if is_online else "offline"
        self.sync_status_changed.emit(status_str)
        self.sync_finished.emit(is_online, pulled_items)
