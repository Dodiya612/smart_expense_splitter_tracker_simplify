"""Analytics service (US-12 / T-42).

Spending is the user's SHARE of every expense; cash paid is what they actually
paid (ledger.md, PRODUCT.md section 05):

- Personal expense (``expenses.group_id IS NULL``, owner ``expenses.user_id``):
  share = cash paid = ``amount_minor`` (no payment or share rows exist).
- Shared expense (``expenses.group_id`` set): share = the user's
  ``expense_shares`` row, cash paid = the user's ``expense_payments`` rows.
- Settlements are never read here: a repayment is never spending or income.
- Soft-deleted expenses (``deleted_at IS NOT NULL``) are excluded.

Aggregation runs in PostgreSQL over integer paise. ``expense_date`` is a calendar
date the user picked in Asia/Kolkata, so buckets use ``date_trunc`` on that date
directly (no time-zone shift is needed or wanted); Asia/Kolkata decides "today"
for the default range. ``date_trunc('week', …)`` starts weeks on Monday (ISO).

"Owed to you" / "you owe" come from the ledger engine via
``settlement_service.compute_net_positions`` (never recomputed here).
There is no server-side cache: every request reads the current rows.
"""

from __future__ import annotations

import uuid
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Unpack

from fastapi import HTTPException, status
from sqlalchemy import BigInteger, Date, DateTime, Select, cast, func, literal, literal_column, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import ExpensePolicy, GroupPolicy
from app.models.category import Category
from app.models.expense import Expense, ExpensePayment, ExpenseShare
from app.models.group import Group, GroupMember
from app.models.user import User
from app.schemas.analytics import (
    AnalyticsCategoriesResponse,
    AnalyticsSummaryResponse,
    AnalyticsTrendsResponse,
    CategoryBreakdownItem,
    Granularity,
    TrendBucket,
)
from app.services import settlement_service
from app.services.group_service import get_group_or_404

MAX_RANGE_DAYS = 731  # two years, inclusive

#: Any SELECT, whatever its column types (SQLAlchemy 2.1 Select is variadic).
AnySelect = Select[Unpack[tuple[Any, ...]]]

#: execution_options key carrying the query kind and filter (used by test fakes;
#: PostgreSQL ignores user-defined execution options).
ANALYTICS_OPTION = "analytics"


# ---------------------------------------------------------------------------
# Range and buckets (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalyticsFilter:
    user_id: uuid.UUID
    start: date
    end: date
    group_id: uuid.UUID | None = None


def _bad_range(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": code, "message": message})


def resolve_range(from_date: date | None, to_date: date | None, today: date) -> tuple[date, date]:
    """Defaults: from = 1st of this month, to = today (Asia/Kolkata). Inclusive; max two years."""
    end = to_date or today
    start = from_date or end.replace(day=1)
    if start > end:
        raise _bad_range("INVALID_RANGE", "'from' must be on or before 'to'.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise _bad_range(
            "RANGE_TOO_LARGE", f"The range can be at most {MAX_RANGE_DAYS} days long."
        )
    return start, end


def bucket_start(d: date, granularity: Granularity) -> date:
    if granularity == "day":
        return d
    if granularity == "week":
        return d - timedelta(days=d.weekday())  # Monday
    return d.replace(day=1)


def bucket_end(start: date, granularity: Granularity) -> date:
    if granularity == "day":
        return start
    if granularity == "week":
        return start + timedelta(days=6)  # Sunday
    return start.replace(day=monthrange(start.year, start.month)[1])


def iter_bucket_starts(start: date, end: date, granularity: Granularity) -> list[date]:
    starts: list[date] = []
    current = bucket_start(start, granularity)
    while current <= end:
        starts.append(current)
        current = bucket_end(current, granularity) + timedelta(days=1)
    return starts


def build_series(
    totals: dict[date, tuple[int, int]],
    start: date,
    end: date,
    granularity: Granularity,
) -> list[TrendBucket]:
    """Every bucket in the range (empty ones as 0) with running totals."""
    buckets: list[TrendBucket] = []
    running_share = 0
    running_cash = 0
    for b_start in iter_bucket_starts(start, end, granularity):
        share, cash = totals.get(b_start, (0, 0))
        running_share += share
        running_cash += cash
        buckets.append(
            TrendBucket(
                bucket_start=b_start,
                bucket_end=bucket_end(b_start, granularity),
                share_paise=share,
                cash_paid_paise=cash,
                cumulative_share_paise=running_share,
                cumulative_cash_paid_paise=running_cash,
            )
        )
    return buckets


# ---------------------------------------------------------------------------
# SQL (aggregated in PostgreSQL)
# ---------------------------------------------------------------------------


def _zero() -> Any:
    return cast(literal(0), BigInteger)


def ledger_rows(f: AnalyticsFilter) -> Any:
    """One row per (expense, amount) that counts for the user: personal, share, payment legs."""
    in_range = (Expense.expense_date >= f.start, Expense.expense_date <= f.end)
    live = Expense.deleted_at.is_(None)

    share_leg = (
        select(
            Expense.id.label("expense_id"),
            Expense.expense_date.label("expense_date"),
            Expense.category_id.label("category_id"),
            cast(ExpenseShare.amount_paise, BigInteger).label("share_paise"),
            _zero().label("cash_paid_paise"),
        )
        .join(ExpenseShare, ExpenseShare.expense_id == Expense.id)
        .where(ExpenseShare.user_id == f.user_id, Expense.group_id.is_not(None), live, *in_range)
    )
    payment_leg = (
        select(
            Expense.id.label("expense_id"),
            Expense.expense_date.label("expense_date"),
            Expense.category_id.label("category_id"),
            _zero().label("share_paise"),
            cast(ExpensePayment.amount_paise, BigInteger).label("cash_paid_paise"),
        )
        .join(ExpensePayment, ExpensePayment.expense_id == Expense.id)
        .where(ExpensePayment.user_id == f.user_id, Expense.group_id.is_not(None), live, *in_range)
    )
    if f.group_id is not None:
        share_leg = share_leg.where(Expense.group_id == f.group_id)
        payment_leg = payment_leg.where(Expense.group_id == f.group_id)
        return union_all(share_leg, payment_leg).subquery("analytics_rows")

    # Personal expenses are scoped by the expense policy (owner only, soft-deleted excluded).
    personal_leg = ExpensePolicy.scope_query(
        select(
            Expense.id.label("expense_id"),
            Expense.expense_date.label("expense_date"),
            Expense.category_id.label("category_id"),
            cast(Expense.amount_minor, BigInteger).label("share_paise"),
            cast(Expense.amount_minor, BigInteger).label("cash_paid_paise"),
        ),
        f.user_id,
    ).where(Expense.group_id.is_(None), *in_range)
    return union_all(personal_leg, share_leg, payment_leg).subquery("analytics_rows")


def _tag(stmt: AnySelect, kind: str, f: AnalyticsFilter, **extra: Any) -> AnySelect:
    return stmt.execution_options(**{ANALYTICS_OPTION: {"kind": kind, "filter": f, **extra}})


def summary_statement(f: AnalyticsFilter) -> AnySelect:
    rows = ledger_rows(f)
    stmt = select(
        func.coalesce(func.sum(rows.c.share_paise), 0).label("share_paise"),
        func.coalesce(func.sum(rows.c.cash_paid_paise), 0).label("cash_paid_paise"),
        func.count(func.distinct(rows.c.expense_id)).label("expense_count"),
    )
    return _tag(stmt, "summary", f)


def trends_statement(f: AnalyticsFilter, granularity: Granularity) -> AnySelect:
    rows = ledger_rows(f)
    # granularity is one of the Literal values, so the inline SQL literal is safe.
    unit: Any = literal_column(f"'{granularity}'")
    bucket = cast(func.date_trunc(unit, cast(rows.c.expense_date, DateTime)), Date).label("bucket_start")
    stmt = (
        select(
            bucket,
            func.coalesce(func.sum(rows.c.share_paise), 0).label("share_paise"),
            func.coalesce(func.sum(rows.c.cash_paid_paise), 0).label("cash_paid_paise"),
        )
        .group_by(bucket)
        .order_by(bucket)
    )
    return _tag(stmt, "trends", f, granularity=granularity)


def categories_statement(f: AnalyticsFilter) -> AnySelect:
    rows = ledger_rows(f)
    share = func.coalesce(func.sum(rows.c.share_paise), 0)
    cash = func.coalesce(func.sum(rows.c.cash_paid_paise), 0)
    stmt = (
        select(
            rows.c.category_id,
            Category.name.label("category_name"),
            share.label("share_paise"),
            cash.label("cash_paid_paise"),
            func.count(func.distinct(rows.c.expense_id)).label("expense_count"),
        )
        .join(Category, Category.id == rows.c.category_id)
        .group_by(rows.c.category_id, Category.name)
        .order_by(share.desc(), cash.desc(), Category.name)
    )
    return _tag(stmt, "categories", f)


# ---------------------------------------------------------------------------
# Authorization and balances
# ---------------------------------------------------------------------------


async def _authorize_group(db: AsyncSession, group_id: uuid.UUID, user: User) -> Group:
    """Current or past members may filter by a group; anyone else gets 404."""
    group = await get_group_or_404(db, group_id)
    GroupPolicy.authorize_member_or_404(user, group.id, {m.user_id for m in group.members})
    return group


async def _balances_across_groups(
    db: AsyncSession, user: User, group_id: uuid.UUID | None
) -> tuple[int, int]:
    """(owed_to_you, you_owe) from the ledger engine, summed over the user's groups."""
    if group_id is not None:
        group_ids = [group_id]
    else:
        result = await db.execute(
            select(GroupMember.group_id)
            .join(Group, Group.id == GroupMember.group_id)
            .where(GroupMember.user_id == user.id, Group.archived_at.is_(None))
        )
        group_ids = sorted({row for row in result.scalars().all()}, key=str)

    owed_to_you = 0
    you_owe = 0
    for gid in group_ids:
        position = (await settlement_service.compute_net_positions(db, gid)).get(str(user.id), 0)
        if position > 0:
            owed_to_you += position
        elif position < 0:
            you_owe += -position
    return owed_to_you, you_owe


async def _prepare(
    db: AsyncSession,
    user: User,
    from_date: date | None,
    to_date: date | None,
    group_id: uuid.UUID | None,
) -> AnalyticsFilter:
    start, end = resolve_range(from_date, to_date, settlement_service.today_in_kolkata())
    if group_id is not None:
        await _authorize_group(db, group_id, user)
    return AnalyticsFilter(user_id=user.id, start=start, end=end, group_id=group_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_summary(
    db: AsyncSession,
    user: User,
    from_date: date | None = None,
    to_date: date | None = None,
    group_id: uuid.UUID | None = None,
) -> AnalyticsSummaryResponse:
    f = await _prepare(db, user, from_date, to_date, group_id)
    row = (await db.execute(summary_statement(f))).one()
    owed_to_you, you_owe = await _balances_across_groups(db, user, group_id)
    return AnalyticsSummaryResponse(
        from_date=f.start,
        to_date=f.end,
        group_id=group_id,
        share_paise=int(row.share_paise),
        cash_paid_paise=int(row.cash_paid_paise),
        expense_count=int(row.expense_count),
        owed_to_you_paise=owed_to_you,
        you_owe_paise=you_owe,
    )


async def get_trends(
    db: AsyncSession,
    user: User,
    granularity: Granularity = "day",
    from_date: date | None = None,
    to_date: date | None = None,
    group_id: uuid.UUID | None = None,
) -> AnalyticsTrendsResponse:
    f = await _prepare(db, user, from_date, to_date, group_id)
    result = await db.execute(trends_statement(f, granularity))
    totals = {
        bucket_start(row.bucket_start, granularity): (int(row.share_paise), int(row.cash_paid_paise))
        for row in result.all()
    }
    buckets = build_series(totals, f.start, f.end, granularity)
    return AnalyticsTrendsResponse(
        from_date=f.start,
        to_date=f.end,
        group_id=group_id,
        granularity=granularity,
        buckets=buckets,
        total_share_paise=buckets[-1].cumulative_share_paise if buckets else 0,
        total_cash_paid_paise=buckets[-1].cumulative_cash_paid_paise if buckets else 0,
    )


async def get_categories(
    db: AsyncSession,
    user: User,
    from_date: date | None = None,
    to_date: date | None = None,
    group_id: uuid.UUID | None = None,
) -> AnalyticsCategoriesResponse:
    f = await _prepare(db, user, from_date, to_date, group_id)
    result = await db.execute(categories_statement(f))
    items = [
        CategoryBreakdownItem(
            category_id=row.category_id,
            category_name=row.category_name,
            share_paise=int(row.share_paise),
            cash_paid_paise=int(row.cash_paid_paise),
            expense_count=int(row.expense_count),
        )
        for row in result.all()
    ]
    return AnalyticsCategoriesResponse(
        from_date=f.start,
        to_date=f.end,
        group_id=group_id,
        categories=items,
        total_share_paise=sum(i.share_paise for i in items),
        total_cash_paid_paise=sum(i.cash_paid_paise for i in items),
    )

# ---------------------------------------------------------------------------
# Query tools (T-52)
# ---------------------------------------------------------------------------

from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


def _now_kolkata() -> date:
    """Return today's date in Asia/Kolkata timezone (no time component)."""
    return datetime.now(KOLKATA_TZ).date()


def parse_relative_date(keyword: str, today: date | None = None) -> tuple[date, date]:
    """Resolve human‑friendly date keywords to a (start, end) tuple in Asia/Kolkata.

    Supported keywords (case‑insensitive):
        - "today"
        - "yesterday"
        - "last week" / "previous week"
        - "this week"
        - "last month"
        - "this month"
    Raises HTTPException(400) for unknown keywords.
    """
    today = today or _now_kolkata()
    kw = keyword.strip().lower()
    if kw == "today":
        return today, today
    if kw == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if kw in ("last week", "previous week"):
        # Start of the week before the current week (Monday)
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
        return start, end
    if kw == "this week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end
    if kw == "last month":
        first_this_month = today.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        start = last_month_end.replace(day=1)
        return start, last_month_end
    if kw == "this month":
        start = today.replace(day=1)
        return start, today
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "INVALID_DATE_KEYWORD", "message": f"Unsupported date keyword: {keyword}"},
    )


def _filter_from_range(f: AnalyticsFilter, granularity: Granularity) -> AnySelect:
    """Create a SELECT that returns aggregated share and cash per bucket start."""
    rows = ledger_rows(f)
    bucket = func.date_trunc(granularity, rows.c.expense_date).label("bucket_start")
    agg = select(
        bucket,
        func.coalesce(func.sum(rows.c.share_paise), 0).label("share"),
        func.coalesce(func.sum(rows.c.cash_paid_paise), 0).label("cash"),
    ).group_by(bucket)
    return agg


async def get_spending_summary(
    user_id: uuid.UUID,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    date_keyword: str | None = None,
    group_id: uuid.UUID | None = None,
) -> AnalyticsSummaryResponse:
    """Tool #1 – total share & cash plus per‑category breakdown."""
    today = _now_kolkata()
    if date_keyword:
        start, end = parse_relative_date(date_keyword, today)
    else:
        start, end = resolve_range(
            from_date=date.fromisoformat(from_date) if from_date else None,
            to_date=date.fromisoformat(to_date) if to_date else None,
            today=today,
        )
    filt = AnalyticsFilter(user_id=user_id, start=start, end=end, group_id=group_id)

    rows = ledger_rows(filt)
    total_share = func.coalesce(func.sum(rows.c.share_paise), 0)
    total_cash = func.coalesce(func.sum(rows.c.cash_paid_paise), 0)
    total_stmt = select(total_share.label("share"), total_cash.label("cash"))
    async with AsyncSession() as session:
        total_res = await session.execute(total_stmt)
        total_share_val, total_cash_val = total_res.first()

    # Category breakdown
    cat_stmt = (
        select(
            Category.id,
            Category.name,
            func.coalesce(func.sum(rows.c.share_paise), 0).label("share"),
            func.coalesce(func.sum(rows.c.cash_paid_paise), 0).label("cash"),
        )
        .join(Category, Category.id == rows.c.category_id, isouter=True)
        .group_by(Category.id, Category.name)
    )
    async with AsyncSession() as session:
        cat_rows = await session.execute(cat_stmt)
        cat_data = cat_rows.all()
    categories = [
        CategoryBreakdownItem(
            category_id=row.id,
            category_name=row.name or "Uncategorised",
            share_paise=row.share,
            cash_paid_paise=row.cash,
        )
        for row in cat_data
    ]
    return AnalyticsSummaryResponse(
        total_share_paise=total_share_val,
        total_cash_paid_paise=total_cash_val,
        categories=categories,
    )


async def get_category_breakdown(
    user_id: uuid.UUID,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    date_keyword: str | None = None,
    group_id: uuid.UUID | None = None,
) -> AnalyticsCategoriesResponse:
    """Tool #2 – just the per‑category part of the summary."""
    summary = await get_spending_summary(
        user_id,
        from_date=from_date,
        to_date=to_date,
        date_keyword=date_keyword,
        group_id=group_id,
    )
    return AnalyticsCategoriesResponse(categories=summary.categories)


async def get_trends(
    user_id: uuid.UUID,
    *,
    granularity: Granularity = "day",
    from_date: str | None = None,
    to_date: str | None = None,
    date_keyword: str | None = None,
    group_id: uuid.UUID | None = None,
) -> AnalyticsTrendsResponse:
    """Tool #3 – time‑series buckets of spend/cash."""
    today = _now_kolkata()
    if date_keyword:
        start, end = parse_relative_date(date_keyword, today)
    else:
        start, end = resolve_range(
            from_date=date.fromisoformat(from_date) if from_date else None,
            to_date=date.fromisoformat(to_date) if to_date else None,
            today=today,
        )
    filt = AnalyticsFilter(user_id=user_id, start=start, end=end, group_id=group_id)
    agg_stmt = _filter_from_range(filt, granularity)
    async with AsyncSession() as session:
        rows = await session.execute(agg_stmt)
        totals = {row.bucket_start: (row.share, row.cash) for row in rows}
    buckets = build_series(totals, start, end, granularity)
    return AnalyticsTrendsResponse(buckets=buckets)

# Fixed‑granularity convenience wrappers (Tools #4‑#6)

async def get_daily_spending(**kwargs) -> AnalyticsSummaryResponse:
    return await get_spending_summary(**kwargs)

async def get_weekly_spending(**kwargs) -> AnalyticsSummaryResponse:
    return await get_spending_summary(**kwargs, granularity="week")  # type: ignore[arg-type]

async def get_monthly_spending(**kwargs) -> AnalyticsSummaryResponse:
    return await get_spending_summary(**kwargs, granularity="monthly")  # type: ignore[arg-type]

# Tool #7 – group‑specific summary

async def get_group_spending(
    user_id: uuid.UUID,
    group_id: uuid.UUID,
    **kwargs,
) -> AnalyticsSummaryResponse:
    return await get_spending_summary(user_id, group_id=group_id, **kwargs)

# Tool #8 – expose the date resolver for external callers

async def resolve_date_keyword(keyword: str) -> tuple[date, date]:
    return parse_relative_date(keyword)
