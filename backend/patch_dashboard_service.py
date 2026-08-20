import re

with open("app/services/dashboard_service.py", "r") as f:
    content = f.read()

# Add ZoneInfo import
if "from zoneinfo import ZoneInfo" not in content:
    content = content.replace("from datetime import datetime, timedelta, timezone", "from datetime import datetime, timedelta, timezone\nfrom zoneinfo import ZoneInfo")

# Replace now = datetime.now(timezone.utc)
content = re.sub(
    r"now = datetime\.now\(timezone\.utc\)",
    "now = datetime.now(ZoneInfo('Africa/Casablanca'))",
    content
)

with open("app/services/dashboard_service.py", "w") as f:
    f.write(content)
