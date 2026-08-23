"""
Pending upload processor — uploads offline-created images/documents through
the authenticated API once connectivity returns.

Design rules:
- Files are stored locally (DATA_DIR/pending_uploads) with a durable
  LocalPendingUpload record; the entity keeps a "pending_uploads/<file>"
  marker until the server confirms success.
- The local file is NEVER removed before the upload is confirmed by the
  server. After confirmation the copy is archived to pending_uploads/uploaded.
- Temporary errors (network, 5xx, auth refreshable) are retried with
  exponential backoff; permanent validation errors (4xx) stop retrying.
- Idempotency: the marker doubles as the idempotency key — one record per
  unique marker, so restarts/reconnects/duplicate sync cycles never create
  duplicate queue entries for the same logical upload.
"""
import logging
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.config import DATA_DIR
from app.database import get_local_session
from app.models.pending_upload import LocalPendingUpload
from app.models.vehicle import LocalVehicle
from app.models.vehicle_image import LocalVehicleImage
from app.models.reservation import LocalReservation
from app.models.client import LocalClient

logger = logging.getLogger(__name__)

PENDING_DIR = Path(DATA_DIR) / "pending_uploads"
ARCHIVE_DIR = PENDING_DIR / "uploaded"

# HTTP status codes that will never succeed on retry.
PERMANENT_ERROR_CODES = {400, 404, 413, 415, 422}
# Backoff: 60s * 2^retry capped at 1 hour.
BACKOFF_BASE_SECONDS = 60
BACKOFF_CAP_SECONDS = 3600


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_pending_file(source_path: str) -> Path:
    """Copy a user-selected file into the durable pending_uploads directory."""
    src = Path(source_path)
    dest = PENDING_DIR / f"{uuid.uuid4().hex}{src.suffix.lower()}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dest))
    return dest


def enqueue_pending_upload(
    session: Session,
    entity_type: str,
    entity_id: str,
    upload_type: str,
    remote_endpoint: str,
    local_path: str,
    field_name: str = None,
    marker: str = None,
) -> LocalPendingUpload:
    """Create (or return the existing) durable pending-upload record.

    Idempotent on `marker`: restarts/reconnects/duplicate sync cycles never
    create duplicate queue entries for the same logical upload.
    """
    if marker:
        existing = session.query(LocalPendingUpload).filter_by(marker=marker).first()
        if existing:
            # Opportunistically attach entity identity if it was unknown before.
            if existing.entity_id != entity_id and entity_id:
                existing.entity_id = entity_id
                existing.updated_at = _now_iso()
                session.commit()
            return existing
        stored_path = PENDING_DIR / Path(marker).name
        if not stored_path.exists():
            stored_path = Path(local_path)
        local_path = str(stored_path)
    else:
        stored = store_pending_file(local_path)
        marker = f"pending_uploads/{stored.name}"
        local_path = str(stored)

    record = LocalPendingUpload(
        id=str(uuid.uuid4()),
        marker=marker,
        entity_type=entity_type,
        entity_id=entity_id,
        upload_type=upload_type,
        field_name=field_name,
        local_path=local_path,
        remote_endpoint=remote_endpoint,
        status="PENDING",
        retry_count=0,
        max_retries=8,
        next_attempt_at=None,
        error_message=None,
        created_at=_now_iso(),
    )
    session.add(record)
    session.commit()
    logger.info("Queued pending upload %s (%s -> %s)", marker, upload_type, remote_endpoint)
    return record


def register_pending_upload(
    session: Session,
    marker: str,
    entity_type: str,
    entity_id: str,
    upload_type: str,
    remote_endpoint: str,
    field_name: str = None,
):
    """Attach a durable pending-upload record to an already-stored marker file.

    Called at entity-save time when the final entity id is known.
    No-op when the marker is not a pending_uploads placeholder.
    """
    if not marker or not str(marker).startswith("pending_uploads/"):
        return None
    return enqueue_pending_upload(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        upload_type=upload_type,
        remote_endpoint=remote_endpoint,
        local_path="",
        field_name=field_name,
        marker=marker,
    )


class PendingUploadProcessor:
    """Uploads queued files via the authenticated API and reconciles URLs."""

    def __init__(self, engine):
        # engine: SyncEngine instance (provides tokens, base URL, refresh).
        self._engine = engine

    async def process_due(self, limit: int = 20) -> dict:
        """Process all due pending uploads. Returns a summary dict."""
        session: Session = get_local_session()
        try:
            now_iso = _now_iso()
            due = (
                session.query(LocalPendingUpload)
                .filter(LocalPendingUpload.status.in_(["PENDING", "FAILED"]))
                .filter(LocalPendingUpload.retry_count < LocalPendingUpload.max_retries)
                .order_by(LocalPendingUpload.created_at)
                .limit(limit)
                .all()
            )
            uploaded, failed, skipped = 0, 0, 0
            for record in due:
                if record.next_attempt_at and record.next_attempt_at > now_iso:
                    skipped += 1
                    continue
                result = await self._process_one(session, record)
                if result:
                    uploaded += 1
                else:
                    failed += 1
            return {"uploaded": uploaded, "failed": failed, "skipped": skipped,
                    "remaining": self.pending_count(session)}
        finally:
            session.close()

    @staticmethod
    def pending_count(session: Session) -> int:
        return (
            session.query(LocalPendingUpload)
            .filter(LocalPendingUpload.status.in_(["PENDING", "FAILED"]))
            .filter(LocalPendingUpload.retry_count < LocalPendingUpload.max_retries)
            .count()
        )

    async def _upload_file(self, record: LocalPendingUpload):
        """Perform one authenticated multipart upload attempt.

        Returns (remote_url, None) on success or (None, error_message).
        """
        headers = {"Authorization": f"Bearer {self._engine._access_token}"}
        file_path = Path(record.local_path)

        for attempt in range(2):  # one retry after token refresh on 401
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    with open(file_path, "rb") as fh:
                        response = await client.post(
                            f"{self._engine._base_url}{record.remote_endpoint}",
                            files={"file": (file_path.name, fh)},
                            headers=headers,
                        )
                if response.status_code == 200:
                    data = response.json()
                    url = data.get("image_url") or data.get("document_url") or data.get("url")
                    if not url:
                        return None, "Server response missing image_url"
                    return url, None
                if response.status_code == 401 and attempt == 0 and self._engine._refresh_token:
                    refreshed = await self._engine._do_refresh()
                    if refreshed:
                        headers = {
                            "Authorization": f"Bearer {self._engine._access_token}"
                        }
                        continue
                    return None, "Authentication failed (refresh rejected)"
                if response.status_code in PERMANENT_ERROR_CODES:
                    detail = ""
                    try:
                        detail = response.json().get("detail", "")
                    except Exception:
                        pass
                    return None, f"PERMANENT:{response.status_code} {detail}".strip()
                return None, f"Temporary server error: HTTP {response.status_code}"
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                return None, f"Network error: {e}"
            except Exception as e:
                return None, f"Upload error: {e}"
        return None, "Authentication failed"

    async def _process_one(self, session: Session, record: LocalPendingUpload) -> bool:
        """Process a single pending-upload record. Returns True on success."""
        file_path = Path(record.local_path)

        if not file_path.exists():
            record.status = "PERMANENT_FAILED"
            record.error_message = f"Local file missing: {record.local_path}"
            record.updated_at = _now_iso()
            session.commit()
            logger.error("Pending upload %s failed permanently: file missing", record.marker)
            return False

        remote_url, error = await self._upload_file(record)

        if remote_url:
            replace_marker_in_entities(session, record.marker, remote_url)
            record.status = "SYNCED"
            record.error_message = None
            record.completed_at = _now_iso()
            record.updated_at = record.completed_at
            session.commit()
            self._archive_local_copy(file_path)
            logger.info("Pending upload %s completed -> %s", record.marker, remote_url)
            return True

        record.updated_at = _now_iso()
        record.error_message = error
        if error and error.startswith("PERMANENT:"):
            record.status = "PERMANENT_FAILED"
            session.commit()
            logger.error(
                "Pending upload %s permanent failure: %s (file kept for inspection)",
                record.marker, error,
            )
        else:
            record.status = "FAILED"
            record.retry_count += 1
            backoff = min(BACKOFF_BASE_SECONDS * (2 ** record.retry_count), BACKOFF_CAP_SECONDS)
            record.next_attempt_at = (
                datetime.now(timezone.utc) + timedelta(seconds=backoff)
            ).isoformat()
            session.commit()
            logger.warning(
                "Pending upload %s temporary failure (%s); retry %d in %ss",
                record.marker, error, record.retry_count, backoff,
            )
        return False

    @staticmethod
    def _archive_local_copy(file_path: Path):
        """Archive (never delete before success) the confirmed-uploaded file."""
        try:
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            dest = ARCHIVE_DIR / file_path.name
            if dest.exists():
                dest.unlink()
            shutil.move(str(file_path), str(dest))
        except Exception as e:
            logger.debug("Could not archive uploaded file %s: %s", file_path, e)


def replace_marker_in_entities(session: Session, marker: str, remote_url: str):
    """Replace a pending_uploads marker with the confirmed remote URL in all
    local entities that may reference it (vehicles, reservations, clients)."""
    try:
        # Vehicles: comma-separated image_url column
        vehicles = session.query(LocalVehicle).filter(
            LocalVehicle.image_url.like(f"%{marker}%")
        ).all()
        for v in vehicles:
            parts = [p.strip() for p in (v.image_url or "").split(",") if p.strip()]
            v.image_url = ",".join(remote_url if p == marker else p for p in parts)

        # Vehicles: normalized image rows
        images = session.query(LocalVehicleImage).filter_by(image_url=marker).all()
        for img in images:
            img.image_url = remote_url

        # Reservations: identity card / driving license documents
        reservations = session.query(LocalReservation).filter(
            (LocalReservation.identity_card_image == marker)
            | (LocalReservation.driving_license_image == marker)
        ).all()
        for r in reservations:
            if r.identity_card_image == marker:
                r.identity_card_image = remote_url
            if r.driving_license_image == marker:
                r.driving_license_image = remote_url

        # Clients: photo + documents
        clients = session.query(LocalClient).filter(
            (LocalClient.photo_url == marker)
            | (LocalClient.identity_card_image == marker)
            | (LocalClient.driving_license_image == marker)
        ).all()
        for c in clients:
            if getattr(c, "photo_url", None) == marker:
                c.photo_url = remote_url
            if getattr(c, "identity_card_image", None) == marker:
                c.identity_card_image = remote_url
            if getattr(c, "driving_license_image", None) == marker:
                c.driving_license_image = remote_url

        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("Failed to reconcile marker %s -> %s: %s", marker, remote_url, e)
