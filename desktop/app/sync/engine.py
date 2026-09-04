import uuid
"""
Sync engine — periodically syncs local changes to server.
Handles offline-first queuing, retries, idempotency, and connection failures gracefully.
"""
import json
import httpx
from typing import Optional
from datetime import datetime, timezone, timedelta
import logging

from app.sync.queue import SyncQueue
from app.database import get_local_session
from app.models.vehicle import LocalVehicle
from app.models.vehicle_image import LocalVehicleImage
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.models.client import LocalClient
from app.sync.uploads import PendingUploadProcessor
from app.config import API_BASE_URL, API_VERSION

logger = logging.getLogger(__name__)


class SyncEngine:
    """Handles bidirectional synchronization between SQLite and PostgreSQL via FastAPI."""

    def __init__(self, device_id: str, access_token: str = None, refresh_token: str = None, base_url: str = None):
        self._device_id = device_id
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._base_url = (base_url or API_BASE_URL).rstrip("/")
        self._is_online = False
        self._last_sync: Optional[datetime] = None
        # Highest /sync/bootstrap revision applied — guards against a truncated
        # 200 response purging a populated cache (see bootstrap()).
        self._bootstrap_revision: int = 0
        self._upload_processor = PendingUploadProcessor(self)

    def set_token(self, token: str, refresh_token: str = None):
        """Update the access token and optional refresh token."""
        self._access_token = token
        if refresh_token:
            self._refresh_token = refresh_token

    @property
    def is_online(self) -> bool:
        return self._is_online

    async def _do_refresh(self) -> bool:
        """Attempt to refresh access token using refresh_token."""
        if not self._refresh_token:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(
                    f"{self._base_url}/api/v1/auth/refresh",
                    json={"refresh_token": self._refresh_token},
                    headers={"Content-Type": "application/json"},
                )
                if r.status_code == 200:
                    data = r.json()
                    self._access_token = data.get("access_token", self._access_token)
                    self._refresh_token = data.get("refresh_token", self._refresh_token)
                    logger.info("SyncEngine: Access token refreshed successfully")
                    return True
        except Exception as e:
            logger.error("SyncEngine: Token refresh failed: %s", e)
        return False

    async def check_connection(self) -> bool:
        """Check if the server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(f"{self._base_url}/health")
                self._is_online = (response.status_code == 200)
        except (httpx.ConnectError, httpx.TimeoutException, Exception):
            self._is_online = False
        return self._is_online

    async def push_changes(self) -> dict:
        """Push pending local changes to the server."""
        logger.debug("SYNC PUSH: Authorization header present = %s", bool(self._access_token))
        if not self._access_token:
            return {"status": "offline", "message": "Not authenticated"}

        session = get_local_session()
        try:
            queue = SyncQueue(session, self._device_id)
            pending = queue.get_pending()

            if not pending:
                return {"status": "ok", "pushed": 0}

            # Build push payload
            items = []
            for item in pending:
                version = 1
                try:
                    if item.entity_type == "vehicle":
                        v = session.query(LocalVehicle).filter_by(id=item.entity_id).first()
                        if v:
                            version = v.version
                    elif item.entity_type == "reservation":
                        r = session.query(LocalReservation).filter_by(id=item.entity_id).first()
                        if r:
                            version = r.version
                    elif item.entity_type == "maintenance":
                        m = session.query(LocalMaintenance).filter_by(id=item.entity_id).first()
                        if m:
                            version = m.version
                    elif item.entity_type == "client":
                        c = session.query(LocalClient).filter_by(id=item.entity_id).first()
                        if c:
                            version = c.version
                except Exception as e:
                    logger.debug("Version lookup note: %s", e)

                payload = json.loads(item.payload)
                payload["version"] = version
                if "id" not in payload or not payload["id"]:
                    payload["id"] = item.entity_id

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

            # Send to server
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self._base_url}/api/{API_VERSION}/sync/push",
                    json={"items": items},
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )

                if response.status_code == 401 and self._refresh_token:
                    if await self._do_refresh():
                        response = await client.post(
                            f"{self._base_url}/api/{API_VERSION}/sync/push",
                            json={"items": items},
                            headers={"Authorization": f"Bearer {self._access_token}"},
                        )

                if response.status_code == 200:
                    results = response.json().get("results", [])
                    conflicts = []
                    for i, result in enumerate(results):
                        if i < len(pending):
                            res_status = result.get("status", "error")
                            if res_status == "ok":
                                queue.mark_synced(pending[i].id)
                                s_ver = result.get("server_version")
                                if s_ver:
                                    etype = pending[i].entity_type
                                    eid = pending[i].entity_id
                                    ent = None
                                    if etype == "vehicle":
                                        ent = session.query(LocalVehicle).filter_by(id=eid).first()
                                    elif etype == "reservation":
                                        ent = session.query(LocalReservation).filter_by(id=eid).first()
                                    elif etype == "maintenance":
                                        ent = session.query(LocalMaintenance).filter_by(id=eid).first()
                                    elif etype == "client":
                                        ent = session.query(LocalClient).filter_by(id=eid).first()
                                    if ent and hasattr(ent, "version"):
                                        ent.version = s_ver
                                        session.commit()
                            elif res_status == "conflict":
                                queue.mark_conflict(pending[i].id, result.get("message", "Conflict"))
                                conflicts.append({
                                    "entity_type": pending[i].entity_type,
                                    "entity_id": pending[i].entity_id,
                                    "message": result.get("message", "Conflict"),
                                })
                                # SERVER AUTHORITY: a server-rejected reservation
                                # must NOT remain RESERVED locally — a stale local
                                # row would permanently block those vehicle dates
                                # in the offline overlap check.
                                if pending[i].entity_type == "reservation" and pending[i].operation == "CREATE":
                                    lr = session.query(LocalReservation).filter_by(
                                        id=pending[i].entity_id).first()
                                    if lr and (lr.status or "").upper() in ("RESERVED", "ACTIVE"):
                                        lr.status = "CANCELLED"
                                        lr.payment_status = "CANCELLED"
                                        lr.updated_at = datetime.now(timezone.utc).isoformat()
                                        lr.version += 1
                                        session.commit()
                                        from app.services.event_bus import get_event_bus
                                        get_event_bus().data_refreshed.emit()
                                        logger.warning(
                                            "SYNC CONFLICT: reservation %s rejected by server (%s) — reverted locally",
                                            pending[i].entity_id, result.get("message"),
                                        )
                            else:
                                queue.mark_failed(pending[i].id, result.get("message", "Error"))
                    pushed_count = sum(1 for r in results if r.get("status") == "ok")
                    self._is_online = True
                    return {"status": "ok", "pushed": pushed_count,
                            "conflicts": conflicts, "results": results}
                elif response.status_code == 401:
                    return {"status": "auth_error", "message": "Token expired"}
                else:
                    return {"status": "error", "message": f"Server error: {response.status_code}"}

        except (httpx.ConnectError, httpx.TimeoutException, Exception) as e:
            self._is_online = False
            return {"status": "offline", "message": str(e)}
        finally:
            session.close()

    async def pull_changes(self) -> dict:
        """Pull changes from server since last sync and merge into SQLite."""
        logger.debug("SYNC PULL: Authorization header present = %s", bool(self._access_token))
        if not self._access_token:
            return {"status": "offline", "message": "Not authenticated"}

        # Apply a 15-second rewind margin to eliminate any commit-race or clock-skew window.
        since = (self._last_sync - timedelta(seconds=15)) if self._last_sync else datetime(2000, 1, 1, tzinfo=timezone.utc)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self._base_url}/api/{API_VERSION}/sync/pull",
                    json={
                        "since": since.isoformat(),
                        "device_id": self._device_id,
                    },
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )

                if response.status_code == 401 and self._refresh_token:
                    if await self._do_refresh():
                        response = await client.post(
                            f"{self._base_url}/api/{API_VERSION}/sync/pull",
                            json={
                                "since": since.isoformat(),
                                "device_id": self._device_id,
                            },
                            headers={"Authorization": f"Bearer {self._access_token}"},
                        )

                if response.status_code == 200:
                    data = response.json()
                    from app.utils.datetime_utils import parse_datetime_utc
                    items = data.get("items", [])
                    success = self.apply_pulled_items(items)
                    if not success:
                        return {"status": "error", "message": "Failed to apply pulled items into SQLite"}
                    self._last_sync = parse_datetime_utc(data["server_time"])
                    self._is_online = True
                    return {"status": "ok", "items": items}
                else:
                    return {"status": "error", "message": f"Server error: {response.status_code}"}

        except (httpx.ConnectError, httpx.TimeoutException, Exception) as e:
            self._is_online = False
            return {"status": "offline", "message": str(e)}

    def apply_pulled_items(self, items: list) -> bool:
        """Merge pulled server items directly into local SQLite database."""
        if not items:
            return True

        session = get_local_session()
        try:
            pending_ids = set()
            try:
                from app.models.sync_queue import SyncQueueItem
                p_rows = session.query(SyncQueueItem.entity_id).filter(
                    SyncQueueItem.sync_status == "PENDING"
                ).all()
                pending_ids = {str(r[0]) for r in p_rows if r[0]}
            except Exception:
                pass

            for item in items:
                etype = item.get("entity_type", "").lower()
                eid = str(item.get("entity_id", ""))
                if eid in pending_ids:
                    logger.info("Skipping pulled item for %s %s: pending local mutation exists", etype, eid)
                    continue
                op = item.get("operation", "").upper()
                payload = item.get("payload", {})
                ver = item.get("version", 1)

                if etype == "vehicle":
                    v = session.query(LocalVehicle).filter_by(id=eid).first()
                    if op == "DELETE":
                        if v:
                            session.delete(v)
                    elif op in ("CREATE", "UPDATE"):
                        if v and getattr(v, "version", None) is not None and ver < v.version:
                            logger.info("Skipping stale pulled vehicle %s (current v%s >= incoming v%s)", eid, v.version, ver)
                            continue
                        now_iso = datetime.now(timezone.utc).isoformat()
                        if not v:
                            v = LocalVehicle(id=eid)
                            session.add(v)
                        v.registration = payload.get("registration", v.registration if hasattr(v, 'registration') else "")
                        v.vin = payload.get("vin", getattr(v, 'vin', None))
                        v.brand = payload.get("brand", getattr(v, 'brand', ""))
                        v.model = payload.get("model", getattr(v, 'model', ""))
                        v.year = payload.get("year", getattr(v, 'year', 2024))
                        v.color = payload.get("color", getattr(v, 'color', "Noir"))
                        v.fuel_type = payload.get("fuel_type", getattr(v, 'fuel_type', "GASOLINE"))
                        v.transmission = payload.get("transmission", getattr(v, 'transmission', "MANUAL"))
                        v.current_mileage = payload.get("current_mileage", getattr(v, 'current_mileage', 0))
                        v.purchase_mileage = payload.get("purchase_mileage", getattr(v, 'purchase_mileage', 0))
                        v.purchase_price = payload.get("purchase_price", getattr(v, 'purchase_price', 0.0))
                        v.daily_rental_price = payload.get("daily_rental_price", getattr(v, 'daily_rental_price', 0.0))
                        v.status = payload.get("status", getattr(v, 'status', "AVAILABLE"))
                        v.image_url = payload.get("image_url", getattr(v, 'image_url', None))
                        v.assurance_expiry = payload.get("assurance_expiry", getattr(v, 'assurance_expiry', None))
                        v.vignette_expiry = payload.get("vignette_expiry", getattr(v, 'vignette_expiry', None))
                        v.visite_technique_expiry = payload.get("visite_technique_expiry", getattr(v, 'visite_technique_expiry', None))
                        v.carte_grise_expiry = payload.get("carte_grise_expiry", getattr(v, 'carte_grise_expiry', None))
                        v.autres_label = payload.get("autres_label", getattr(v, 'autres_label', None))
                        v.autres_expiry = payload.get("autres_expiry", getattr(v, 'autres_expiry', None))
                        v.notes = payload.get("notes", getattr(v, 'notes', None))
                        v.version = ver
                        v.updated_at = now_iso
                        v_created = payload.get("created_at")
                        if v_created:
                            v.created_at = v_created
                        elif not getattr(v, 'created_at', None):
                            v.created_at = now_iso

                        # Sync local vehicle images
                        session.query(LocalVehicleImage).filter_by(vehicle_id=eid).delete()
                        raw_imgs = payload.get("images") or []
                        if not raw_imgs and v.image_url:
                            raw_imgs = [u.strip() for u in v.image_url.split(",") if u.strip()]
                        for idx, img in enumerate(raw_imgs):
                            img_url = img if isinstance(img, str) else img.get("image_url", "")
                            if img_url:
                                local_img = LocalVehicleImage(
                                    id=str(uuid.uuid4()),
                                    vehicle_id=eid,
                                    image_url=img_url,
                                    sort_order=idx
                                )
                                session.add(local_img)

                elif etype == "reservation":
                    r = session.query(LocalReservation).filter_by(id=eid).first()
                    if op == "DELETE":
                        if r:
                            session.delete(r)
                    elif op in ("CREATE", "UPDATE"):
                        if r and getattr(r, "version", None) is not None and ver < r.version:
                            logger.info("Skipping stale pulled reservation %s (current v%s >= incoming v%s)", eid, r.version, ver)
                            continue
                        now_iso = datetime.now(timezone.utc).isoformat()
                        if not r:
                            r = LocalReservation(id=eid)
                            session.add(r)
                        r.vehicle_id = payload.get("vehicle_id", getattr(r, 'vehicle_id', ""))
                        r.customer_id = payload.get("customer_id", getattr(r, 'customer_id', None))
                        r.customer_name = payload.get("customer_name", getattr(r, 'customer_name', ""))
                        r.customer_phone = payload.get("customer_phone", getattr(r, 'customer_phone', None))
                        r.customer_email = payload.get("customer_email", getattr(r, 'customer_email', None))
                        r.identity_card_image = payload.get("identity_card_image", getattr(r, 'identity_card_image', None))
                        r.driving_license_image = payload.get("driving_license_image", getattr(r, 'driving_license_image', None))
                        r.start_datetime = payload.get("start_datetime", getattr(r, 'start_datetime', now_iso))
                        r.end_datetime = payload.get("end_datetime", getattr(r, 'end_datetime', now_iso))
                        r.daily_price = payload.get("daily_price", getattr(r, 'daily_price', 0.0))
                        r.num_days = payload.get("num_days", getattr(r, 'num_days', 1))
                        r.total_price = payload.get("total_price", getattr(r, 'total_price', 0.0))
                        r.deposit = payload.get("deposit", getattr(r, 'deposit', 0.0))
                        r.status = payload.get("status", getattr(r, 'status', "RESERVED"))
                        r.cancellation_reason = payload.get("cancellation_reason", getattr(r, 'cancellation_reason', None))
                        r.cancelled_at = payload.get("cancelled_at", getattr(r, 'cancelled_at', None))
                        r.payment_status = payload.get("payment_status", getattr(r, 'payment_status', "PENDING"))
                        r.version = ver
                        r.updated_at = now_iso
                        r_created = payload.get("created_at")
                        if r_created:
                            r.created_at = r_created
                        elif not getattr(r, 'created_at', None):
                            r.created_at = now_iso
                elif etype == "client":
                    c = session.query(LocalClient).filter_by(id=eid).first()
                    if op == "DELETE":
                        if c:
                            session.delete(c)
                    elif op in ("CREATE", "UPDATE"):
                        if c and getattr(c, "version", None) is not None and ver < c.version:
                            logger.info("Skipping stale pulled client %s (current v%s >= incoming v%s)", eid, c.version, ver)
                            continue
                        now_iso = datetime.now(timezone.utc).isoformat()
                        if not c:
                            c = LocalClient(id=eid)
                            session.add(c)
                        c.first_name = payload.get("first_name", getattr(c, 'first_name', ""))
                        c.last_name = payload.get("last_name", getattr(c, 'last_name', ""))
                        c.phone = payload.get("phone", getattr(c, 'phone', None))
                        c.email = payload.get("email", getattr(c, 'email', None))
                        c.cin_number = payload.get("cin_number", getattr(c, 'cin_number', None))
                        c.license_number = payload.get("license_number", getattr(c, 'license_number', None))
                        c.photo_url = payload.get("photo_url", getattr(c, 'photo_url', None))
                        c.identity_card_image = payload.get("identity_card_image", getattr(c, 'identity_card_image', None))
                        c.identity_card_image_back = payload.get("identity_card_image_back", getattr(c, 'identity_card_image_back', None))
                        c.driving_license_image = payload.get("driving_license_image", getattr(c, 'driving_license_image', None))
                        c.driving_license_image_back = payload.get("driving_license_image_back", getattr(c, 'driving_license_image_back', None))
                        c.notes = payload.get("notes", getattr(c, 'notes', None))
                        c.status = payload.get("status", getattr(c, 'status', "ACTIVE"))
                        c.version = ver
                        c.updated_at = now_iso
                        c_created = payload.get("created_at")
                        if c_created:
                            c.created_at = c_created
                        elif not getattr(c, 'created_at', None):
                            c.created_at = now_iso

                elif etype == "maintenance":
                    from app.models.maintenance import LocalMaintenancePart
                    m = session.query(LocalMaintenance).filter_by(id=eid).first()
                    if op == "DELETE":
                        if m:
                            session.delete(m)
                    elif op in ("CREATE", "UPDATE"):
                        if m and getattr(m, "version", None) is not None and ver < m.version:
                            logger.info("Skipping stale pulled maintenance %s (current v%s >= incoming v%s)", eid, m.version, ver)
                            continue
                        now_iso = datetime.now(timezone.utc).isoformat()
                        if not m:
                            m = LocalMaintenance(id=eid)
                            session.add(m)

                        m.vehicle_id = payload.get("vehicle_id", getattr(m, 'vehicle_id', ""))
                        m.type = payload.get("type", getattr(m, 'type', "Entretien"))
                        m.title = payload.get("title", getattr(m, 'title', None))
                        m.description = payload.get("description", getattr(m, 'description', None))
                        m.diagnosis = payload.get("diagnosis", getattr(m, 'diagnosis', None))
                        m.repair_description = payload.get("repair_description", getattr(m, 'repair_description', None))

                        m.start_datetime = payload.get("start_datetime", getattr(m, 'start_datetime', now_iso))
                        m.expected_end_datetime = payload.get("expected_end_datetime", getattr(m, 'expected_end_datetime', None))
                        m.actual_end_datetime = payload.get("actual_end_datetime", getattr(m, 'actual_end_datetime', None))

                        m.mileage = payload.get("mileage", getattr(m, 'mileage', None))
                        m.location = payload.get("location", getattr(m, 'location', None))
                        m.technician_name = payload.get("technician_name", getattr(m, 'technician_name', None))
                        m.invoice_number = payload.get("invoice_number", getattr(m, 'invoice_number', None))

                        m.oil_brand = payload.get("oil_brand", getattr(m, 'oil_brand', None))
                        m.oil_viscosity = payload.get("oil_viscosity", getattr(m, 'oil_viscosity', None))
                        m.oil_quantity = payload.get("oil_quantity", getattr(m, 'oil_quantity', None))
                        m.oil_filter_changed = payload.get("oil_filter_changed", getattr(m, 'oil_filter_changed', False))
                        m.air_filter_changed = payload.get("air_filter_changed", getattr(m, 'air_filter_changed', False))
                        m.fuel_filter_changed = payload.get("fuel_filter_changed", getattr(m, 'fuel_filter_changed', False))
                        m.cabin_filter_changed = payload.get("cabin_filter_changed", getattr(m, 'cabin_filter_changed', False))

                        m.estimated_cost = payload.get("estimated_cost", getattr(m, 'estimated_cost', 0.0))
                        m.parts_cost = payload.get("parts_cost", getattr(m, 'parts_cost', 0.0))
                        m.labor_cost = payload.get("labor_cost", getattr(m, 'labor_cost', 0.0))
                        m.other_cost = payload.get("other_cost", getattr(m, 'other_cost', 0.0))
                        m.actual_cost = payload.get("actual_cost", getattr(m, 'actual_cost', None))

                        m.next_maintenance_date = payload.get("next_maintenance_date", getattr(m, 'next_maintenance_date', None))
                        m.next_maintenance_mileage = payload.get("next_maintenance_mileage", getattr(m, 'next_maintenance_mileage', None))

                        m.step = payload.get("step", getattr(m, 'step', "EN ATTENTE"))
                        m.status = payload.get("status", getattr(m, 'status', "ACTIVE"))
                        m.notes = payload.get("notes", getattr(m, 'notes', None))

                        m.version = ver
                        m.updated_at = now_iso
                        m_created = payload.get("created_at")
                        if m_created:
                            m.created_at = m_created
                        elif not getattr(m, 'created_at', None):
                            m.created_at = now_iso

                        # Sync parts
                        session.query(LocalMaintenancePart).filter_by(maintenance_id=eid).delete()
                        raw_parts = payload.get("parts", [])
                        for pt in raw_parts:
                            local_part = LocalMaintenancePart(
                                id=str(pt.get("id", uuid.uuid4())),
                                maintenance_id=eid,
                                part_name=pt.get("part_name", ""),
                                quantity=pt.get("quantity", 1.0),
                                unit_price=pt.get("unit_price", 0.0),
                                total_price=pt.get("total_price", 0.0),
                                notes=pt.get("notes", None),
                                created_at=now_iso,
                                updated_at=now_iso
                            )
                            session.add(local_part)

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("Failed to merge pulled items into SQLite: %s", e)
            return False
        finally:
            session.close()

    async def push(self) -> dict:
        """Alias for push_changes."""
        return await self.push_changes()

    async def pull(self) -> dict:
        """Alias for pull_changes."""
        return await self.pull_changes()

    async def process_pending_uploads(self) -> dict:
        """Upload offline-created images/documents once connectivity returns.

        Called at the start of each successful sync cycle. Uses the same
        authenticated API client flow (with token refresh) as push/pull.
        """
        if not self._access_token:
            return {"status": "offline", "message": "Not authenticated"}
        try:
            result = await self._upload_processor.process_due()
            self._is_online = True
            return {"status": "ok", **result}
        except Exception as e:
            logger.error("Pending upload processing failed: %s", e)
            return {"status": "error", "message": str(e)}

    async def bootstrap(self) -> dict:
        """Atomic full synchronization from /api/v1/sync/bootstrap.

        Reconciles the local SQLite cache against the authoritative PostgreSQL
        snapshot — upserting fresh rows and PURGING rows the server no longer
        has. Because it deletes, a partial/degraded server response (HTTP 200
        but truncated body) could wipe good local data — so it is guarded:
        a snapshot whose ``revision`` did not advance and that is emptier than
        the current cache is rejected without touching a single row.
        """
        if not self._access_token:
            return {"status": "offline", "message": "Not authenticated"}

        try:
            headers = {"Authorization": f"Bearer {self._access_token}"}
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self._base_url}/api/{API_VERSION}/sync/bootstrap",
                    headers=headers
                )
                if resp.status_code != 200:
                    return {"status": "error", "message": f"Server error: {resp.status_code}"}
                data = resp.json()

            session = get_local_session()
            try:
                from app.models.sync_queue import SyncQueueItem
                from app.models.vehicle import LocalVehicle
                from app.models.reservation import LocalReservation
                from app.models.maintenance import LocalMaintenance, LocalMaintenancePart
                from app.models.client import LocalClient

                server_vehicles = data.get("vehicles", []) or []
                server_clients = data.get("clients", []) or []
                server_rentals = data.get("rentals", []) or data.get("reservations", []) or []
                server_maint = data.get("maintenance", []) or []
                server_total = (len(server_vehicles) + len(server_clients)
                                + len(server_rentals) + len(server_maint))
                local_total = (
                    session.query(LocalVehicle).count()
                    + session.query(LocalClient).count()
                    + session.query(LocalReservation).count()
                    + session.query(LocalMaintenance).count()
                )
                p_rows = session.query(SyncQueueItem.entity_id).filter(
                    SyncQueueItem.sync_status == "PENDING"
                ).all()
                pending_ids = {str(r[0]) for r in p_rows if r[0]}
                has_pending = bool(pending_ids)

                incoming_rev = int(data.get("revision") or 0)
                # Completeness guard: reject if snapshot is completely empty while local has rows,
                # or if snapshot is suspiciously smaller while local has pending unsynced changes.
                if (local_total > 0 and server_total == 0) or (
                    has_pending and local_total > 5 and server_total * 2 < local_total and incoming_rev <= (self._bootstrap_revision or 0)
                ):
                    logger.warning(
                        "bootstrap: rejecting suspect snapshot (server=%d local=%d rev=%d<=%s pending=%s) — no rows touched",
                        server_total, local_total, incoming_rev, self._bootstrap_revision, has_pending,
                    )
                    return {"status": "rejected", "message": "suspect/partial server snapshot"}
                self._bootstrap_revision = max(self._bootstrap_revision or 0, incoming_rev)

                now_iso = datetime.now(timezone.utc).isoformat()

                # 1. Reconcile VEHICLES
                server_vehicles = data.get("vehicles", [])
                server_v_ids = {str(v.get("id")) for v in server_vehicles}
                for lv in session.query(LocalVehicle).all():
                    if str(lv.id) not in server_v_ids and str(lv.id) not in pending_ids:
                        session.delete(lv)

                for v_dto in server_vehicles:
                    vid = str(v_dto.get("id"))
                    if vid in pending_ids:
                        continue
                    v = session.query(LocalVehicle).filter_by(id=vid).first()
                    if not v:
                        v = LocalVehicle(id=vid)
                        session.add(v)
                    v.registration = v_dto.get("registration", "")
                    v.vin = v_dto.get("vin")
                    v.brand = v_dto.get("brand", "")
                    v.model = v_dto.get("model", "")
                    v.year = v_dto.get("year", 2024)
                    v.color = v_dto.get("color", "Noir")
                    v.fuel_type = v_dto.get("fuel_type", "DIESEL")
                    v.transmission = v_dto.get("transmission", "MANUAL")
                    v.current_mileage = v_dto.get("current_mileage", 0)
                    v.purchase_mileage = v_dto.get("purchase_mileage", 0)
                    v.purchase_price = float(v_dto.get("purchase_price", 0.0) or 0.0)
                    v.daily_rental_price = float(v_dto.get("daily_rental_price", 0.0) or 0.0)
                    v.status = v_dto.get("status", "AVAILABLE")
                    v.image_url = v_dto.get("image_url")
                    v.version = v_dto.get("version", 1)
                    v.updated_at = now_iso
                    if not getattr(v, "created_at", None):
                        v.created_at = v_dto.get("created_at") or now_iso

                # 2. Reconcile CLIENTS
                server_clients = data.get("clients", [])
                server_c_ids = {str(c.get("id")) for c in server_clients}
                for lc in session.query(LocalClient).all():
                    if str(lc.id) not in server_c_ids and str(lc.id) not in pending_ids:
                        session.delete(lc)

                for c_dto in server_clients:
                    cid = str(c_dto.get("id"))
                    if cid in pending_ids:
                        continue
                    c = session.query(LocalClient).filter_by(id=cid).first()
                    if not c:
                        c = LocalClient(id=cid)
                        session.add(c)
                    c.first_name = c_dto.get("first_name", "")
                    c.last_name = c_dto.get("last_name", "")
                    c.phone = c_dto.get("phone")
                    c.email = c_dto.get("email")
                    c.cin_number = c_dto.get("cin_number")
                    c.license_number = c_dto.get("license_number")
                    c.photo_url = c_dto.get("photo_url")
                    c.identity_card_image = c_dto.get("identity_card_image")
                    c.identity_card_image_back = c_dto.get("identity_card_image_back")
                    c.driving_license_image = c_dto.get("driving_license_image")
                    c.driving_license_image_back = c_dto.get("driving_license_image_back")
                    c.notes = c_dto.get("notes")
                    c.status = c_dto.get("status", "ACTIVE")
                    c.version = c_dto.get("version", 1)
                    c.updated_at = now_iso
                    if not getattr(c, "created_at", None):
                        c.created_at = c_dto.get("created_at") or now_iso

                # 3. Reconcile RESERVATIONS
                server_rentals = data.get("rentals", []) or data.get("reservations", [])
                server_r_ids = {str(r.get("id")) for r in server_rentals}
                for lr in session.query(LocalReservation).all():
                    if str(lr.id) not in server_r_ids and str(lr.id) not in pending_ids:
                        session.delete(lr)

                for r_dto in server_rentals:
                    rid = str(r_dto.get("id"))
                    if rid in pending_ids:
                        continue
                    r = session.query(LocalReservation).filter_by(id=rid).first()
                    if not r:
                        r = LocalReservation(id=rid)
                        session.add(r)
                    r.vehicle_id = str(r_dto.get("vehicle_id", ""))
                    r.customer_id = str(r_dto.get("customer_id")) if r_dto.get("customer_id") else None
                    r.customer_name = r_dto.get("customer_name")
                    r.customer_phone = r_dto.get("customer_phone")
                    r.customer_email = r_dto.get("customer_email")
                    r.identity_card_image = r_dto.get("identity_card_image")
                    r.driving_license_image = r_dto.get("driving_license_image")
                    r.start_datetime = str(r_dto.get("start_datetime", ""))
                    r.end_datetime = str(r_dto.get("end_datetime", ""))
                    r.daily_price = float(r_dto.get("daily_price", 0.0) or 0.0)
                    r.num_days = int(r_dto.get("num_days", 1) or 1)
                    r.total_price = float(r_dto.get("total_price", 0.0) or 0.0)
                    r.deposit = float(r_dto.get("deposit", 0.0) or 0.0)
                    r.status = r_dto.get("status", "RESERVED")
                    r.cancellation_reason = r_dto.get("cancellation_reason")
                    r.cancelled_at = r_dto.get("cancelled_at")
                    r.payment_status = r_dto.get("payment_status", "PENDING")
                    r.notes = r_dto.get("notes")
                    r.version = r_dto.get("version", 1)
                    r.updated_at = now_iso
                    if not getattr(r, "created_at", None):
                        r.created_at = r_dto.get("created_at") or now_iso

                # 4. Reconcile MAINTENANCE
                server_maint = data.get("maintenance", [])
                server_m_ids = {str(m.get("id")) for m in server_maint}
                for lm in session.query(LocalMaintenance).all():
                    if str(lm.id) not in server_m_ids and str(lm.id) not in pending_ids:
                        session.query(LocalMaintenancePart).filter_by(maintenance_id=lm.id).delete()
                        session.delete(lm)

                for m_dto in server_maint:
                    mid = str(m_dto.get("id"))
                    if mid in pending_ids:
                        continue
                    m = session.query(LocalMaintenance).filter_by(id=mid).first()
                    if not m:
                        m = LocalMaintenance(id=mid)
                        session.add(m)
                    m.vehicle_id = str(m_dto.get("vehicle_id", ""))
                    m.type = m_dto.get("type", "Entretien")
                    m.title = m_dto.get("title")
                    m.description = m_dto.get("description")
                    m.diagnosis = m_dto.get("diagnosis")
                    m.repair_description = m_dto.get("repair_description")
                    m.start_datetime = str(m_dto.get("start_datetime", ""))
                    m.expected_end_datetime = str(m_dto.get("expected_end_datetime")) if m_dto.get("expected_end_datetime") else None
                    m.actual_end_datetime = str(m_dto.get("actual_end_datetime")) if m_dto.get("actual_end_datetime") else None
                    m.mileage = float(m_dto.get("mileage") or 0.0) if m_dto.get("mileage") is not None else None
                    m.location = m_dto.get("location")
                    m.technician_name = m_dto.get("technician_name")
                    m.invoice_number = m_dto.get("invoice_number")
                    m.oil_brand = m_dto.get("oil_brand")
                    m.oil_viscosity = m_dto.get("oil_viscosity")
                    m.oil_quantity = float(m_dto.get("oil_quantity") or 0.0) if m_dto.get("oil_quantity") is not None else None
                    m.oil_filter_changed = bool(m_dto.get("oil_filter_changed", False))
                    m.air_filter_changed = bool(m_dto.get("air_filter_changed", False))
                    m.fuel_filter_changed = bool(m_dto.get("fuel_filter_changed", False))
                    m.cabin_filter_changed = bool(m_dto.get("cabin_filter_changed", False))
                    m.estimated_cost = float(m_dto.get("estimated_cost") or 0.0) if m_dto.get("estimated_cost") is not None else None
                    m.parts_cost = float(m_dto.get("parts_cost", 0.0) or 0.0)
                    m.labor_cost = float(m_dto.get("labor_cost", 0.0) or 0.0)
                    m.other_cost = float(m_dto.get("other_cost", 0.0) or 0.0)
                    m.actual_cost = float(m_dto.get("actual_cost") or 0.0) if m_dto.get("actual_cost") is not None else None
                    m.next_maintenance_date = str(m_dto.get("next_maintenance_date")) if m_dto.get("next_maintenance_date") else None
                    m.next_maintenance_mileage = float(m_dto.get("next_maintenance_mileage") or 0.0) if m_dto.get("next_maintenance_mileage") is not None else None
                    m.step = m_dto.get("step", "EN ATTENTE")
                    m.status = m_dto.get("status", "ACTIVE")
                    m.notes = m_dto.get("notes")
                    m.version = m_dto.get("version", 1)
                    m.updated_at = now_iso
                    if not getattr(m, "created_at", None):
                        m.created_at = m_dto.get("created_at") or now_iso

                # 5. Purge any orphaned local records referencing non-existent vehicles
                known_v_ids = {str(v.id) for v in session.query(LocalVehicle.id).all()}
                for lr in session.query(LocalReservation).all():
                    if str(lr.vehicle_id) not in known_v_ids and str(lr.id) not in pending_ids:
                        logger.warning("Bootstrap: purging orphaned reservation %s with non-existent vehicle %s", lr.id, lr.vehicle_id)
                        session.delete(lr)
                for lm in session.query(LocalMaintenance).all():
                    if str(lm.vehicle_id) not in known_v_ids and str(lm.id) not in pending_ids:
                        logger.warning("Bootstrap: purging orphaned maintenance %s with non-existent vehicle %s", lm.id, lm.vehicle_id)
                        session.query(LocalMaintenancePart).filter_by(maintenance_id=lm.id).delete()
                        session.delete(lm)

                session.commit()
                self._is_online = True
                return {"status": "ok", "bootstrap": True}
            except Exception as e:
                session.rollback()
                logger.error("Failed to apply bootstrap into SQLite: %s", e)
                return {"status": "error", "message": str(e)}
            finally:
                session.close()
        except Exception as e:
            logger.error("Bootstrap execution failed: %s", e)
            return {"status": "error", "message": str(e)}

    async def sync(self) -> dict:
        """Full sync cycle: uploads, then push, then pull."""
        upload_result = await self.process_pending_uploads()
        push_result = await self.push_changes()
        pull_result = await self.pull_changes()
        return {
            "uploads": upload_result,
            "push": push_result,
            "pull": pull_result,
            "is_online": self._is_online,
        }
