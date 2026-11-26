"""Predefined, fixed query tools for expense assistant (T-57 / US-24).

Strict Security & Architectural Invariants:
1. Exactly eight fixed tools.
2. User-level authorization enforced at every query (server-side authenticated user_id).
3. The LLM NEVER generates SQL queries.
4. The LLM NEVER receives database credentials or direct database access.
5. All monetary calculations are performed on whole integer paise.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any, Callable

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.date_resolver import DateResolver
from app.models.category import Category
from app.models.expense import Expense
from app.services.groq_client import CATEGORY_LOOKUP

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Eight Fixed Tool Implementation Functions
# -----------------------------------------------------------------------------


async def tool_get_total_spending(
    db: AsyncSession,
    user_id: uuid.UUID,
    start_date: str | None = None,
    end_date: str | None = None,
    date_range: str | None = None,
) -> dict[str, Any]:
    """1. Get total spending amount (in paise and rupees) and transaction count for the authenticated user."""
    resolved = DateResolver.resolve(
        date_range_keyword=date_range,
        start_date=start_date,
        end_date=end_date,
    )

    base_where = [
        Expense.user_id == user_id,
        Expense.deleted_at.is_(None),
    ]
    if resolved.start_date:
        base_where.append(Expense.expense_date >= resolved.start_date)
    if resolved.end_date:
        base_where.append(Expense.expense_date <= resolved.end_date)

    stmt = select(
        func.coalesce(func.sum(Expense.amount_minor), 0),
        func.count(Expense.id),
    ).where(*base_where)

    result = await db.execute(stmt)
    total_paise, count = result.one()
    total_paise = int(total_paise)
    count = int(count)

    return {
        "tool": "get_total_spending",
        "total_paise": total_paise,
        "total_rupees": total_paise / 100.0,
        "transaction_count": count,
        "start_date": resolved.start_date.isoformat() if resolved.start_date else None,
        "end_date": resolved.end_date.isoformat() if resolved.end_date else None,
        "period_label": resolved.period_label,
    }


async def tool_get_spending_by_category(
    db: AsyncSession,
    user_id: uuid.UUID,
    category: str,
    start_date: str | None = None,
    end_date: str | None = None,
    date_range: str | None = None,
) -> dict[str, Any]:
    """2. Get total spending and transaction count for a specific category."""
    if not category or not category.strip():
        raise ValueError("Category parameter is required")

    cat_name = category.strip()
    canonical_name = CATEGORY_LOOKUP.get(cat_name.lower(), cat_name)

    resolved = DateResolver.resolve(
        date_range_keyword=date_range,
        start_date=start_date,
        end_date=end_date,
    )

    base_where = [
        Expense.user_id == user_id,
        Expense.deleted_at.is_(None),
        (Category.is_default == True) | (Category.owner_id == user_id),
        func.lower(Category.name) == func.lower(canonical_name),
    ]
    if resolved.start_date:
        base_where.append(Expense.expense_date >= resolved.start_date)
    if resolved.end_date:
        base_where.append(Expense.expense_date <= resolved.end_date)

    stmt = (
        select(
            func.coalesce(func.sum(Expense.amount_minor), 0),
            func.count(Expense.id),
        )
        .join(Category, Expense.category_id == Category.id)
        .where(*base_where)
    )

    result = await db.execute(stmt)
    total_paise, count = result.one()
    total_paise = int(total_paise)
    count = int(count)

    return {
        "tool": "get_spending_by_category",
        "category": canonical_name,
        "total_paise": total_paise,
        "total_rupees": total_paise / 100.0,
        "transaction_count": count,
        "start_date": resolved.start_date.isoformat() if resolved.start_date else None,
        "end_date": resolved.end_date.isoformat() if resolved.end_date else None,
        "period_label": resolved.period_label,
    }


async def tool_get_category_breakdown(
    db: AsyncSession,
    user_id: uuid.UUID,
    start_date: str | None = None,
    end_date: str | None = None,
    date_range: str | None = None,
    limit: int | None = 10,
) -> dict[str, Any]:
    """3. Get spending totals grouped by category, ordered from highest to lowest."""
    resolved = DateResolver.resolve(
        date_range_keyword=date_range,
        start_date=start_date,
        end_date=end_date,
    )

    base_where = [
        Expense.user_id == user_id,
        Expense.deleted_at.is_(None),
    ]
    if resolved.start_date:
        base_where.append(Expense.expense_date >= resolved.start_date)
    if resolved.end_date:
        base_where.append(Expense.expense_date <= resolved.end_date)

    stmt = (
        select(
            Category.name,
            func.coalesce(func.sum(Expense.amount_minor), 0).label("cat_total"),
            func.count(Expense.id).label("cat_count"),
        )
        .join(Category, Expense.category_id == Category.id)
        .where(*base_where)
        .group_by(Category.name)
        .order_by(desc("cat_total"))
    )

    if limit and limit > 0:
        stmt = stmt.limit(min(limit, 50))

    result = await db.execute(stmt)
    rows = result.all()

    breakdown = []
    grand_total_paise = 0
    total_txns = 0
    for cat_name, amt, count in rows:
        amt = int(amt)
        count = int(count)
        grand_total_paise += amt
        total_txns += count
        breakdown.append(
            {
                "category": cat_name,
                "total_paise": amt,
                "total_rupees": amt / 100.0,
                "transaction_count": count,
            }
        )

    return {
        "tool": "get_category_breakdown",
        "breakdown": breakdown,
        "total_paise": grand_total_paise,
        "total_rupees": grand_total_paise / 100.0,
        "transaction_count": total_txns,
        "start_date": resolved.start_date.isoformat() if resolved.start_date else None,
        "end_date": resolved.end_date.isoformat() if resolved.end_date else None,
        "period_label": resolved.period_label,
    }


async def tool_get_recent_expenses(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int | None = 5,
    start_date: str | None = None,
    end_date: str | None = None,
    date_range: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """4. List individual recent expenses for the user with details (up to 20)."""
    resolved = DateResolver.resolve(
        date_range_keyword=date_range,
        start_date=start_date,
        end_date=end_date,
    )

    safe_limit = min(max(1, limit or 5), 20)
    base_where = [
        Expense.user_id == user_id,
        Expense.deleted_at.is_(None),
    ]
    if resolved.start_date:
        base_where.append(Expense.expense_date >= resolved.start_date)
    if resolved.end_date:
        base_where.append(Expense.expense_date <= resolved.end_date)

    if category and category.strip():
        canonical_cat = CATEGORY_LOOKUP.get(category.strip().lower(), category.strip())
        base_where.append(func.lower(Category.name) == func.lower(canonical_cat))

    stmt = (
        select(Expense, Category.name)
        .join(Category, Expense.category_id == Category.id)
        .where(*base_where)
        .order_by(Expense.expense_date.desc(), Expense.created_at.desc())
        .limit(safe_limit)
    )

    result = await db.execute(stmt)
    records = result.all()

    expenses_list = []
    total_paise = 0
    for exp, cat_name in records:
        total_paise += exp.amount_minor
        expenses_list.append(
            {
                "id": str(exp.id),
                "description": exp.description,
                "amount_paise": exp.amount_minor,
                "amount_rupees": exp.amount_minor / 100.0,
                "date": exp.expense_date.isoformat(),
                "category": cat_name,
                "merchant": exp.merchant,
            }
        )

    return {
        "tool": "get_recent_expenses",
        "expenses": expenses_list,
        "count": len(expenses_list),
        "total_paise": total_paise,
        "total_rupees": total_paise / 100.0,
        "start_date": resolved.start_date.isoformat() if resolved.start_date else None,
        "end_date": resolved.end_date.isoformat() if resolved.end_date else None,
        "period_label": resolved.period_label,
    }


async def tool_get_highest_expense(
    db: AsyncSession,
    user_id: uuid.UUID,
    start_date: str | None = None,
    end_date: str | None = None,
    date_range: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """5. Retrieve the single largest/highest expense recorded by the user."""
    resolved = DateResolver.resolve(
        date_range_keyword=date_range,
        start_date=start_date,
        end_date=end_date,
    )

    base_where = [
        Expense.user_id == user_id,
        Expense.deleted_at.is_(None),
    ]
    if resolved.start_date:
        base_where.append(Expense.expense_date >= resolved.start_date)
    if resolved.end_date:
        base_where.append(Expense.expense_date <= resolved.end_date)

    if category and category.strip():
        canonical_cat = CATEGORY_LOOKUP.get(category.strip().lower(), category.strip())
        base_where.append(func.lower(Category.name) == func.lower(canonical_cat))

    stmt = (
        select(Expense, Category.name)
        .join(Category, Expense.category_id == Category.id)
        .where(*base_where)
        .order_by(Expense.amount_minor.desc())
        .limit(1)
    )

    result = await db.execute(stmt)
    row = result.first()

    if not row:
        return {
            "tool": "get_highest_expense",
            "expense": None,
            "period_label": resolved.period_label,
        }

    exp, cat_name = row
    return {
        "tool": "get_highest_expense",
        "expense": {
            "id": str(exp.id),
            "description": exp.description,
            "amount_paise": exp.amount_minor,
            "amount_rupees": exp.amount_minor / 100.0,
            "date": exp.expense_date.isoformat(),
            "category": cat_name,
            "merchant": exp.merchant,
        },
        "period_label": resolved.period_label,
    }


async def tool_get_spending_by_merchant(
    db: AsyncSession,
    user_id: uuid.UUID,
    merchant: str,
    start_date: str | None = None,
    end_date: str | None = None,
    date_range: str | None = None,
) -> dict[str, Any]:
    """6. Get total spending and transaction count for a specific merchant."""
    if not merchant or not merchant.strip():
        raise ValueError("Merchant parameter is required")

    merchant_clean = merchant.strip()
    resolved = DateResolver.resolve(
        date_range_keyword=date_range,
        start_date=start_date,
        end_date=end_date,
    )

    base_where = [
        Expense.user_id == user_id,
        Expense.deleted_at.is_(None),
        (
            (Expense.merchant.ilike(f"%{merchant_clean}%"))
            | (Expense.description.ilike(f"%{merchant_clean}%"))
        ),
    ]
    if resolved.start_date:
        base_where.append(Expense.expense_date >= resolved.start_date)
    if resolved.end_date:
        base_where.append(Expense.expense_date <= resolved.end_date)

    stmt = select(
        func.coalesce(func.sum(Expense.amount_minor), 0),
        func.count(Expense.id),
    ).where(*base_where)

    result = await db.execute(stmt)
    total_paise, count = result.one()
    total_paise = int(total_paise)
    count = int(count)

    return {
        "tool": "get_spending_by_merchant",
        "merchant": merchant_clean,
        "total_paise": total_paise,
        "total_rupees": total_paise / 100.0,
        "transaction_count": count,
        "start_date": resolved.start_date.isoformat() if resolved.start_date else None,
        "end_date": resolved.end_date.isoformat() if resolved.end_date else None,
        "period_label": resolved.period_label,
    }


async def tool_get_daily_average_spending(
    db: AsyncSession,
    user_id: uuid.UUID,
    start_date: str | None = None,
    end_date: str | None = None,
    date_range: str | None = None,
) -> dict[str, Any]:
    """7. Calculate daily average spending across the resolved date range."""
    resolved = DateResolver.resolve(
        date_range_keyword=date_range,
        start_date=start_date,
        end_date=end_date,
    )

    today = DateResolver.get_current_ist_date()
    s_date = resolved.start_date or (today.replace(day=1))
    e_date = resolved.end_date or today

    if s_date > e_date:
        s_date, e_date = e_date, s_date

    days = max(1, (e_date - s_date).days + 1)

    base_where = [
        Expense.user_id == user_id,
        Expense.deleted_at.is_(None),
        Expense.expense_date >= s_date,
        Expense.expense_date <= e_date,
    ]

    stmt = select(
        func.coalesce(func.sum(Expense.amount_minor), 0),
        func.count(Expense.id),
    ).where(*base_where)

    result = await db.execute(stmt)
    total_paise, count = result.one()
    total_paise = int(total_paise)
    count = int(count)

    avg_paise = round(total_paise / days)

    return {
        "tool": "get_daily_average_spending",
        "average_daily_paise": avg_paise,
        "average_daily_rupees": avg_paise / 100.0,
        "total_paise": total_paise,
        "total_rupees": total_paise / 100.0,
        "days": days,
        "transaction_count": count,
        "start_date": s_date.isoformat(),
        "end_date": e_date.isoformat(),
        "period_label": resolved.period_label,
    }


async def tool_get_expenses_count(
    db: AsyncSession,
    user_id: uuid.UUID,
    start_date: str | None = None,
    end_date: str | None = None,
    date_range: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """8. Count the number of expense transactions recorded by the user."""
    resolved = DateResolver.resolve(
        date_range_keyword=date_range,
        start_date=start_date,
        end_date=end_date,
    )

    base_where = [
        Expense.user_id == user_id,
        Expense.deleted_at.is_(None),
    ]
    if resolved.start_date:
        base_where.append(Expense.expense_date >= resolved.start_date)
    if resolved.end_date:
        base_where.append(Expense.expense_date <= resolved.end_date)

    canonical_cat = None
    if category and category.strip():
        canonical_cat = CATEGORY_LOOKUP.get(category.strip().lower(), category.strip())
        base_where.extend([
            (Category.is_default == True) | (Category.owner_id == user_id),
            func.lower(Category.name) == func.lower(canonical_cat),
        ])

    stmt = select(func.count(Expense.id))
    if canonical_cat:
        stmt = stmt.join(Category, Expense.category_id == Category.id)
    stmt = stmt.where(*base_where)

    result = await db.execute(stmt)
    count = int(result.scalar_one() or 0)

    return {
        "tool": "get_expenses_count",
        "transaction_count": count,
        "category": canonical_cat,
        "start_date": resolved.start_date.isoformat() if resolved.start_date else None,
        "end_date": resolved.end_date.isoformat() if resolved.end_date else None,
        "period_label": resolved.period_label,
    }


# -----------------------------------------------------------------------------
# Fixed Eight Tools Registry & Schemas
# -----------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    "get_total_spending": tool_get_total_spending,
    "get_spending_by_category": tool_get_spending_by_category,
    "get_category_breakdown": tool_get_category_breakdown,
    "get_recent_expenses": tool_get_recent_expenses,
    "get_highest_expense": tool_get_highest_expense,
    "get_spending_by_merchant": tool_get_spending_by_merchant,
    "get_daily_average_spending": tool_get_daily_average_spending,
    "get_expenses_count": tool_get_expenses_count,
}

ALLOWED_TOOL_NAMES: frozenset[str] = frozenset(TOOL_REGISTRY.keys())

# Tool Schemas presented to the LLM (NO SQL, NO DB access, NO user_id parameter)
TOOL_DEFINITIONS = [
    {
        "name": "get_total_spending",
        "description": "Get total spending amount and transaction count for a specified date range or all time.",
        "parameters": {
            "type": "object",
            "properties": {
                "date_range": {
                    "type": "string",
                    "description": "Relative period keyword: today, yesterday, this_week, last_week, this_month, last_month, this_year, last_year, all_time",
                },
                "start_date": {"type": "string", "description": "Optional ISO start date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "Optional ISO end date YYYY-MM-DD"},
            },
        },
    },
    {
        "name": "get_spending_by_category",
        "description": "Get spending amount and transaction count for a specific expense category (e.g. food, groceries, transport, utilities).",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "The category name (e.g. Food & Dining, Groceries, Travel & Transport, Shopping, Bills & Utilities)"},
                "date_range": {"type": "string", "description": "Relative period keyword: today, yesterday, this_week, last_week, this_month, last_month, this_year, last_year, all_time"},
                "start_date": {"type": "string", "description": "Optional ISO start date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "Optional ISO end date YYYY-MM-DD"},
            },
            "required": ["category"],
        },
    },
    {
        "name": "get_category_breakdown",
        "description": "Get spending breakdown across all categories, ranked by highest spend.",
        "parameters": {
            "type": "object",
            "properties": {
                "date_range": {"type": "string", "description": "Relative period keyword"},
                "start_date": {"type": "string", "description": "Optional ISO start date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "Optional ISO end date YYYY-MM-DD"},
                "limit": {"type": "integer", "description": "Maximum number of categories to return"},
            },
        },
    },
    {
        "name": "get_recent_expenses",
        "description": "List individual recent expense records (description, amount, date, category, merchant).",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of expenses to list (1-20)"},
                "date_range": {"type": "string", "description": "Relative period keyword: today, yesterday, this_week, etc."},
                "start_date": {"type": "string", "description": "Optional ISO start date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "Optional ISO end date YYYY-MM-DD"},
                "category": {"type": "string", "description": "Optional category filter"},
            },
        },
    },
    {
        "name": "get_highest_expense",
        "description": "Find the user's largest/highest single expense transaction.",
        "parameters": {
            "type": "object",
            "properties": {
                "date_range": {"type": "string", "description": "Relative period keyword"},
                "start_date": {"type": "string", "description": "Optional ISO start date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "Optional ISO end date YYYY-MM-DD"},
                "category": {"type": "string", "description": "Optional category filter"},
            },
        },
    },
    {
        "name": "get_spending_by_merchant",
        "description": "Get total spending and transactions at a specific merchant/store (e.g. Starbucks, Amazon, Swiggy, Uber).",
        "parameters": {
            "type": "object",
            "properties": {
                "merchant": {"type": "string", "description": "Merchant or payee name"},
                "date_range": {"type": "string", "description": "Relative period keyword"},
                "start_date": {"type": "string", "description": "Optional ISO start date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "Optional ISO end date YYYY-MM-DD"},
            },
            "required": ["merchant"],
        },
    },
    {
        "name": "get_daily_average_spending",
        "description": "Calculate daily average spending amount over a given date range.",
        "parameters": {
            "type": "object",
            "properties": {
                "date_range": {"type": "string", "description": "Relative period keyword: this_month, last_month, this_week, last_week"},
                "start_date": {"type": "string", "description": "Optional ISO start date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "Optional ISO end date YYYY-MM-DD"},
            },
        },
    },
    {
        "name": "get_expenses_count",
        "description": "Count total number of transactions recorded by the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Optional category filter"},
                "date_range": {"type": "string", "description": "Relative period keyword"},
                "start_date": {"type": "string", "description": "Optional ISO start date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "Optional ISO end date YYYY-MM-DD"},
            },
        },
    },
]


async def execute_tool(
    tool_name: str,
    parameters: dict[str, Any],
    user_id: uuid.UUID,
    db: AsyncSession,
) -> dict[str, Any]:
    """Execute one of the eight predefined query tools with server-side user isolation.

    Raises ValueError for unsupported tools or invalid parameters.
    """
    if tool_name not in ALLOWED_TOOL_NAMES:
        raise ValueError(
            f"Unsupported tool '{tool_name}'. Allowed tools are: {sorted(ALLOWED_TOOL_NAMES)}"
        )

    # Disallow injection of unauthorized parameters (e.g. user_id, raw sql)
    unauthorized_keys = {"user_id", "sql", "query_sql", "raw_query", "db"}
    intersection = unauthorized_keys.intersection(parameters.keys())
    if intersection:
        raise ValueError(f"Unauthorized parameter(s) passed to tool: {sorted(intersection)}")

    fn = TOOL_REGISTRY[tool_name]
    return await fn(db=db, user_id=user_id, **parameters)
