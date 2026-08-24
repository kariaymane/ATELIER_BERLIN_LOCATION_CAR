"""
API client — synchronous HTTP client for the FastAPI backend.
Thread-safe, handles auth token refresh, used from Qt main thread.
"""
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ApiClient:
    """Synchronous HTTP client for backend communication."""

    def __init__(self, base_url: str, timeout: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._is_online = False

    @property
    def is_online(self) -> bool:
        return self._is_online

    def set_tokens(self, access: str, refresh: str):
        self._access_token = access
        self._refresh_token = refresh

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._access_token:
            h["Authorization"] = f"Bearer {self._access_token}"
        return h

    def _request(self, method: str, path: str, **kwargs) -> Optional[httpx.Response]:
        """Make a request, handle connectivity and token refresh."""
        url = f"{self._base_url}{path}"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = getattr(client, method)(
                    url, headers=self._headers(), **kwargs
                )
                self._is_online = True

                # Auto-refresh on 401
                if response.status_code == 401 and self._refresh_token:
                    if self._do_refresh():
                        response = getattr(client, method)(
                            url, headers=self._headers(), **kwargs
                        )
                return response

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            self._is_online = False
            logger.warning("API offline: %s", e)
            return None
        except Exception as e:
            logger.error("API error: %s", e)
            return None

    def _do_refresh(self) -> bool:
        """Refresh the access token."""
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.post(
                    f"{self._base_url}/api/v1/auth/refresh",
                    json={"refresh_token": self._refresh_token},
                    headers={"Content-Type": "application/json"},
                )
                if r.status_code == 200:
                    data = r.json()
                    self._access_token = data["access_token"]
                    self._refresh_token = data["refresh_token"]
                    logger.info("Token refreshed")
                    return True
        except Exception as e:
            logger.error("Token refresh failed: %s", e)
        return False

    # ── Auth ──

    def login(self, email: str, password: str) -> Optional[dict]:
        r = self._request("post", "/api/v1/auth/login", json={
            "email": email, "password": password,
        })
        if r and r.status_code == 200:
            data = r.json()
            self.set_tokens(data["access_token"], data["refresh_token"])
            return data
        return None

    # ── Vehicles ──

    def get_vehicles(self, page: int = 1, page_size: int = 100) -> Optional[dict]:
        r = self._request("get", f"/api/v1/vehicles/?page={page}&page_size={page_size}")
        return r.json() if r and r.status_code == 200 else None

    def create_vehicle(self, data: dict) -> Optional[dict]:
        r = self._request("post", "/api/v1/vehicles/", json=data)
        if r and r.status_code == 201:
            return r.json()
        if r:
            return {"error": r.json().get("detail", "Error")}
        return None

    def update_vehicle(self, vid: str, data: dict) -> Optional[dict]:
        r = self._request("put", f"/api/v1/vehicles/{vid}", json=data)
        if r and r.status_code == 200:
            return r.json()
        if r:
            return {"error": r.json().get("detail", "Error")}
        return None

    def delete_vehicle(self, vid: str) -> bool:
        r = self._request("delete", f"/api/v1/vehicles/{vid}")
        return r is not None and r.status_code == 204

    def check_availability(self, vid: str, start: str, end: str) -> Optional[dict]:
        r = self._request("get", f"/api/v1/vehicles/{vid}/availability?start={start}&end={end}")
        return r.json() if r and r.status_code == 200 else None

    # ── Rentals ──

    def get_rentals(self, page: int = 1, status: str = None) -> Optional[dict]:
        url = f"/api/v1/rentals/?page={page}"
        if status:
            url += f"&status={status}"
        r = self._request("get", url)
        return r.json() if r and r.status_code == 200 else None

    def create_rental(self, data: dict) -> Optional[dict]:
        r = self._request("post", "/api/v1/rentals/", json=data)
        if r and r.status_code == 201:
            return r.json()
        if r:
            return {"error": r.json().get("detail", "Error")}
        return None

    def cancel_rental(self, rid: str) -> Optional[dict]:
        r = self._request("post", f"/api/v1/rentals/{rid}/cancel")
        if r and r.status_code == 200:
            return r.json()
        if r:
            return {"error": r.json().get("detail", "Error")}
        return None

    def complete_rental(self, rid: str) -> Optional[dict]:
        r = self._request("post", f"/api/v1/rentals/{rid}/complete")
        if r and r.status_code == 200:
            return r.json()
        if r:
            return {"error": r.json().get("detail", "Error")}
        return None

    def activate_rental(self, rid: str) -> Optional[dict]:
        r = self._request("post", f"/api/v1/rentals/{rid}/activate")
        if r and r.status_code == 200:
            return r.json()
        if r:
            return {"error": r.json().get("detail", "Error")}
        return None

    # ── Dashboard ──

    def get_dashboard(self) -> Optional[dict]:
        r = self._request("get", "/api/v1/dashboard/stats")
        return r.json() if r and r.status_code == 200 else None

    def get_stats(self, period: str) -> Optional[dict]:
        r = self._request("get", f"/api/v1/dashboard/{period}")
        return r.json() if r and r.status_code == 200 else None

    def get_vehicle_performance(self) -> Optional[list]:
        r = self._request("get", "/api/v1/dashboard/vehicle-performance")
        return r.json() if r and r.status_code == 200 else None

    def upload_vehicle_image(self, file_path: str, vehicle_id: Optional[str] = None) -> Optional[dict]:
        from pathlib import Path
        import mimetypes
        url = f"{self._base_url}/api/v1/vehicles/upload-image"
        if vehicle_id:
            url += f"?vehicle_id={vehicle_id}"
        headers = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        try:
            with open(file_path, "rb") as f:
                mime_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"
                files = {"file": (Path(file_path).name, f, mime_type)}
                with httpx.Client(timeout=30.0) as client:
                    r = client.post(url, headers=headers, files=files)
                    if r.status_code in (200, 201):
                        return r.json()
        except Exception as e:
            logger.error("Failed to upload image: %s", e)
        return None

    # ── Clients ──

    def get_clients(self, page: int = 1, page_size: int = 100, search: Optional[str] = None, status: Optional[str] = None) -> Optional[dict]:
        url = f"/api/v1/clients/?page={page}&page_size={page_size}"
        if search:
            url += f"&search={search}"
        if status:
            url += f"&status={status}"
        r = self._request("get", url)
        return r.json() if r and r.status_code == 200 else None

    def get_client(self, cid: str) -> Optional[dict]:
        r = self._request("get", f"/api/v1/clients/{cid}")
        return r.json() if r and r.status_code == 200 else None

    def create_client(self, data: dict) -> Optional[dict]:
        r = self._request("post", "/api/v1/clients/", json=data)
        if r and r.status_code == 201:
            return r.json()
        if r:
            return {"error": r.json().get("detail", "Error")}
        return None

    def update_client(self, cid: str, data: dict) -> Optional[dict]:
        r = self._request("put", f"/api/v1/clients/{cid}", json=data)
        if r and r.status_code == 200:
            return r.json()
        if r:
            return {"error": r.json().get("detail", "Error")}
        return None

    def delete_client(self, cid: str) -> bool:
        r = self._request("delete", f"/api/v1/clients/{cid}")
        return r is not None and r.status_code in (200, 204)

    def get_client_history(self, cid: str) -> Optional[dict]:
        r = self._request("get", f"/api/v1/clients/{cid}/history")
        return r.json() if r and r.status_code == 200 else None

    def get_client_rentals_report(self, cid: str) -> Optional[dict]:
        """Canonical live client report: summary KPIs + rentals + vehicles."""
        r = self._request("get", f"/api/v1/clients/{cid}/rentals")
        return r.json() if r and r.status_code == 200 else None

    def upload_client_image(self, file_path: str) -> Optional[dict]:
        from pathlib import Path
        import mimetypes
        url = f"{self._base_url}/api/v1/clients/upload-image"
        headers = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        try:
            with open(file_path, "rb") as f:
                mime_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"
                files = {"file": (Path(file_path).name, f, mime_type)}
                with httpx.Client(timeout=30.0) as client:
                    r = client.post(url, headers=headers, files=files)
                    if r.status_code in (200, 201):
                        return r.json()
        except Exception as e:
            logger.error("Failed to upload client image: %s", e)
        return None

    # ── Notifications ──

    def get_notifications(self, unread_only: bool = False, page: int = 1) -> Optional[dict]:
        r = self._request("get", f"/api/v1/notifications/?unread_only={unread_only}&page={page}")
        return r.json() if r and r.status_code == 200 else None

    def get_unread_notification_count(self) -> int:
        r = self._request("get", "/api/v1/notifications/unread-count")
        if r and r.status_code == 200:
            return r.json().get("unread_count", 0)
        return 0

    def mark_notification_read(self, notification_id: str) -> bool:
        r = self._request("patch", f"/api/v1/notifications/{notification_id}/read")
        return r is not None and r.status_code == 200

    def mark_all_notifications_read(self) -> bool:
        r = self._request("post", "/api/v1/notifications/mark-all-read")
        return r is not None and r.status_code == 200
