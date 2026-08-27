from datetime import datetime
try:
    dt = datetime.fromisoformat("2026-08-20T09:00:00 00:00")
    print("Parsed!", repr(dt))
except Exception as e:
    print("Error:", e)
