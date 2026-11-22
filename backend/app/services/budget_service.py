"""Budgets (US-25 / T-48): limits, current-period progress and threshold alerts.

Rules
-----
A budget belongs to one user: a period (weekly or monthly), a limit in integer paise and
either one category or none (overall). At most one active budget exists per (user,
period, category or overall); a second one is ``409 BUDGET_EXISTS``. Only the owner can
see or change a budget (``BudgetPolicy``: anyone else gets 404).

Spending
--------
Spent is the user's SHARE of every live expense dated in the period, read through the
analytics aggregation (``analytics_service.ledger_rows``): a personal expense counts in
full, a shared expense counts the user's ``expense_shares`` row. Cash paid, settlements
and soft-deleted expenses never count.

Periods
-------
"Today" is decided in Asia/Kolkata. A weekly budget covers Monday to Sunday, a monthly
budget the calendar month (``analytics_service.bucket_start``/``bucket_end``). Expense
dates are calendar days picked in Asia/Kolkata, so they are compared directly.

Thresholds
----------
Integer maths only: 80% is reached when ``spent * 100 >= limit * 80``, 100% when
``spent >= limit``; ``percent_used`` is ``floor(spent * 100 / limit)``. Status is
``under`` (< 80%), ``warning`` (80% to < 100%) or ``exceeded`` (>= 100%).

Alerts (once per threshold per period)
--------------------------------------
``check_after_commit()`` runs AFTER a change that can move a user's spending has
committed (personal expense create/update/delete/restore, shared expense create/update/
delete for every user whose share changed, recurring-generated expenses, budget create
and limit change). It never raises: a failing check is logged and the saved record stays.

For each active budget it measures the CURRENT period and inserts one
``budget_alerts`` row per reached threshold with ``INSERT ... ON CONFLICT DO NOTHING``
on the UNIQUE ``(budget_id, period_start, threshold)`` key. Only the request whose insert
lands announces the alert, so concurrent saves can never alert twice; the notification
centre's ``(user_id, dedupe_key)`` key is a second guard. When spending jumps straight past
100% the 80% row is stored as ``suppressed`` and only the 100% alert is sent.

Going back under a threshold (an edit, a delete, a higher limit) shows in progress and
status at once, but the alert rows stay: crossing the same threshold again in the same
period does not alert again. A new period has new keys, so it starts fresh.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import BigInteger, cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import Action, BudgetPolicy, CategoryPolicy
from app.core.database import AsyncSessionLocal
from app.models.budget import ALERT_THRESHOLDS, Budget, BudgetAlert
from app.models.category import Category
from app.models.user import User
from app.schemas.analytics import Granularity
from app.schemas.budget import (
    BudgetCreate,
    BudgetProgress,
    BudgetResponse,
    BudgetStatus,
    BudgetUpdate,
)
from app.services import idempotency, notifications
from app.services.analytics_service import AnalyticsFilter, AnySelect, bucket_end, bucket_start, ledger_rows
from app.services.settlement_service import IST

logger = logging.getLogger("app.budgets")

WARNING_THRESHOLD, EXCEEDED_THRESHOLD = ALERT_THRESHOLDS
KIND_FOR_THRESHOLD: dict[int, str] = {
    WARNING_THRESHOLD: "budget_warning",
    EXCEEDED_THRESHOLD: "budget_exceeded",
}
_GRANULARITY: dict[str, Granularity] = {"weekly": "week", "monthly": "month"}

#: execution_options key carrying the spending query's filter (used by test fakes;
#: PostgreSQL ignores user-defined execution options).
SPENDING_OPTION = "budget_spending"


# ==============================================================================
# Clock (replaced by tests)
# ==============================================================================


def _now() -> datetime:
    return datetime.now(UTC)


def today_in_kolkata(now: datetime | None = None) -> date:
    return (now or _now()).astimezone(IST).date()


# ==============================================================================
# Periods and thresholds (pure)
# ==============================================================================


def period_bounds(period: str, day: date) -> tuple[date, date]:
    """The (first, last) day of the weekly (Monday to Sunday) or monthly period holding ``day``."""
    granularity = _GRANULARITY[period]
    start = bucket_start(day, granularity)
    return start, bucket_end(start, granularity)


def reached_thresholds(spent_paise: int, limit_paise: int) -> tuple[int, ...]:
    """Thresholds (percent of the limit) that spending has reached, lowest first."""
    return tuple(t for t in ALERT_THRESHOLDS if spent_paise * 100 >= limit_paise * t)


def status_for(spent_paise: int, limit_paise: int) -> BudgetStatus:
    reached = reached_thresholds(spent_paise, limit_paise)
    if EXCEEDED_THRESHOLD in reached:
        return "exceeded"
    if WARNING_THRESHOLD in reached:
        return "warning"
    return "under"


def build_progress(spent_paise: int, limit_paise: int, start: date, end: date) -> BudgetProgress:
    return BudgetProgress(
        period_start=start,
        period_end=end,
        spent_paise=spent_paise,
        remaining_paise=limit_paise - spent_paise,
        over_by_paise=max(spent_paise - limit_paise, 0),
        percent_used=spent_paise * 100 // limit_paise,
        status=status_for(spent_paise, limit_paise),
    )


def alerts_to_record(spent_paise: int, limit_paise: int) -> list[tuple[int, bool]]:
    """(threshold, suppressed) rows to try to insert for this spending.

    At 100% or more the 80% row is suppressed: if it is new, spending jumped straight past
    100% and only the 100% alert is sent; if it already exists the insert is a no-op.
    """
    reached = reached_thresholds(spent_paise, limit_paise)
    return [(t, t != reached[-1]) for t in reached]


# ==============================================================================
# Spending (the analytics aggregation, summed per category)
# ==============================================================================


def spending_statement(user_id: uuid.UUID, start: date, end: date) -> AnySelect:
    """The user's share per category for expenses dated start..end (inclusive)."""
    f = AnalyticsFilter(user_id=user_id, start=start, end=end)
    rows = ledger_rows(f)
    stmt = select(
        rows.c.category_id,
        cast(func.coalesce(func.sum(rows.c.share_paise), 0), BigInteger).label("share_paise"),
    ).group_by(rows.c.category_id)
    return stmt.execution_options(**{SPENDING_OPTION: {"filter": f}})


async def spending_by_category(
    db: AsyncSession, user_id: uuid.UUID, start: date, end: date
) -> dict[uuid.UUID, int]:
    result = await db.execute(spending_statement(user_id, start, end))
    return {row.category_id: int(row.share_paise) for row in result.all()}


def spent_for(budget: Budget, by_category: dict[uuid.UUID, int]) -> int:
    if budget.category_id is None:
        return sum(by_category.values())
    return by_category.get(budget.category_id, 0)


@dataclass(frozen=True)
class Measured:
    budget: Budget
    start: date
    end: date
    spent_paise: int


async def measure(db: AsyncSession, user_id: uuid.UUID, budgets: list[Budget], today: date) -> list[Measured]:
    """Current-period spending for each budget (one spending query per period in use)."""
    cache: dict[tuple[date, date], dict[uuid.UUID, int]] = {}
    measured: list[Measured] = []
    for budget in budgets:
        start, end = period_bounds(budget.period, today)
        if (start, end) not in cache:
            cache[(start, end)] = await spending_by_category(db, user_id, start, end)
        measured.append(Measured(budget, start, end, spent_for(budget, cache[(start, end)])))
    return measured


def to_response(m: Measured) -> BudgetResponse:
    b = m.budget
    return BudgetResponse(
        id=b.id,
        period=b.period,  # type: ignore[arg-type]
        category_id=b.category_id,
        limit_paise=b.limit_paise,
        created_at=b.created_at,
        updated_at=b.updated_at,
        progress=build_progress(m.spent_paise, b.limit_paise, m.start, m.end),
    )


async def _respond(db: AsyncSession, user: User, budget: Budget) -> BudgetResponse:
    return to_response((await measure(db, user.id, [budget], today_in_kolkata()))[0])


# ==============================================================================
# CRUD
# ==============================================================================


def _exists() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "BUDGET_EXISTS",
            "message": "You already have an active budget for this period and category.",
        },
    )


async def _validate_category(db: AsyncSession, user: User, category_id: uuid.UUID) -> None:
    """A default category or one of the user's own; anything else is 400 INVALID_CATEGORY."""
    stmt = CategoryPolicy.scope_query(select(Category).where(Category.id == category_id), user.id)
    category = (await db.execute(stmt)).scalar_one_or_none()
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_CATEGORY",
                "message": f"Category '{category_id}' does not exist or is not accessible.",
            },
        )
    CategoryPolicy.authorize(user, category, Action.READ)


async def _active_duplicate(db: AsyncSession, user: User, period: str, category_id: uuid.UUID | None) -> bool:
    stmt = BudgetPolicy.scope_query(select(Budget.id).where(Budget.period == period), user.id)
    if category_id is None:
        stmt = stmt.where(Budget.category_id.is_(None))
    else:
        stmt = stmt.where(Budget.category_id == category_id)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def _load_owned(db: AsyncSession, user: User, budget_id: uuid.UUID, *, for_update: bool = False) -> Budget:
    stmt = BudgetPolicy.scope_query(select(Budget).where(Budget.id == budget_id), user.id)
    if for_update:
        stmt = stmt.with_for_update()
    budget = (await db.execute(stmt)).scalar_one_or_none()
    return BudgetPolicy.authorize(user, budget)


async def create_budget(
    db: AsyncSession,
    user: User,
    payload: BudgetCreate,
    idempotency_key: str | None = None,
) -> tuple[BudgetResponse, bool]:
    """Create a budget. Returns (response, is_replay). Thresholds are checked after the commit."""
    key, hashed, replay = await idempotency.prepare(
        db, user.id, idempotency_key, "budget_create", None, payload, BudgetResponse
    )
    if replay is not None:
        return replay, True

    if payload.category_id is not None:
        await _validate_category(db, user, payload.category_id)
    if await _active_duplicate(db, user, payload.period, payload.category_id):
        raise _exists()

    now = _now()
    budget = Budget(
        id=uuid.uuid4(),
        user_id=user.id,
        period=payload.period,
        category_id=payload.category_id,
        limit_paise=payload.limit_paise,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    db.add(budget)
    response = await _respond(db, user, budget)
    if key and hashed:
        idempotency.stage_record(db, user.id, key, hashed, response, budget.id)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # A concurrent retry with the same key committed first: replay its response.
        replay = await idempotency.replay_after_conflict(db, user.id, key, hashed, BudgetResponse)
        if replay is not None:
            return replay, True
        # Otherwise a concurrent create won the partial unique index.
        raise _exists() from exc

    await check_after_commit([user.id])
    return response, False


async def list_budgets(db: AsyncSession, user: User, limit: int, offset: int) -> tuple[list[BudgetResponse], int]:
    """The user's active budgets, oldest first, each with its current-period progress."""
    base = BudgetPolicy.scope_query(select(Budget), user.id)
    total = (
        await db.execute(BudgetPolicy.scope_query(select(func.count(Budget.id)), user.id))
    ).scalar_one()
    budgets = list(
        (await db.execute(base.order_by(Budget.created_at, Budget.id).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    measured = await measure(db, user.id, budgets, today_in_kolkata())
    return [to_response(m) for m in measured], int(total or 0)


async def get_budget(db: AsyncSession, user: User, budget_id: uuid.UUID) -> BudgetResponse:
    return await _respond(db, user, await _load_owned(db, user, budget_id))


async def update_budget(
    db: AsyncSession, user: User, budget_id: uuid.UUID, payload: BudgetUpdate
) -> BudgetResponse:
    """Change the limit. A lower limit can alert at once; a higher one never removes an alert."""
    budget = await _load_owned(db, user, budget_id, for_update=True)
    budget.limit_paise = payload.limit_paise
    budget.updated_at = _now()
    await db.commit()
    await check_after_commit([user.id])
    return await _respond(db, user, budget)


async def delete_budget(db: AsyncSession, user: User, budget_id: uuid.UUID) -> None:
    """Soft-delete: the budget stops counting and frees its (period, category) slot."""
    budget = await _load_owned(db, user, budget_id, for_update=True)
    now = _now()
    budget.deleted_at = now
    budget.updated_at = now
    await db.commit()


# ==============================================================================
# Threshold checks (post-commit; never raise)
# ==============================================================================


@dataclass(frozen=True)
class Announcement:
    user_id: uuid.UUID
    budget_id: uuid.UUID
    threshold: int
    dedupe_key: str
    payload: dict[str, Any]


def dedupe_key(budget_id: uuid.UUID, period_start: date, threshold: int) -> str:
    return f"budget_threshold:{budget_id}:{period_start.isoformat()}:{threshold}"


def _parse_ids(user_ids: Iterable[uuid.UUID | str]) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for value in user_ids:
        try:
            parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            logger.error("Budget check skipped an invalid user id")
            continue
        if parsed not in ids:
            ids.append(parsed)
    return ids


async def check_after_commit(user_ids: Iterable[uuid.UUID | str]) -> None:
    """Check every active budget of these users. Call AFTER the change has committed.

    Never raises: a failure is logged and the caller's saved record is kept.
    """
    try:
        ids = _parse_ids(user_ids)
        if ids:
            await _check_users(ids)
    except Exception as exc:  # noqa: BLE001 - never fail a committed request because of a budget check
        logger.error("Budget check failed; the saved record is kept (%s)", type(exc).__name__)
        logger.debug("Budget check failed - traceback", exc_info=exc)


async def _check_users(user_ids: list[uuid.UUID]) -> None:
    """Record reached thresholds in their own transaction, then announce the new ones."""
    today = today_in_kolkata()
    for user_id in user_ids:
        try:
            async with AsyncSessionLocal() as session:
                announcements = await _record_alerts(session, user_id, today)
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - one user's failure must not block the others
            logger.error("Budget check failed for user=%s (%s)", user_id, type(exc).__name__)
            logger.debug("Budget check failed - traceback", exc_info=exc)
            continue
        for a in announcements:
            await notifications.emit(
                a.user_id,
                KIND_FOR_THRESHOLD[a.threshold],
                str(a.budget_id),
                a.dedupe_key,
                a.payload,
            )


async def _record_alerts(session: AsyncSession, user_id: uuid.UUID, today: date) -> list[Announcement]:
    budgets = list(
        (await session.execute(BudgetPolicy.scope_query(select(Budget), user_id).order_by(Budget.created_at)))
        .scalars()
        .all()
    )
    if not budgets:
        return []

    names: dict[uuid.UUID, str] | None = None
    announcements: list[Announcement] = []
    for m in await measure(session, user_id, budgets, today):
        b = m.budget
        for threshold, suppressed in alerts_to_record(m.spent_paise, b.limit_paise):
            inserted = (
                await session.execute(
                    pg_insert(BudgetAlert)
                    .values(
                        id=uuid.uuid4(),
                        budget_id=b.id,
                        period_start=m.start,
                        period_end=m.end,
                        threshold=threshold,
                        spent_paise=m.spent_paise,
                        limit_paise=b.limit_paise,
                        suppressed=suppressed,
                        created_at=_now(),
                    )
                    .on_conflict_do_nothing(index_elements=["budget_id", "period_start", "threshold"])
                    .returning(BudgetAlert.id)
                )
            ).scalar_one_or_none()
            if inserted is None or suppressed:
                continue
            if b.category_id is not None and names is None:
                names = await _category_names(session, budgets)
            announcements.append(
                Announcement(
                    user_id=user_id,
                    budget_id=b.id,
                    threshold=threshold,
                    dedupe_key=dedupe_key(b.id, m.start, threshold),
                    payload={
                        "budget_id": str(b.id),
                        "period": b.period,
                        "period_start": m.start.isoformat(),
                        "period_end": m.end.isoformat(),
                        "category_id": str(b.category_id) if b.category_id else None,
                        "category_name": (names or {}).get(b.category_id) if b.category_id else None,
                        "threshold": threshold,
                        "spent_paise": m.spent_paise,
                        "limit_paise": b.limit_paise,
                        "percent_used": m.spent_paise * 100 // b.limit_paise,
                    },
                )
            )
    return announcements


async def _category_names(session: AsyncSession, budgets: list[Budget]) -> dict[uuid.UUID, str]:
    ids = {b.category_id for b in budgets if b.category_id is not None}
    result = await session.execute(select(Category.id, Category.name).where(Category.id.in_(ids)))
    return {cid: name for cid, name in result.all()}
