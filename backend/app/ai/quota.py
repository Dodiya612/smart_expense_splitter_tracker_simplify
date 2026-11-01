"""AI Quota and Usage Logging Service (S2-AI-01).

Implements per-user daily limits per AI feature, database-backed atomic quota
reservations across multiple workers/processes, PostgreSQL advisory locking,
UTC midnight quota reset, global AI_ENABLED toggle, and persistent usage logging
to the ai_usage_log table.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai_usage_log import AIUsageLog

logger = logging.getLogger(__name__)

VALID_FEATURES: frozenset[str] = frozenset(
    {"categorize", "receipt", "budget_goals", "ask"}
)

VALID_STATUSES: frozenset[str] = frozenset(
    {"pending", "success", "quota_exceeded", "error"}
)


def get_utc_day_start() -> datetime:
    """Return the start of the current day (00:00:00) in UTC."""
    return datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def get_daily_limit_for_feature(feature: str) -> int:
    """Retrieve the configured daily quota for the specified AI feature."""
    if feature == "categorize":
        return settings.AI_QUOTA_CATEGORIZE_DAILY
    elif feature == "receipt":
        return settings.AI_QUOTA_RECEIPT_DAILY
    elif feature == "budget_goals":
        return settings.AI_QUOTA_BUDGET_GOALS_DAILY
    elif feature == "ask":
        return settings.AI_QUOTA_ASK_DAILY
    else:
        raise ValueError(
            f"Unknown AI feature: '{feature}'. Valid features are: {sorted(VALID_FEATURES)}"
        )


@dataclass(frozen=True)
class QuotaStatus:
    """Immutable status snapshot of a user's quota for a specific feature."""

    feature: str
    allowed: bool
    used_today: int
    daily_limit: int
    remaining: int
    is_ai_enabled: bool
    reason: str | None = None


@dataclass
class QuotaReservation:
    """Active quota reservation ticket holding a slot across workers/processes."""

    status: QuotaStatus
    reservation_id: uuid.UUID | None = None
    _finalized: bool = False
    _db: AsyncSession | None = None

    @property
    def allowed(self) -> bool:
        return self.status.allowed

    @property
    def remaining(self) -> int:
        return self.status.remaining

    @property
    def used_today(self) -> int:
        return self.status.used_today

    @property
    def daily_limit(self) -> int:
        return self.status.daily_limit

    @property
    def is_ai_enabled(self) -> bool:
        return self.status.is_ai_enabled

    @property
    def reason(self) -> str | None:
        return self.status.reason

    async def finalize(
        self,
        status: str = "success",
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_ms: float | None = None,
        error_message: str | None = None,
        db: AsyncSession | None = None,
    ) -> AIUsageLog | None:
        """Finalize the pending reservation row to success or error."""
        self._finalized = True
        target_db = db or self._db
        if self.reservation_id is None:
            return None

        if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens

        return await _finalize_reservation(
            reservation_id=self.reservation_id,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            error_message=error_message,
            db=target_db,
        )


async def _finalize_reservation(
    reservation_id: uuid.UUID,
    status: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    latency_ms: float | None = None,
    error_message: str | None = None,
    db: AsyncSession | None = None,
) -> AIUsageLog | None:
    """Update a pending AIUsageLog reservation row with outcome metrics."""
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status: '{status}'. Valid statuses are: {sorted(VALID_STATUSES)}"
        )

    stmt = (
        update(AIUsageLog)
        .where(AIUsageLog.id == reservation_id)
        .values(
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            error_message=error_message[:1000] if error_message else None,
        )
        .returning(AIUsageLog)
    )

    if db is not None:
        try:
            result = await db.execute(stmt)
            await db.commit()
            return result.scalar_one_or_none()
        except SQLAlchemyError as exc:
            logger.warning("Failed to finalize AIUsageLog reservation %s: %s", reservation_id, exc)
            return None

    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            result = await session.execute(stmt)
            await session.commit()
            return result.scalar_one_or_none()
    except (SQLAlchemyError, OSError, RuntimeError) as exc:
        logger.warning(
            "Unable to acquire database session to finalize AIUsageLog reservation: %s", exc
        )
        return None


class AIQuotaService:
    """Manager for daily AI quotas with distributed database-backed atomic reservations."""

    def __init__(self) -> None:
        self._reservations: dict[tuple[uuid.UUID, str], int] = {}
        self._locks: dict[tuple[uuid.UUID, str], asyncio.Lock] = {}

    def _get_lock(self, user_id: uuid.UUID, feature: str) -> asyncio.Lock:
        key = (user_id, feature)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def get_usage_count(
        self,
        db: AsyncSession | None,
        user_id: uuid.UUID,
        feature: str,
        since: datetime | None = None,
        include_pending: bool = False,
        pending_cutoff: datetime | None = None,
    ) -> int:
        """Count authoritative successful (and optionally active pending) calls today.

        Pending reservations older than 2 minutes are treated as stale/abandoned and ignored.
        """
        if feature not in VALID_FEATURES:
            raise ValueError(f"Unknown AI feature: '{feature}'")

        cutoff = since if since is not None else get_utc_day_start()
        stale_cutoff = pending_cutoff or (datetime.now(UTC) - timedelta(minutes=2))

        condition = (AIUsageLog.status == "success")
        if include_pending:
            condition = or_(
                AIUsageLog.status == "success",
                (AIUsageLog.status == "pending") & (AIUsageLog.created_at >= stale_cutoff),
            )

        if db is not None:
            try:
                stmt = select(func.count(AIUsageLog.id)).where(
                    AIUsageLog.user_id == user_id,
                    AIUsageLog.feature == feature,
                    AIUsageLog.created_at >= cutoff,
                    condition,
                )
                result = await db.execute(stmt)
                return int(result.scalar_one_or_none() or 0)
            except SQLAlchemyError as exc:
                logger.warning(
                    "Database error querying AI usage count for user %s (%s): %s",
                    user_id,
                    feature,
                    exc,
                )
                return 0

        try:
            from app.core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                stmt = select(func.count(AIUsageLog.id)).where(
                    AIUsageLog.user_id == user_id,
                    AIUsageLog.feature == feature,
                    AIUsageLog.created_at >= cutoff,
                    condition,
                )
                result = await session.execute(stmt)
                return int(result.scalar_one_or_none() or 0)
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            logger.warning(
                "Unable to obtain database session for AI quota check: %s", exc
            )
            return 0

    async def check_quota(
        self,
        user_id: uuid.UUID,
        feature: str,
        db: AsyncSession | None = None,
        raise_on_exceeded: bool = True,
    ) -> QuotaStatus:
        """Inspect current quota availability without acquiring a persistent reservation."""
        if feature not in VALID_FEATURES:
            raise ValueError(f"Unknown AI feature: '{feature}'")

        limit = get_daily_limit_for_feature(feature)
        is_enabled = settings.AI_ENABLED

        if not is_enabled:
            return QuotaStatus(
                feature=feature,
                allowed=False,
                used_today=0,
                daily_limit=limit,
                remaining=0,
                is_ai_enabled=False,
                reason="AI_DISABLED",
            )

        used = await self.get_usage_count(
            db=db,
            user_id=user_id,
            feature=feature,
            include_pending=True,
        )
        in_flight = self._reservations.get((user_id, feature), 0) if db is None else 0
        effective_used = used + in_flight
        remaining = max(0, limit - effective_used)
        allowed = remaining > 0

        if not allowed and raise_on_exceeded:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "AI_QUOTA_EXCEEDED",
                    "message": f"Daily AI quota exceeded for {feature}. Resets at midnight UTC.",
                    "detail": None,
                },
            )

        return QuotaStatus(
            feature=feature,
            allowed=allowed,
            used_today=used,
            daily_limit=limit,
            remaining=remaining,
            is_ai_enabled=True,
            reason=None if allowed else "QUOTA_EXCEEDED",
        )

    @asynccontextmanager
    async def reserve(
        self,
        user_id: uuid.UUID,
        feature: str,
        db: AsyncSession | None = None,
        provider: str = "groq",
        model: str = settings.GROQ_MODEL,
        raise_on_exceeded: bool = True,
    ) -> AsyncGenerator[QuotaReservation, None]:
        """Atomically reserve an execution slot across Uvicorn workers and processes.

        Uses PostgreSQL advisory transactions where supported, inserts an active
        'pending' row in ai_usage_log so all workers observe the in-flight reservation,
        and provides automatic rollback if unfinalized.
        """
        if feature not in VALID_FEATURES:
            raise ValueError(f"Unknown AI feature: '{feature}'")

        limit = get_daily_limit_for_feature(feature)
        is_enabled = settings.AI_ENABLED

        if not is_enabled:
            unallowed_status = QuotaStatus(
                feature=feature,
                allowed=False,
                used_today=0,
                daily_limit=limit,
                remaining=0,
                is_ai_enabled=False,
                reason="AI_DISABLED",
            )
            yield QuotaReservation(status=unallowed_status, _db=db)
            return

        # Fast process-local lock to coordinate local tasks
        process_lock = self._get_lock(user_id, feature)
        async with process_lock:
            # 1. Acquire PostgreSQL advisory xact lock if connected to live PostgreSQL
            if db is not None:
                try:
                    bind = getattr(db, "bind", None)
                    dialect_name = getattr(getattr(bind, "dialect", None), "name", "")
                    if dialect_name == "postgresql":
                        lock_key = f"ai_quota:{user_id}:{feature}:{get_utc_day_start().date().isoformat()}"
                        await db.execute(
                            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                            {"lock_key": lock_key},
                        )
                except (SQLAlchemyError, OSError, RuntimeError) as exc:
                    logger.debug("PostgreSQL advisory lock skipped or unavailable: %s", exc)

            # 2. Inspect active usage including active pending reservations across all workers
            active_usage = await self.get_usage_count(
                db=db,
                user_id=user_id,
                feature=feature,
                include_pending=True,
            )
            in_flight = self._reservations.get((user_id, feature), 0) if db is None else 0
            effective_used = active_usage + in_flight

            if effective_used >= limit:
                unallowed_status = QuotaStatus(
                    feature=feature,
                    allowed=False,
                    used_today=active_usage,
                    daily_limit=limit,
                    remaining=0,
                    is_ai_enabled=True,
                    reason="QUOTA_EXCEEDED",
                )
                if raise_on_exceeded:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail={
                            "code": "AI_QUOTA_EXCEEDED",
                            "message": f"Daily AI quota exceeded for {feature}. Resets at midnight UTC.",
                            "detail": None,
                        },
                    )
                yield QuotaReservation(status=unallowed_status, _db=db)
                return

            # 3. Insert persistent pending reservation row into PostgreSQL
            pending_record = AIUsageLog(
                user_id=user_id,
                feature=feature,
                provider=provider,
                model=model,
                status="pending",
            )
            if db is not None:
                try:
                    db.add(pending_record)
                    await db.commit()
                    await db.refresh(pending_record)
                except SQLAlchemyError as exc:
                    logger.warning("Failed to persist pending AI reservation: %s", exc)

            # Record in-memory counter as defense-in-depth
            key = (user_id, feature)
            self._reservations[key] = self._reservations.get(key, 0) + 1

            allowed_status = QuotaStatus(
                feature=feature,
                allowed=True,
                used_today=active_usage,
                daily_limit=limit,
                remaining=max(0, limit - (effective_used + 1)),
                is_ai_enabled=True,
                reason=None,
            )
            reservation = QuotaReservation(
                status=allowed_status,
                reservation_id=pending_record.id,
                _db=db,
            )

        try:
            yield reservation
        finally:
            async with process_lock:
                key = (user_id, feature)
                current = self._reservations.get(key, 0)
                if current <= 1:
                    self._reservations.pop(key, None)
                else:
                    self._reservations[key] = current - 1

            # If user block aborted/errored without finalizing, mark pending record as error
            if not reservation._finalized and reservation.reservation_id is not None:
                await _finalize_reservation(
                    reservation_id=reservation.reservation_id,
                    status="error",
                    error_message="Reservation unfinalized or cancelled",
                    db=db,
                )

    def clear_in_memory_reservations(self) -> None:
        """Clear active in-flight reservations (for test isolation and resets)."""
        self._reservations.clear()


# Global Singleton Quota Service
_QUOTA_SERVICE: AIQuotaService = AIQuotaService()


def get_quota_service() -> AIQuotaService:
    """Retrieve the singleton AIQuotaService instance."""
    return _QUOTA_SERVICE


async def check_quota(
    user_id: uuid.UUID,
    feature: str,
    db: AsyncSession | None = None,
    raise_on_exceeded: bool = True,
) -> QuotaStatus:
    """Convenience helper to check quota on the singleton service."""
    return await _QUOTA_SERVICE.check_quota(
        user_id=user_id,
        feature=feature,
        db=db,
        raise_on_exceeded=raise_on_exceeded,
    )


async def log_ai_usage(
    user_id: uuid.UUID,
    feature: str,
    provider: str,
    model: str,
    status: str = "success",
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    latency_ms: float | None = None,
    error_message: str | None = None,
    db: AsyncSession | None = None,
) -> AIUsageLog | None:
    """Persist an audit log entry for an AI feature invocation.

    Ensures zero secret/prompt logging, calculates total tokens if omitted,
    and safely handles database exceptions without masking primary business failures.
    """
    if feature not in VALID_FEATURES:
        raise ValueError(f"Unknown AI feature: '{feature}'")

    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status: '{status}'. Valid statuses are: {sorted(VALID_STATUSES)}"
        )

    # Derive total tokens if prompt and completion are provided
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens

    log_entry = AIUsageLog(
        user_id=user_id,
        feature=feature,
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        status=status,
        error_message=error_message[:1000] if error_message else None,
    )

    if db is not None:
        try:
            db.add(log_entry)
            await db.commit()
            await db.refresh(log_entry)
            return log_entry
        except SQLAlchemyError as exc:
            logger.warning("Failed to persist AIUsageLog to database: %s", exc)
            return None

    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            session.add(log_entry)
            await session.commit()
            await session.refresh(log_entry)
            return log_entry
    except (SQLAlchemyError, OSError, RuntimeError) as exc:
        logger.warning(
            "Failed to acquire session to persist AIUsageLog: %s", exc
        )
        return None
