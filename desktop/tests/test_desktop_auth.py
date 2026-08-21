import pytest
from app.services.api_client import ApiClient


def test_api_client_token_management():
    client = ApiClient(base_url="https://car-rental-system.fly.dev")
    assert client.is_online is False
    assert client._access_token == ""

    client.set_tokens("access_token_123", "refresh_token_456")
    assert client._access_token == "access_token_123"
    assert client._refresh_token == "refresh_token_456"

    headers = client._headers()
    assert headers["Authorization"] == "Bearer access_token_123"
    assert headers["Content-Type"] == "application/json"


def test_api_client_offline_graceful_handling():
    # Invalid host should not crash the client, but return None and mark offline
    client = ApiClient(base_url="http://127.0.0.1:59998", timeout=0.5)
    res = client.get_vehicles()
    assert res is None
    assert client.is_online is False
