from datetime import datetime, timezone
import sys
sys.path.insert(0, "./desktop")
from app.utils.datetime_utils import parse_datetime_utc

data = {
    "start_datetime": "2026-08-20T09:00:00+00:00",
    "end_datetime": "2026-08-25T09:00:00+00:00"
}

new_start = parse_datetime_utc(data["start_datetime"])
new_end = parse_datetime_utc(data["end_datetime"])

print(f"new_start: {new_start.isoformat()}")
print(f"new_end: {new_end.isoformat()}")

from urllib.parse import urlencode
query = urlencode({"start": new_start.isoformat(), "end": new_end.isoformat()})
print(f"query: {query}")
