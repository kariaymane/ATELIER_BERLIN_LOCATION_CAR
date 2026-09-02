"""
AuthClient — the ONE desktop authentication client.

Before this module the desktop had two login implementations:
`LoginWorker._authenticate_online` (raw httpx, 4s timeout, no retry — the
path the screen actually used) and `ApiClient.login` (robust, retrying —
effectively dead code). Every "login keeps breaking" fix landed in the wrong
one (FORENSIC_ROOT_CAUSE_ANALYSIS.md §1.1, §2).

This is now the only symbol allowed to call `/api/v1/auth/*` from the
desktop. It:
  * uses a 5s connect / 30s read timeout with 2 backoff retries, because the
    production Fly machine can cold-start and the first hit legitimately
    takes >10s;
  * returns a TYPED outcome so the UI can tell INVALID_CREDENTIALS from
    NETWORK_UNREACHABLE from SERVER_ERROR from RATE_LIMITED — never again
    "identifiants incorrects" for a flat network.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 30.0
_RETRIES = 2

# Indirected so tests can neutralise the backoff.
_sleep = time.sleep


class AuthOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_UNREACHABLE = "NETWORK_UNREACHABLE"
    SERVER_ERROR = "SERVER_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"


# Outcome -> i18n key for the login screen. One message per real cause.
OUTCOME_I18N = {
    AuthOutcome.INVALID_CREDENTIALS: "login.err_invalid_credentials",
    AuthOutcome.ACCOUNT_LOCKED: "login.err_account_locked",
    AuthOutcome.RATE_LIMITED: "login.err_rate_limited",
    AuthOutcome.NETWORK_UNREACHABLE: "login.err_network",
    AuthOutcome.SERVER_ERROR: "login.err_server",
    AuthOutcome.CONFIG_ERROR: "login.err_config",
}


@dataclass
class AuthResult:
    outcome: AuthOutcome
    data: dict = field(default_factory=dict)
    http_status: Optional[int] = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome == AuthOutcome.SUCCESS

    @property
    def is_server_side_rejection(self) -> bool:
        """The server was reached and said no — offline fallback is NOT valid."""
        return self.outcome in (
            AuthOutcome.INVALID_CREDENTIALS,
            AuthOutcome.ACCOUNT_LOCKED,
        )

    @property
    def i18n_key(self) -> str:
        return OUTCOME_I18N.get(self.outcome, "login.err_server")


class AuthClient:
    def __init__(self, base_url: str):
        self._base = base_url.rstrip("/")
        if self._base.endswith("/api/v1"):
            self._base = self._base[:-7]
        self._timeout = httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)

    # ── login ──────────────────────────────────────────────────────────
    def login(self, email: str, password: str, device_id: str | None = None) -> AuthResult:
        if not self._base.startswith(("http://", "https://")):
            return AuthResult(AuthOutcome.CONFIG_ERROR, detail=f"bad API base URL {self._base!r}")

        payload = {"email": email, "password": password}
        if device_id:
            payload["device_id"] = device_id

        last_exc: Exception | None = None
        for attempt in range(_RETRIES + 1):
            try:
                with httpx.Client(timeout=self._timeout) as c:
                    r = c.post(f"{self._base}/api/v1/auth/login", json=payload)
                return self._classify(r)
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                # A genuine "can't reach the server" — do not spend all retries.
                logger.info("auth: connect failed (%s)", e)
                return AuthResult(AuthOutcome.NETWORK_UNREACHABLE, detail=str(e))
            except httpx.TimeoutException as e:
                last_exc = e
                if attempt < _RETRIES:
                    _sleep(1.5 * (attempt + 1))
                    logger.warning("auth: read timeout, retry %d/%d", attempt + 1, _RETRIES)
                    continue
            except Exception as e:  # pragma: no cover - defensive
                last_exc = e
                break
        logger.warning("auth: giving up (%s)", last_exc)
        return AuthResult(AuthOutcome.NETWORK_UNREACHABLE, detail=str(last_exc))

    def _classify(self, r: httpx.Response) -> AuthResult:
        if r.status_code == 200:
            return AuthResult(AuthOutcome.SUCCESS, data=r.json(), http_status=200)
        detail = ""
        try:
            body = r.json()
            detail = body.get("detail") if isinstance(body, dict) else str(body)
            if isinstance(detail, list):  # pydantic 422
                detail = "; ".join(str(d.get("msg", d)) for d in detail)
        except Exception:
            detail = r.text[:200]
        low = (detail or "").lower()
        if r.status_code == 429:
            return AuthResult(AuthOutcome.RATE_LIMITED, http_status=429, detail=detail)
        if r.status_code in (400, 401, 403, 422):
            if "lock" in low or "verrou" in low or "bloqu" in low:
                return AuthResult(AuthOutcome.ACCOUNT_LOCKED, http_status=r.status_code, detail=detail)
            return AuthResult(AuthOutcome.INVALID_CREDENTIALS, http_status=r.status_code, detail=detail)
        return AuthResult(AuthOutcome.SERVER_ERROR, http_status=r.status_code, detail=detail)

    # ── refresh ────────────────────────────────────────────────────────
    def refresh(self, refresh_token: str) -> Optional[dict]:
        """Return the new token dict, or None on any failure."""
        try:
            with httpx.Client(timeout=httpx.Timeout(15.0, connect=_CONNECT_TIMEOUT)) as c:
                r = c.post(
                    f"{self._base}/api/v1/auth/refresh",
                    json={"refresh_token": refresh_token},
                )
                if r.status_code == 200:
                    return r.json()
                logger.info("auth: refresh rejected HTTP %s", r.status_code)
        except Exception as e:
            logger.warning("auth: refresh transport error (%s)", e)
        return None

    def warmup(self) -> None:
        """Fire-and-forget health ping to start a suspended Fly machine while
        the operator is still typing their password."""
        try:
            with httpx.Client(timeout=httpx.Timeout(20.0, connect=_CONNECT_TIMEOUT)) as c:
                c.get(f"{self._base}/health")
        except Exception:
            pass
