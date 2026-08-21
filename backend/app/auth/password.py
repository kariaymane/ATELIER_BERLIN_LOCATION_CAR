"""
Password hashing using Argon2id.
Passwords are NEVER stored or logged in plaintext.
"""
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
import logging

logger = logging.getLogger(__name__)

# Argon2id with recommended parameters
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MB
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,  # argon2id
)


def hash_password(password: str) -> str:
    """Hash a password using Argon2id. Never logs the password."""
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its Argon2id hash. Never logs passwords."""
    try:
        return _hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed_password: str) -> bool:
    """Check if a password hash needs to be updated (e.g., after parameter changes)."""
    return _hasher.check_needs_rehash(hashed_password)
