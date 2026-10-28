import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.rate_limit import LoginRateLimit

logger = logging.getLogger(__name__)


def _to_utc(dt: datetime) -> datetime:
    """Normalize datetime to UTC timezone-aware datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def check_login_rate_limit(
    db: AsyncSession,
    key: str,
    max_attempts: Optional[int] = None,
    window_seconds: Optional[int] = None,
) -> None:
    """
    Checks if the failed login attempt rate limit has been exceeded for the given key.
    Raises HTTPException 429 when the limit is exceeded.
    Compatible with multiple workers and instances via shared database persistence.
    """
    max_att = max_attempts if max_attempts is not None else settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS
    win_sec = window_seconds if window_seconds is not None else settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS

    now = datetime.now(timezone.utc)
    try:
        query = select(LoginRateLimit).where(LoginRateLimit.key == key)
        result = await db.execute(query)
        record = result.scalar_one_or_none()

        if not record:
            return

        last_attempt = _to_utc(record.last_attempt_at)
        elapsed = (now - last_attempt).total_seconds()

        if elapsed >= win_sec:
            # Lockout/window window expired; reset count
            record.attempts = 0
            record.last_attempt_at = now
            await db.commit()
            return

        if record.attempts >= max_att:
            retry_after = max(1, int(win_sec - elapsed))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": f"Too many failed login attempts. Please try again in {retry_after} seconds.",
                },
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(f"Error checking login rate limit for '{key}': {exc}")


async def record_failed_login_attempt(
    db: AsyncSession,
    key: str,
    window_seconds: Optional[int] = None,
) -> None:
    """
    Records a failed login attempt for the given key.
    Increments attempt counter or resets if previous window expired.
    Compatible with multiple workers and instances via shared database.
    """
    win_sec = window_seconds if window_seconds is not None else settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    now = datetime.now(timezone.utc)

    try:
        query = select(LoginRateLimit).where(LoginRateLimit.key == key)
        result = await db.execute(query)
        record = result.scalar_one_or_none()

        if record:
            last_attempt = _to_utc(record.last_attempt_at)
            elapsed = (now - last_attempt).total_seconds()
            if elapsed >= win_sec:
                record.attempts = 1
            else:
                record.attempts += 1
            record.last_attempt_at = now
        else:
            record = LoginRateLimit(
                key=key,
                attempts=1,
                last_attempt_at=now,
            )
            db.add(record)

        await db.commit()
    except Exception as exc:
        logger.warning(f"Error recording failed login attempt for '{key}': {exc}")
        await db.rollback()


async def reset_login_rate_limit(
    db: AsyncSession,
    key: str,
) -> None:
    """
    Clears failed login attempts for the key upon a successful login.
    """
    try:
        query = select(LoginRateLimit).where(LoginRateLimit.key == key)
        result = await db.execute(query)
        record = result.scalar_one_or_none()
        if record:
            await db.delete(record)
            await db.commit()
    except Exception as exc:
        logger.warning(f"Error resetting login rate limit for '{key}': {exc}")
        await db.rollback()
