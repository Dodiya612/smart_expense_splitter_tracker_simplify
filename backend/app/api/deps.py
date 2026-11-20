import uuid
from typing import Optional
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import (
    Action,
    CategoryPolicy,
    ExpensePolicy,
    GroupPolicy,
    GroupRole,
    PROTECTED_FIELDS,
    SessionPolicy,
    validate_protected_fields_update,
)
from app.core.database import get_db
from app.core.security import (
    TokenExpiredError,
    TokenInvalidError,
    decode_access_token,
    token_version_from_claims,
)
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Validates the bearer access token and returns the current active User.
    Raises 401 UNAUTHORIZED, TOKEN_EXPIRED, or INVALID_TOKEN on failure.
    """
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Authentication required. Bearer token missing."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(auth.credentials)
    except TokenExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message": "Access token has expired."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except TokenInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Token subject (sub) is missing."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Invalid token subject format."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "User not found."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "ACCOUNT_INACTIVE", "message": "User account is inactive."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # T-50: a password change bumps users.token_version. Every access token issued before
    # that (on any device) carries the old version and is refused here, so the change takes
    # effect on the next request instead of when the token would have expired.
    try:
        token_version = token_version_from_claims(payload)
    except TokenInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if token_version != (user.token_version or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "TOKEN_REVOKED",
                "message": "This session has been signed out. Please log in again.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_session_id(
    current_user: User = Depends(get_current_user),
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> uuid.UUID:
    """The device session (refresh-token family) the validated access token belongs to.

    Depends on get_current_user, so the token has already been fully validated (signature,
    claims, user, token version) before its ``sid`` claim is read. Access tokens issued
    before T-50 have no ``sid``: the client gets a 401 and its normal refresh-and-retry
    obtains a new access token that carries one.
    """
    assert auth is not None  # guaranteed by get_current_user
    payload = decode_access_token(auth.credentials)
    try:
        return uuid.UUID(str(payload["sid"]))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "SESSION_NOT_IDENTIFIED",
                "message": "Your session needs to be refreshed. Please try again.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user_optional(
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Returns the User if a valid access token is provided and user exists,
    or None if missing, expired, or invalid. Never raises HTTP 401, allowing
    endpoints like logout to proceed safely using request body payloads while
    retaining identity for ownership checks even if account is inactive.
    """
    if not auth or not auth.credentials:
        return None

    try:
        payload = decode_access_token(auth.credentials)
    except (TokenExpiredError, TokenInvalidError, Exception):
        return None

    user_id_str = payload.get("sub")
    if not user_id_str:
        return None

    try:
        user_uuid = uuid.UUID(user_id_str)
    except (ValueError, TypeError):
        return None

    try:
        result = await db.execute(select(User).where(User.id == user_uuid))
        user = result.scalar_one_or_none()
        if not user:
            return None
        return user
    except Exception:
        return None


__all__ = [
    "Action",
    "CategoryPolicy",
    "ExpensePolicy",
    "GroupPolicy",
    "GroupRole",
    "PROTECTED_FIELDS",
    "SessionPolicy",
    "get_current_session_id",
    "get_current_user",
    "get_current_user_optional",
    "validate_protected_fields_update",
]
