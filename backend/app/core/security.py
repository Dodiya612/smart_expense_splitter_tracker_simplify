import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

import argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
import jwt

from app.core.config import settings


class TokenExpiredError(Exception):
    """Raised when an access token has expired."""
    pass


class TokenInvalidError(Exception):
    """Raised when an access token is invalid, tampered with, or contains incorrect claims."""
    pass


# Argon2id password hasher with exact parameter specification
_password_hasher = argon2.PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    type=argon2.Type.ID,
)

# Reference dummy hash for constant-time comparison when user is not found
DUMMY_PASSWORD_HASH: str = _password_hasher.hash("reference-dummy-password-for-timing-equalization")


def hash_password(password: str) -> str:
    """Hashes a password using Argon2id."""
    return _password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain-text password against an Argon2id hash."""
    try:
        return _password_hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_dummy_password(plain_password: str = "dummy_password") -> bool:
    """
    Performs a dummy password verification against precomputed hash to mitigate
    user enumeration timing attacks when a requested account does not exist.
    """
    try:
        _password_hasher.verify(DUMMY_PASSWORD_HASH, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pass
    return False


def validate_password_length(password: str) -> bool:
    """Validates that a password satisfies minimum and maximum length bounds (8-128)."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if len(password) > 128:
        raise ValueError("Password must not exceed 128 characters.")
    return True


def create_access_token(
    user_id: UUID | str,
    email: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Creates a signed JWT access token.
    Claims include sub, email, type ('access'), iss, aud, iat, exp, and jti.
    """
    now = datetime.now(timezone.utc)
    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "type": "access",
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": str(uuid4()),
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decodes and validates a JWT access token.
    Validates signature, iss, aud, exp, and type == 'access'.
    Raises TokenExpiredError if expired, TokenInvalidError if invalid.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
        if payload.get("type") != "access":
            raise TokenInvalidError("Invalid token type: expected 'access'")
        return payload
    except jwt.ExpiredSignatureError as e:
        raise TokenExpiredError("Access token has expired.") from e
    except jwt.PyJWTError as e:
        raise TokenInvalidError(f"Invalid access token: {str(e)}") from e


def generate_refresh_token() -> str:
    """Generates 32 cryptographically secure random bytes as a 64-character hex string."""
    return secrets.token_hex(32)


def hash_refresh_token(token: str) -> str:
    """Hashes a raw refresh token using SHA-256 to produce a 64-character hex digest."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
