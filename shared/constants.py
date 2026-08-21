"""
Shared constants used across backend and desktop.
"""

# Sync
MAX_SYNC_RETRY = 5
SYNC_BATCH_SIZE = 50
SYNC_INTERVAL_SECONDS = 30

# Pagination
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

# File upload
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

# Vehicle
MIN_VEHICLE_YEAR = 1990
MAX_VEHICLE_YEAR = 2030

# QR Code prefix
QR_PREFIX = "CAR-"
