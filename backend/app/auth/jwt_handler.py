"""
JWT token creation and verification.
Access tokens are short-lived (15 min).
Refresh tokens are longer-lived (7 days) and stored hashed.
"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt, JWTError
import logging

logger = logging.getLogger(__name__)


class JWTHandler:
    """Handles JWT token operations. Secrets come from config, never hardcoded."""

    def __init__(
        self,
        secret: str,
        refresh_secret: str,
        algorithm: str = "HS256",
        access_expire_minutes: int = 15,
        refresh_expire_days: int = 7,
    ):
        self._secret = secret
        self._refresh_secret = refresh_secret
        self._algorithm = algorithm
        self._access_expire_minutes = access_expire_minutes
        self._refresh_expire_days = refresh_expire_days

    def create_access_token(
        self,
        user_id: str,
        role: str,
        device_id: Optional[str] = None,
    ) -> str:
        """Create a short-lived access token."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "role": role,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=self._access_expire_minutes),
            "jti": str(uuid.uuid4()),
        }
        if device_id:
            payload["device_id"] = device_id
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def create_refresh_token(
        self,
        user_id: str,
        device_id: Optional[str] = None,
    ) -> tuple[str, datetime]:
        """Create a refresh token. Returns (token, expiry)."""
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(days=self._refresh_expire_days)
        payload = {
            "sub": user_id,
            "type": "refresh",
            "iat": now,
            "exp": expiry,
            "jti": str(uuid.uuid4()),
        }
        if device_id:
            payload["device_id"] = device_id
        token = jwt.encode(payload, self._refresh_secret, algorithm=self._algorithm)
        return token, expiry

    def verify_access_token(self, token: str) -> Optional[dict]:
        """Verify and decode an access token. Returns None on failure."""
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
            if payload.get("type") != "access":
                return None
            return payload
        except JWTError:
            return None

    def verify_refresh_token(self, token: str) -> Optional[dict]:
        """Verify and decode a refresh token. Returns None on failure."""
        try:
            payload = jwt.decode(
                token, self._refresh_secret, algorithms=[self._algorithm]
            )
            if payload.get("type") != "refresh":
                return None
            return payload
        except JWTError:
            return None

    @staticmethod
    def hash_token(token: str) -> str:
        """Hash a token for database storage. Never store raw tokens."""
        return hashlib.sha256(token.encode()).hexdigest()
