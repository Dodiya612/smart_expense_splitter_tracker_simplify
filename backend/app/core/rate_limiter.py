"""Shared PostgreSQL-backed rate limiter (T-39 / US-33).

Fixed-window counters live in the ``rate_limit_buckets`` table, so one limit holds across
every worker and instance. A request "reserves" its slot with a single atomic
``INSERT ... ON CONFLICT DO UPDATE SET count = count + 1 RETURNING count`` BEFORE the
guarded work runs, so concurrent requests can never all pass a read-then-write check.

* Counters are written in their own short session, so a request that later fails and
  rolls back still counts.
* Identifiers (emails, user ids, client addresses) are stored only as keyed HMAC hashes.
* Over-limit requests get HTTP 429 with the standard error envelope, code
  ``RATE_LIMIT_EXCEEDED`` and a positive integer ``Retry-After``.
* When the counters cannot be read or written, the request is refused with HTTP 503
  (``RATE_LIMITER_UNAVAILABLE``), never 429, on EVERY limited route. There is no fail-open
  path: a limit is never silently skipped because the database is unavailable.
* Client addresses are NEVER taken from ``X-Forwarded-For`` or the socket peer. They come
  only from the header named by ``TRUSTED_CLIENT_IP_HEADER`` (unset by default). Without
  it, address-scoped limits are skipped and a warning is logged.

See docs/RATE_LIMITING_AND_CSRF.md.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, Sequence

from fastapi import HTTPException, Request, status
from sqlalchemy import delete, select, tuple_, update, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.rate_limit import RateLimitBucket
from app.schemas.common import ApiErrorResponse

logger = logging.getLogger("app.rate_limit")

RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
RATE_LIMITER_UNAVAILABLE = "RATE_LIMITER_UNAVAILABLE"

# OpenAPI documentation for guarded routes (429 and 503).
RATE_LIMIT_RESPONSES: dict[int | str, dict[str, Any]] = {
    429: {
        "model": ApiErrorResponse,
        "description": "Rate limit exceeded (code RATE_LIMIT_EXCEEDED).",
        "headers": {
            "Retry-After": {
                "description": "Seconds to wait before retrying (positive integer).",
                "schema": {"type": "integer", "minimum": 1},
            }
        },
    },
    503: {
        "model": ApiErrorResponse,
        "description": "Rate limiter unavailable (code RATE_LIMITER_UNAVAILABLE); the request was not processed.",
    },
}


class RateLimiterUnavailable(Exception):
    """The counter store could not be read or written."""


@dataclass(frozen=True)
class Policy:
    scope: str
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class Hit:
    """A reserved slot: what was counted and where, so it can be refunded or cleared."""

    policy: Policy
    identifier_hash: str
    window_start: datetime
    count: int
    retry_after: int

    @property
    def exceeded(self) -> bool:
        return self.count > self.policy.limit


def get_policy(name: str) -> Policy:
    """Build a policy from current settings (read at call time so tests can override)."""
    s = settings
    table = {
        "login_pair": (s.LOGIN_RATE_LIMIT_MAX_ATTEMPTS, s.LOGIN_RATE_LIMIT_WINDOW_SECONDS),
        "login_ip": (s.RATE_LIMIT_LOGIN_IP_MAX, s.LOGIN_RATE_LIMIT_WINDOW_SECONDS),
        "login_account": (s.RATE_LIMIT_LOGIN_ACCOUNT_MAX, s.LOGIN_RATE_LIMIT_WINDOW_SECONDS),
        "signup_ip": (s.RATE_LIMIT_SIGNUP_IP_MAX, s.RATE_LIMIT_SIGNUP_WINDOW_SECONDS),
        "refresh_ip": (s.RATE_LIMIT_REFRESH_IP_MAX, s.RATE_LIMIT_REFRESH_WINDOW_SECONDS),
        "invite_user": (s.RATE_LIMIT_INVITE_USER_MAX, s.RATE_LIMIT_INVITE_WINDOW_SECONDS),
        "join_user": (s.RATE_LIMIT_JOIN_USER_MAX, s.RATE_LIMIT_JOIN_WINDOW_SECONDS),
        "join_code_user": (s.RATE_LIMIT_JOIN_CODE_USER_MAX, s.RATE_LIMIT_JOIN_CODE_WINDOW_SECONDS),
        "invite_respond_user": (
            s.RATE_LIMIT_INVITE_RESPOND_USER_MAX,
            s.RATE_LIMIT_INVITE_RESPOND_WINDOW_SECONDS,
        ),
        "ai_burst_user": (s.RATE_LIMIT_AI_BURST_USER_MAX, s.RATE_LIMIT_AI_WINDOW_SECONDS),
        "ai_feedback_user": (s.RATE_LIMIT_AI_FEEDBACK_USER_MAX, s.RATE_LIMIT_AI_WINDOW_SECONDS),
    }
    limit, window = table[name]
    return Policy(scope=name, limit=limit, window_seconds=window)


# --------------------------------------------------------------------------------------
# Time, hashing, windows
# --------------------------------------------------------------------------------------


def _now() -> datetime:
    """Current UTC time (a seam so tests can move the clock)."""
    return datetime.now(UTC)


def _hash_key() -> bytes:
    # Derived from the JWT secret with a fixed context, so no extra secret is needed and
    # stored hashes cannot be reversed with a plain dictionary of emails or addresses.
    return hmac.new(
        settings.JWT_SECRET_KEY.encode("utf-8"), b"rate-limit-v1", hashlib.sha256
    ).digest()


def hash_identifier(scope: str, identifier: str) -> str:
    return hmac.new(_hash_key(), f"{scope}:{identifier}".encode("utf-8"), hashlib.sha256).hexdigest()


def window_bounds(policy: Policy, at: datetime) -> tuple[datetime, datetime]:
    """Fixed window containing ``at``, aligned to the Unix epoch (same on every worker)."""
    epoch = int(at.timestamp())
    start_epoch = epoch - (epoch % policy.window_seconds)
    start = datetime.fromtimestamp(start_epoch, UTC)
    return start, start + timedelta(seconds=policy.window_seconds)


# --------------------------------------------------------------------------------------
# Store layer (PostgreSQL). Tests of the HTTP layer may replace these four functions.
# --------------------------------------------------------------------------------------


async def _store_increment(
    scope: str, identifier_hash: str, window_start: datetime, expires_at: datetime
) -> int:
    """Atomically add one to the bucket (creating it at 1) and return the new count."""
    now = _now()
    stmt = (
        pg_insert(RateLimitBucket)
        .values(
            scope=scope,
            identifier_hash=identifier_hash,
            window_start=window_start,
            count=1,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["scope", "identifier_hash", "window_start"],
            set_={"count": RateLimitBucket.count + 1, "updated_at": now},
        )
        .returning(RateLimitBucket.count)
    )
    async with AsyncSessionLocal() as session:
        count = (await session.execute(stmt)).scalar_one()
        await session.commit()
    return int(count)


async def _store_decrement(scope: str, identifier_hash: str, window_start: datetime) -> None:
    stmt = (
        update(RateLimitBucket)
        .where(
            RateLimitBucket.scope == scope,
            RateLimitBucket.identifier_hash == identifier_hash,
            RateLimitBucket.window_start == window_start,
        )
        .values(count=func.greatest(RateLimitBucket.count - 1, 0), updated_at=_now())
    )
    async with AsyncSessionLocal() as session:
        await session.execute(stmt)
        await session.commit()


async def _store_clear(scope: str, identifier_hash: str) -> None:
    stmt = delete(RateLimitBucket).where(
        RateLimitBucket.scope == scope, RateLimitBucket.identifier_hash == identifier_hash
    )
    async with AsyncSessionLocal() as session:
        await session.execute(stmt)
        await session.commit()


async def _store_purge(cutoff: datetime, batch: int) -> int:
    """Delete up to ``batch`` buckets that expired before ``cutoff``."""
    expired = (
        select(
            RateLimitBucket.scope, RateLimitBucket.identifier_hash, RateLimitBucket.window_start
        )
        .where(RateLimitBucket.expires_at < cutoff)
        .limit(batch)
    )
    stmt = delete(RateLimitBucket).where(
        tuple_(
            RateLimitBucket.scope, RateLimitBucket.identifier_hash, RateLimitBucket.window_start
        ).in_(expired)
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        await session.commit()
    return result.rowcount or 0


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------


def _error(status_code: int, code: str, message: str, headers: Optional[dict[str, str]] = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
        headers=headers,
    )


def rate_limit_exceeded(retry_after: int, message: Optional[str] = None) -> HTTPException:
    retry_after = max(1, int(retry_after))
    text = message or "Too many requests. Please try again in {n} seconds."
    return _error(
        status.HTTP_429_TOO_MANY_REQUESTS,
        RATE_LIMIT_EXCEEDED,
        text.format(n=retry_after),
        {"Retry-After": str(retry_after)},
    )


def limiter_unavailable() -> HTTPException:
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        RATE_LIMITER_UNAVAILABLE,
        "The service is temporarily unable to process this request. Please try again shortly.",
    )


async def hit(policy: Policy, identifier: str) -> Hit:
    """Reserve one slot in the policy's current window. Raises RateLimiterUnavailable."""
    at = _now()
    start, end = window_bounds(policy, at)
    identifier_hash = hash_identifier(policy.scope, identifier)
    try:
        count = await _store_increment(
            policy.scope, identifier_hash, start, end + timedelta(seconds=60)
        )
    except Exception as exc:  # noqa: BLE001 - any store failure means "unavailable"
        raise RateLimiterUnavailable(type(exc).__name__) from exc
    retry_after = max(1, math.ceil((end - at).total_seconds()))
    return Hit(policy, identifier_hash, start, count, retry_after)


async def reserve(
    checks: Sequence[tuple[Policy, str]],
    *,
    message: Optional[str] = None,
) -> list[Hit]:
    """Count one request against every (policy, identifier) check.

    Raises HTTP 429 (largest Retry-After among the exceeded checks) when any limit is
    exceeded, or HTTP 503 when the counters are unavailable (fail closed, always).
    """
    if not settings.RATE_LIMIT_ENABLED or not checks:
        return []
    hits: list[Hit] = []
    for policy, identifier in checks:
        try:
            hits.append(await hit(policy, identifier))
        except RateLimiterUnavailable as exc:
            logger.error("Rate limiter unavailable scope=%s cause=%s", policy.scope, exc)
            raise limiter_unavailable() from exc
    exceeded = [h for h in hits if h.exceeded]
    if exceeded:
        logger.warning("Rate limit exceeded scopes=%s", ",".join(h.policy.scope for h in exceeded))
        raise rate_limit_exceeded(max(h.retry_after for h in exceeded), message)
    await _maybe_purge()
    return hits


async def refund(hits: Sequence[Hit], scopes: Optional[set[str]] = None) -> None:
    """Give back reserved slots (for example after a successful login). Never raises."""
    for h in hits:
        if scopes is not None and h.policy.scope not in scopes:
            continue
        try:
            await _store_decrement(h.policy.scope, h.identifier_hash, h.window_start)
        except Exception as exc:  # noqa: BLE001
            logger.error("Rate limit refund failed scope=%s cause=%s", h.policy.scope, type(exc).__name__)


async def clear(policy: Policy, identifier: str) -> None:
    """Delete every window of one counter (for example after a successful login). Never raises."""
    try:
        await _store_clear(policy.scope, hash_identifier(policy.scope, identifier))
    except Exception as exc:  # noqa: BLE001
        logger.error("Rate limit clear failed scope=%s cause=%s", policy.scope, type(exc).__name__)


async def purge_expired(batch: Optional[int] = None) -> int:
    """Delete one batch of expired counters. Returns the number removed."""
    return await _store_purge(_now(), batch or settings.RATE_LIMIT_PURGE_BATCH)


async def _maybe_purge() -> None:
    if random.random() >= settings.RATE_LIMIT_PURGE_PROBABILITY:
        return
    try:
        await purge_expired()
    except Exception as exc:  # noqa: BLE001 - cleanup must never affect a request
        logger.warning("Rate limit purge failed cause=%s", type(exc).__name__)


# --------------------------------------------------------------------------------------
# Client address
# --------------------------------------------------------------------------------------

_warned_no_trusted_header = False


def get_client_ip(request: Request) -> Optional[str]:
    """The client address from the configured trusted header, or None.

    Never reads X-Forwarded-For or ``request.client``: with the current Render start command
    (``--forwarded-allow-ips='*'``) uvicorn copies the caller-controlled leftmost
    X-Forwarded-For entry into ``request.client``. The header must hold exactly one valid IP;
    anything else (a list, garbage, empty) is treated as "unknown".
    """
    header = settings.TRUSTED_CLIENT_IP_HEADER
    if not header:
        _warn_no_trusted_header()
        return None
    raw = request.headers.get(header)
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw.strip()))
    except ValueError:
        logger.warning("Ignoring invalid value in trusted client IP header %s", header)
        return None


def _warn_no_trusted_header() -> None:
    global _warned_no_trusted_header
    if not _warned_no_trusted_header:
        _warned_no_trusted_header = True
        logger.warning(
            "TRUSTED_CLIENT_IP_HEADER is not set: address-scoped rate limits are skipped. "
            "See docs/RATE_LIMITING_AND_CSRF.md."
        )
