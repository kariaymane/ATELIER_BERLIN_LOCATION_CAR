"""The ONE desktop auth client — typed outcomes.

Pins that a network failure NEVER reads as 'identifiants incorrects', that a
slow cold-starting server is retried into success, and that a server-side
rejection is not eligible for offline fallback
(FORENSIC_ROOT_CAUSE_ANALYSIS.md §2).
"""
import httpx
import pytest

from app.services.auth_client import AuthClient, AuthOutcome


class _FakeClient:
    """Stands in for httpx.Client; `script` is a list of (exc_or_response)."""

    def __init__(self, script):
        self._script = script  # shared across attempts, like a real server

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None):
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url):
        return httpx.Response(200, json={"status": "alive"})


def _resp(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://x"))


def _patch(monkeypatch, script):
    monkeypatch.setattr("app.services.auth_client._sleep", lambda *_: None)
    shared = _FakeClient(script)
    monkeypatch.setattr(
        "app.services.auth_client.httpx.Client",
        lambda *a, **k: shared,
    )


def test_success(monkeypatch):
    _patch(monkeypatch, [_resp(200, {
        "access_token": "a", "refresh_token": "r", "role": "ADMIN",
        "user_id": "u1", "full_name": "Berlin",
    })])
    # Synthetic credentials only. The transport is mocked (`https://x` is never
    # dialled), so these values are decorative — a real credential here would be
    # a published secret, not a stronger test.
    res = AuthClient("https://x").login("operator@example.test", "dummy-password")
    assert res.outcome == AuthOutcome.SUCCESS
    assert res.data["access_token"] == "a"


def test_wrong_password_is_invalid_credentials_not_network(monkeypatch):
    _patch(monkeypatch, [_resp(401, {"detail": "Identifiants invalides"})])
    res = AuthClient("https://x").login("operator@example.test", "nope12345")
    assert res.outcome == AuthOutcome.INVALID_CREDENTIALS
    assert res.is_server_side_rejection is True


def test_locked_account(monkeypatch):
    _patch(monkeypatch, [_resp(401, {"detail": "Compte bloqué / verrouillé"})])
    res = AuthClient("https://x").login("operator@example.test", "x" * 9)
    assert res.outcome == AuthOutcome.ACCOUNT_LOCKED
    assert res.is_server_side_rejection is True


def test_rate_limited(monkeypatch):
    _patch(monkeypatch, [_resp(429, {"detail": "rate limit exceeded"})])
    res = AuthClient("https://x").login("a@b.com", "x" * 9)
    assert res.outcome == AuthOutcome.RATE_LIMITED
    assert res.is_server_side_rejection is False


def test_connect_error_is_network_unreachable(monkeypatch):
    _patch(monkeypatch, [httpx.ConnectError("no route to host")])
    res = AuthClient("https://x").login("a@b.com", "x" * 9)
    assert res.outcome == AuthOutcome.NETWORK_UNREACHABLE
    assert res.is_server_side_rejection is False


def test_cold_start_timeout_then_success_is_retried(monkeypatch):
    _patch(monkeypatch, [
        httpx.ReadTimeout("cold start"),
        _resp(200, {"access_token": "a", "refresh_token": "r",
                    "role": "ADMIN", "user_id": "u", "full_name": "B"}),
    ])
    res = AuthClient("https://x").login("a@b.com", "x" * 9)
    assert res.outcome == AuthOutcome.SUCCESS


def test_persistent_timeout_is_network_not_credentials(monkeypatch):
    _patch(monkeypatch, [httpx.ReadTimeout("x")] * 5)
    res = AuthClient("https://x").login("a@b.com", "x" * 9)
    assert res.outcome == AuthOutcome.NETWORK_UNREACHABLE


def test_500_is_server_error(monkeypatch):
    _patch(monkeypatch, [_resp(500, {"detail": "boom"})])
    res = AuthClient("https://x").login("a@b.com", "x" * 9)
    assert res.outcome == AuthOutcome.SERVER_ERROR
    assert res.is_server_side_rejection is False


def test_bad_base_url_is_config_error(monkeypatch):
    res = AuthClient("not-a-url").login("a@b.com", "x" * 9)
    assert res.outcome == AuthOutcome.CONFIG_ERROR


def test_every_outcome_maps_to_an_i18n_key():
    for oc in AuthOutcome:
        if oc == AuthOutcome.SUCCESS:
            continue
        from app.services.auth_client import AuthResult
        assert AuthResult(oc).i18n_key.startswith("login.err_")
