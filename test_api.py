import urllib.request
import json
import sys

URL_BASE = "https://car-rental-system.fly.dev/api/v1"

# 1. Login
data = json.dumps({'email': 'BERLINCAR@GMAIL.COM', 'password': 'Berlin20002000'}).encode('utf-8')
req = urllib.request.Request(f"{URL_BASE}/auth/login", data=data, headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req) as response:
        login_res = json.loads(response.read().decode())
        token = login_res.get('access_token')
except urllib.error.HTTPError as e:
    print(f"Login failed: HTTP Error {e.code}: {e.read().decode()}")
    sys.exit(1)

# 2. Endpoints
headers = {"Authorization": f"Bearer {token}"}
endpoints = [
    "/vehicles",
    "/rentals",
    "/maintenance",
    "/notifications",
    "/dashboard/stats"
]

for ep in endpoints:
    req = urllib.request.Request(f"{URL_BASE}{ep}", headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            data = res.read().decode()
            if len(data) >= 0:
                print(f"PASS: {ep} (HTTP {res.status})")
    except urllib.error.HTTPError as e:
        print(f"FAIL: {ep} Exception: {e.code} {e.read().decode()}")

