"""
Canonical datetime handling for the desktop application.

ONE parser for the entire codebase:

    parse_datetime_utc(value) -> datetime|None

Policy (deterministic):
- Accepts ISO-8601 strings ("Z", explicit offsets, naive legacy values),
  datetime objects, and SQLite "YYYY-MM-DD HH:MM:SS" timestamps.
- Naive values are interpreted as BUSINESS-LOCAL wall time (Africa/Casablanca),
  exactly as shared.money_time.to_business — ONE naive-datetime policy across
  backend, shared and desktop (v1.1.0 audit P2-4 unification). The server
  serializes tz-aware ISO off TIMESTAMPTZ, so a naive value here only ever comes
  from a legacy row / SQLite round-trip, which is business-local wall time.
- Output is ALWAYS timezone-aware UTC.
- Invalid input -> None (never raises).

Business rule: datetime comparisons must NEVER be performed on strings.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_BUSINESS_TZ = ZoneInfo("Africa/Casablanca")

import logging

logger = logging.getLogger(__name__)

BLOCKING_RESERVATION_STATUSES = ("RESERVED", "ACTIVE")
NON_BLOCKING_RESERVATION_STATUSES = ("CANCELLED", "COMPLETED")


def parse_datetime_utc(value):
    """Normalize any datetime/ISO-string representation to aware UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_BUSINESS_TZ).astimezone(timezone.utc)
        return value.astimezone(timezone.utc)
    try:
        s = str(value).strip().replace("Z", "+00:00").replace("z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_BUSINESS_TZ)   # unified: naive == business-local
        return dt.astimezone(timezone.utc)
    except Exception as e:
        logger.warning("parse_datetime_utc invalid format %r: %s", value, e)
        return None


def reservations_overlap(start_a, end_a, start_b, end_b) -> bool:
    """Canonical interval predicate (adjacent intervals do NOT overlap).

    start_A < end_B AND end_A > start_B
    """
    if not all((start_a, end_a, start_b, end_b)):
        return False
    return start_a < end_b and end_a > start_b


def status_blocks_reservation(status) -> bool:
    """Normalize status: RESERVED/ACTIVE block; CANCELLED/COMPLETED do not."""
    return (status or "").upper() in BLOCKING_RESERVATION_STATUSES
