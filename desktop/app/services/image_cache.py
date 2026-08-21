import logging
import os
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

logger = logging.getLogger(__name__)


class ImageCache(QObject):
    """Asynchronously loads and caches images via HTTP or local filesystem for the UI."""
    # Signal emitted when an image is successfully loaded: (url, QPixmap)
    image_loaded = Signal(str, QPixmap)

    def __init__(self, base_url: str, parent=None):
        super().__init__(parent)
        self._base_url = base_url.rstrip("/")
        self._manager = QNetworkAccessManager(self)
        self._manager.finished.connect(self._on_request_finished)
        self._cache = {}  # url -> QPixmap
        self._pending = set()  # urls currently being fetched

    def get_image(self, img_path: str, vehicle_id: str = None):
        """Request an image. If cached or found locally on disk, it emits immediately. Otherwise fetches async."""
        if not img_path:
            return

        url = self._build_url(img_path)
        cache_key = f"{vehicle_id}_{url}" if vehicle_id else url

        if cache_key in self._cache:
            self.image_loaded.emit(cache_key, self._cache[cache_key])
            return

        # 1. Check local disk storage first (fast offline resolution)
        clean_rel = img_path.replace("/static/uploads/vehicles/", "").replace("/static/uploads/", "").lstrip("/")
        from app.config import DATA_DIR
        candidate_paths = [
            DATA_DIR / clean_rel,
            Path("/home/ayman/car-rental-system/backend/uploads/vehicles") / clean_rel,
            Path("/home/ayman/car-rental-system/backend/uploads") / clean_rel,
            Path(img_path),
            Path(os.getcwd()) / "uploads" / "vehicles" / clean_rel,
        ]
        for p in candidate_paths:
            if p.is_file():
                pix = QPixmap(str(p))
                if not pix.isNull():
                    self._cache[cache_key] = pix
                    self.image_loaded.emit(cache_key, pix)
                    return

        if cache_key in self._pending:
            return

        self._pending.add(cache_key)

        request = QNetworkRequest(QUrl(url))
        # Store cache_key dynamically in the request object so we can use it on response
        request.setAttribute(QNetworkRequest.Attribute.User, cache_key)
        self._manager.get(request)

    def _build_url(self, img_path: str) -> str:
        if not img_path.startswith("http"):
            if not img_path.startswith("/"):
                img_path = "/" + img_path
            return f"{self._base_url}{img_path}"
        return img_path

    def _on_request_finished(self, reply: QNetworkReply):
        cache_key = reply.request().attribute(QNetworkRequest.Attribute.User)
        if not cache_key:
            cache_key = reply.url().toString()

        if cache_key in self._pending:
            self._pending.remove(cache_key)

        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            pixmap = QPixmap()
            if pixmap.loadFromData(data) and not pixmap.isNull():
                self._cache[cache_key] = pixmap
                self.image_loaded.emit(cache_key, pixmap)
            else:
                logger.warning(f"Failed to decode image data for {cache_key}")
        else:
            logger.debug(f"Image fetch note for {cache_key}: {reply.errorString()}")

        reply.deleteLater()

    def invalidate(self, img_path: str):
        """Remove an image from the cache (e.g. after update)."""
        url = self._build_url(img_path)
        if url in self._cache:
            del self._cache[url]


_global_image_cache = None


def get_image_cache():
    global _global_image_cache
    if _global_image_cache is None:
        from app.config import API_BASE_URL
        _global_image_cache = ImageCache(API_BASE_URL)
    return _global_image_cache
