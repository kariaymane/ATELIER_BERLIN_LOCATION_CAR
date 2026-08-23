"""
Authentication service — handles login, token management, and password operations.
Never logs passwords or tokens.
"""
from typing import Optional
from uuid import UUID
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password, verify_password, needs_rehash
from app.auth.jwt_handler import JWTHandler
from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.repositories.user_repository import UserRepository
from app.repositories.audit_repository import AuditRepository
from app.i18n import get_message
import logging

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession, jwt_handler: JWTHandler):
        self._session = session
        self._jwt_handler = jwt_handler
        self._user_repo = UserRepository(session)
        self._audit_repo = AuditRepository(session)

    async def login(
        self,
        email: str,
        password: str,
        device_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        lang: str = "fr",
    ) -> dict:
        """
        Authenticate user and return tokens.
        Logs failed attempts but NEVER logs the password.
        """
        clean_email = email.strip().lower() if email else ""
        user = await self._user_repo.get_by_email(clean_email)

        now = datetime.now(timezone.utc)
        if user and user.locked_until and user.locked_until > now:
            await self._audit_repo.create(
                entity_type="auth",
                action="LOGIN_FAILED_LOCKED",
                user_id=user.id,
                details="Attempted login on locked account",
                ip_address=ip_address,
                device_id=device_id,
            )
            return {"error": get_message("auth.account_locked", lang)}

        if not user or not verify_password(password, user.password_hash):
            # Log failed attempt without the password
            await self._audit_repo.create(
                entity_type="auth",
                action="LOGIN_FAILED",
                details=f"Failed login for email (not logging the email for security)",
                ip_address=ip_address,
                device_id=device_id,
            )
            if user:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= 5:
                    user.locked_until = now + timedelta(minutes=15)
                    await self._audit_repo.create(
                        entity_type="auth",
                        action="ACCOUNT_LOCKED",
                        user_id=user.id,
                        details="Account locked due to 5 failed login attempts",
                        ip_address=ip_address,
                        device_id=device_id,
                    )
                self._session.add(user)
                await self._session.commit()
                if user.failed_login_attempts >= 5:
                    return {"error": get_message("auth.account_locked", lang)}

            return {"error": get_message("auth.invalid_credentials", lang)}

        if not user.is_active:
            await self._audit_repo.create(
                entity_type="auth",
                action="LOGIN_FAILED",
                user_id=user.id,
                details="Disabled account login attempt",
                ip_address=ip_address,
                device_id=device_id,
            )
            return {"error": get_message("auth.account_disabled", lang)}

        # Reset failed attempts and locked status on successful login
        user.failed_login_attempts = 0
        user.locked_until = None
        self._session.add(user)

        # Rehash password if parameters have changed
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        # Create tokens
        access_token = self._jwt_handler.create_access_token(
            user_id=str(user.id),
            role=user.role,
            device_id=device_id,
        )
        refresh_token, refresh_expiry = self._jwt_handler.create_refresh_token(
            user_id=str(user.id),
            device_id=device_id,
        )

        # Store hashed refresh token
        token_record = RefreshToken(
            user_id=user.id,
            token_hash=JWTHandler.hash_token(refresh_token),
            expires_at=refresh_expiry,
            device_id=device_id,
        )
        self._session.add(token_record)

        # Audit log
        await self._audit_repo.create(
            entity_type="auth",
            action="LOGIN",
            user_id=user.id,
            ip_address=ip_address,
            device_id=device_id,
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self._jwt_handler._access_expire_minutes * 60,
            "user_id": str(user.id),
            "role": user.role,
            "full_name": user.full_name,
        }

    async def refresh_tokens(
        self,
        refresh_token: str,
        device_id: Optional[str] = None,
        lang: str = "fr",
    ) -> dict:
        """Refresh an access token using a valid refresh token."""
        payload = self._jwt_handler.verify_refresh_token(refresh_token)
        if not payload:
            return {"error": get_message("auth.token_invalid", lang)}

        # Find the stored token by hash
        from sqlalchemy import select
        token_hash = JWTHandler.hash_token(refresh_token)
        result = await self._session.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.is_revoked == False,
            )
        )
        token_record = result.scalar_one_or_none()

        if not token_record:
            return {"error": get_message("auth.refresh_token_revoked", lang)}

        if token_record.is_expired:
            return {"error": get_message("auth.token_expired", lang)}

        # Get user
        user = await self._user_repo.get_by_id(token_record.user_id)
        if not user or not user.is_active:
            return {"error": get_message("auth.account_disabled", lang)}

        # Revoke old token
        token_record.is_revoked = True

        # Create new tokens (token rotation)
        new_access = self._jwt_handler.create_access_token(
            user_id=str(user.id),
            role=user.role,
            device_id=device_id,
        )
        new_refresh, new_expiry = self._jwt_handler.create_refresh_token(
            user_id=str(user.id),
            device_id=device_id,
        )

        # Store new refresh token
        new_token_record = RefreshToken(
            user_id=user.id,
            token_hash=JWTHandler.hash_token(new_refresh),
            expires_at=new_expiry,
            device_id=device_id,
        )
        self._session.add(new_token_record)

        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": self._jwt_handler._access_expire_minutes * 60,
        }

    async def logout(
        self,
        refresh_token: str,
        user_id: Optional[UUID] = None,
        ip_address: Optional[str] = None,
        lang: str = "fr",
    ) -> dict:
        """Revoke a refresh token (logout)."""
        from sqlalchemy import select
        token_hash = JWTHandler.hash_token(refresh_token)
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        token_record = result.scalar_one_or_none()

        if token_record:
            token_record.is_revoked = True
            await self._audit_repo.create(
                entity_type="auth",
                action="LOGOUT",
                user_id=user_id,
                ip_address=ip_address,
            )

        return {"message": get_message("auth.logout_success", lang)}

    async def change_password(
        self,
        user_id: UUID,
        current_password: str,
        new_password: str,
        ip_address: Optional[str] = None,
        lang: str = "fr",
    ) -> dict:
        """Change user password. Old password must be verified first."""
        user = await self._user_repo.get_by_id(user_id)
        if not user:
            return {"error": get_message("user.not_found", lang)}

        if not verify_password(current_password, user.password_hash):
            return {"error": get_message("auth.password_mismatch", lang)}

        user.password_hash = hash_password(new_password)
        user.version += 1

        # Revoke all refresh tokens for this user (force re-login)
        from sqlalchemy import update
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.is_revoked == False)
            .values(is_revoked=True)
        )

        await self._audit_repo.create(
            entity_type="auth",
            action="PASSWORD_CHANGED",
            user_id=user_id,
            ip_address=ip_address,
        )

        return {"message": get_message("auth.password_changed", lang)}
