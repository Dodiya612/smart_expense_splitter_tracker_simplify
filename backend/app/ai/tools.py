"""The eight fixed query tools of the expense assistant (T-57 / US-24).

The tools are the ones PRODUCT.md names: ``spend_total``, ``spend_by_category``,
``compare_periods``, ``top_merchants``, ``budget_status``, ``owed_summary``,
``recurring_upcoming`` and ``list_expenses``.

- The language model (or the offline question parser) picks ONE tool by name and
  fills its slots; each tool has a Pydantic slot model with ``extra="forbid"``.
- Every figure comes from an existing service, so the assistant always agrees
  with the rest of the app: spending from app/services/analytics_service.py
  (the user's SHARE: personal expenses in full, their share of shared ones;
  settlements and deleted expenses never count), budgets from budget_service,
  balances from the ledger through analytics_service, recurring expenses from
  recurring_service (a group rule counts the user's share, computed by the
  shared-expense split rules). Tools run no spending SQL of their own.
- Tools are scoped to the signed-in user: they take the authenticated ``User``
  and the services apply the policies. No slot accepts a user, group or expense
  id; a group is named and looked up among the user's own groups.
- Only totals, counts, the period and labels taken from the question may be
  shown to the model (CF-01). Lists built from stored text (category names,
  merchants, descriptions, group names) are filled in by code, and the rows of
  ``list_expenses`` are only ever shown through its template.
- Dates are resolved in code (app/services/date_ranges.py, Asia/Kolkata).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.category_terms import CategoryName
from app.ai.grounding import AllowedFigures, format_count, format_percent, format_rupees, percentage
from app.models.category import Category
from app.models.user import User
from app.schemas.assistant import AssistantCount, AssistantFigure, AssistantPeriod
from app.schemas.budget import BudgetResponse
from app.schemas.recurring import RecurringRuleResponse
from app.services import analytics_service, budget_service, group_service, recurring_service, shared_expense_service
from app.services.date_ranges import (
    Period,
    PeriodError,
    PeriodSlots,
    RelativePeriod,
    cap_at_today,
    format_day,
    resolve_period,
)

MERCHANT_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 &'.-]{0,39}$"
GROUP_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 &'.,()-]{0,59}$"
MAX_BUDGETS = 100
MAX_RECURRING_RULES = 100
MAX_LISTED = 10
#: What the model is shown instead of a list built from stored text.
FILLED_IN_BY_THE_APP = "[a list the app fills in]"


class ToolInputError(ValueError):
    """The slots name something the tool cannot answer for; the message is shown as the reason."""


#: Errors a tool raises for slots it cannot answer for; the message is shown to the user.
TOOL_INPUT_ERRORS = (PeriodError, ToolInputError)


# ---------------------------------------------------------------------------
# Slot models (one per tool)
# ---------------------------------------------------------------------------


class _Slots(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpendTotalSlots(_Slots):
    period: PeriodSlots = Field(default_factory=PeriodSlots, description="Leave empty when no period is named.")
    category: CategoryName | None = None
    measure: Literal["total", "count", "daily_average"] = Field(
        default="total",
        description="'total' (how much), 'count' (how many expenses) or 'daily_average' (average per day).",
    )


class SpendByCategorySlots(_Slots):
    period: PeriodSlots = Field(default_factory=PeriodSlots)
    limit: int = Field(default=5, ge=1, le=12, description="How many of the largest categories to name.")


class ComparePeriodsSlots(_Slots):
    a: PeriodSlots = Field(..., description="The period asked about.")
    b: PeriodSlots = Field(..., description="The period it is compared with.")
    category: CategoryName | None = None


class TopMerchantsSlots(_Slots):
    period: PeriodSlots = Field(default_factory=PeriodSlots)
    n: int = Field(default=5, ge=1, le=MAX_LISTED, description="How many merchants to name.")


class BudgetStatusSlots(_Slots):
    category: CategoryName | None = Field(default=None, description="Only the budget for this category.")


class OwedSummarySlots(_Slots):
    group: str | None = Field(
        default=None, pattern=GROUP_PATTERN, description="A group name written in the question; omit for all groups."
    )


class RecurringUpcomingSlots(_Slots):
    days: int = Field(default=7, ge=1, le=31, description="How many days ahead, including today.")


class ExpenseFilters(_Slots):
    period: PeriodSlots = Field(default_factory=PeriodSlots, description="Leave empty for the last two years.")
    category: CategoryName | None = None
    merchant: str | None = Field(
        default=None, pattern=MERCHANT_PATTERN, description="Merchant or payee name from the question."
    )


class ListExpensesSlots(_Slots):
    filters: ExpenseFilters = Field(default_factory=ExpenseFilters)
    sort: Literal["recent", "largest"] = "recent"
    limit: int = Field(default=5, ge=1, le=MAX_LISTED, description="How many expenses to show.")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolResult:
    """Figures computed by the backend, plus the sentence that states them.

    ``template`` uses ``{placeholders}`` filled from ``values``. Values named in
    ``private`` are lists built from stored text: the model only learns that the
    placeholder exists, and code fills it in. ``model_wording`` False means the
    answer is always the template (the model is not asked to word it).
    """

    tool: str
    period: Period | None
    figures: list[AssistantFigure]
    counts: list[AssistantCount]
    template: str
    values: dict[str, str]
    private: frozenset[str] = frozenset()
    percentages: frozenset[Decimal] = frozenset()
    extra_dates: frozenset[date] = frozenset()
    extra_phrases: frozenset[str] = frozenset()
    model_wording: bool = True

    def allowed(self) -> AllowedFigures:
        dates = set(self.extra_dates)
        phrases = set(self.extra_phrases)
        phrases.update(self.values[k] for k in self.private if k in self.values)
        if self.period is not None:
            dates.update({self.period.start, self.period.end})
            phrases.add(self.period.label)
        return AllowedFigures(
            amounts_paise=frozenset(f.amount_paise for f in self.figures),
            counts=frozenset(c.value for c in self.counts),
            percentages=self.percentages,
            dates=frozenset(dates),
            phrases=frozenset(phrases),
        )

    def template_answer(self) -> str:
        return self.template.format(**self.values)

    def shared_values(self) -> dict[str, str]:
        """What the model may see: every value, with private lists replaced by a marker."""
        return {k: FILLED_IN_BY_THE_APP if k in self.private else v for k, v in self.values.items()}

    def public_period(self) -> AssistantPeriod | None:
        if self.period is None:
            return None
        return AssistantPeriod(from_date=self.period.start, to_date=self.period.end, label=self.period.label)


def describe_period(period: Period) -> str:
    """'last week (16 Nov 2026 – 22 Nov 2026)'; a label that already has its dates stays as it is."""
    if format_day(period.start) in period.label:
        return period.label
    if period.start == period.end:
        return f"{period.label} ({format_day(period.start)})"
    return f"{period.label} ({format_day(period.start)} – {format_day(period.end)})"


def _expenses(n: int) -> str:
    return format_count(n, "expense", "expenses")


async def _spending(db: AsyncSession, user: User, period: Period, category: CategoryName | None) -> tuple[int, int]:
    """(share in paise, expense count) for the period, overall or in one category."""
    if category is None:
        s = await analytics_service.get_summary(db, user, period.start, period.end)
        return s.share_paise, s.expense_count
    c = await analytics_service.get_categories(db, user, period.start, period.end)
    wanted = category.value.casefold()
    items = [i for i in c.categories if i.category_name.casefold() == wanted]
    return sum(i.share_paise for i in items), sum(i.expense_count for i in items)


# ---------------------------------------------------------------------------
# 1. spend_total(category?, period)
# ---------------------------------------------------------------------------


async def spend_total(db: AsyncSession, user: User, slots: SpendTotalSlots, today: date) -> ToolResult:
    period = resolve_period(slots.period, today)
    if slots.measure == "daily_average":
        period = cap_at_today(period, today)  # an average over days still to come would be wrong
    total, count = await _spending(db, user, period, slots.category)
    values = {"total": format_rupees(total), "expenses": _expenses(count), "period": describe_period(period)}
    on = in_ = ""
    total_label = "Total spending"
    if slots.category is not None:
        values["category"] = slots.category.value
        on, in_ = " on {category}", " in {category}"
        total_label = f"{slots.category.value} spending"
    figures = [AssistantFigure(label=total_label, amount_paise=total)]
    counts = [AssistantCount(label="Expenses", value=count)]

    if slots.measure == "count":
        template = (
            f"You recorded {{expenses}}{in_} {{period}}, {{total}} in total."
            if count
            else f"You have no expenses{in_} recorded {{period}}."
        )
    elif slots.measure == "daily_average":
        days = period.days
        average = (2 * total + days) // (2 * days)  # nearest paisa, half up
        values["average"] = format_rupees(average)
        values["days"] = format_count(days, "day", "days")
        template = f"You spent {{average}} a day on average{on} {{period}}, {{total}} in total over {{days}}."
        figures.insert(0, AssistantFigure(label="Average per day", amount_paise=average))
        counts.insert(0, AssistantCount(label="Days", value=days))
    else:
        template = (
            f"You spent {{total}}{on} across {{expenses}} {{period}}."
            if count
            else f"You have no spending{on} recorded {{period}}."
        )
    return ToolResult("spend_total", period, figures, counts, template, values)


# ---------------------------------------------------------------------------
# 2. spend_by_category(period)
# ---------------------------------------------------------------------------


async def spend_by_category(db: AsyncSession, user: User, slots: SpendByCategorySlots, today: date) -> ToolResult:
    period = resolve_period(slots.period, today)
    c = await analytics_service.get_categories(db, user, period.start, period.end)
    total = c.total_share_paise  # every category, not only the ones named
    spent = [i for i in c.categories if i.share_paise > 0]
    shown = spent[: slots.limit]
    remaining = len(spent) - len(shown)
    pcts = [percentage(i.share_paise, total) for i in shown]
    values = {
        "total": format_rupees(total),
        "categories": format_count(len(spent), "category", "categories"),
        "breakdown": "; ".join(
            f"{i.category_name} {format_rupees(i.share_paise)} ({format_percent(p)})" for i, p in zip(shown, pcts)
        ),
        "period": describe_period(period),
    }
    counts = [AssistantCount(label="Categories", value=len(spent))]
    if not spent:
        template = "You have no spending recorded {period}."
    else:
        template = "You spent {total} across {categories} {period}. By category: {breakdown}."
        if remaining:
            template += " Plus {others}."
            values["others"] = format_count(remaining, "more category", "more categories")
            counts.append(AssistantCount(label="Categories not listed", value=remaining))
    return ToolResult(
        "spend_by_category",
        period,
        [
            AssistantFigure(label="Total spending", amount_paise=total),
            *(AssistantFigure(label=i.category_name, amount_paise=i.share_paise) for i in shown),
        ],
        counts,
        template,
        values,
        private=frozenset({"breakdown"}),  # category names can be user-defined text
        percentages=frozenset(pcts),
    )


# ---------------------------------------------------------------------------
# 3. compare_periods(a, b, category?)
# ---------------------------------------------------------------------------


async def compare_periods(db: AsyncSession, user: User, slots: ComparePeriodsSlots, today: date) -> ToolResult:
    a = resolve_period(slots.a, today)
    b = resolve_period(slots.b, today)
    if (a.start, a.end) == (b.start, b.end):
        raise ToolInputError("Those are the same period, so there is nothing to compare.")
    total_a, count_a = await _spending(db, user, a, slots.category)
    total_b, count_b = await _spending(db, user, b, slots.category)
    difference = abs(total_a - total_b)
    values = {
        "total_a": format_rupees(total_a),
        "total_b": format_rupees(total_b),
        "difference": format_rupees(difference),
        "period_a": describe_period(a),
        "period_b": describe_period(b),
    }
    on = ""
    prefix = "Spending"
    if slots.category is not None:
        values["category"] = slots.category.value
        on = " on {category}"
        prefix = f"{slots.category.value} spending"

    pcts: frozenset[Decimal] = frozenset()
    if total_a == total_b == 0:
        template = f"You have no spending{on} recorded {{period_a}} or {{period_b}}."
    elif total_a == total_b:
        template = f"You spent {{total_a}}{on} both {{period_a}} and {{period_b}}."
    elif total_a == 0:
        template = f"You have no spending{on} recorded {{period_a}}, against {{total_b}} {{period_b}}."
    elif total_b == 0:
        template = f"You spent {{total_a}}{on} {{period_a}}, and nothing {{period_b}}."
    else:
        more = "more" if total_a > total_b else "less"
        template = f"You spent {{total_a}}{on} {{period_a}}, {{difference}} {more} than the {{total_b}} {{period_b}}."
        change = percentage(difference, total_b)
        values["change"] = format_percent(change)
        template += f" That is {{change}} {more}."
        pcts = frozenset({change})
    return ToolResult(
        "compare_periods",
        a,
        [
            AssistantFigure(label=f"{prefix} {a.label}", amount_paise=total_a),
            AssistantFigure(label=f"{prefix} {b.label}", amount_paise=total_b),
            AssistantFigure(label="Difference", amount_paise=difference),
        ],
        [
            AssistantCount(label=f"Expenses {a.label}", value=count_a),
            AssistantCount(label=f"Expenses {b.label}", value=count_b),
        ],
        template,
        values,
        percentages=pcts,
        extra_dates=frozenset({b.start, b.end}),
        extra_phrases=frozenset({b.label}),
    )


# ---------------------------------------------------------------------------
# 4. top_merchants(period, n)
# ---------------------------------------------------------------------------


async def top_merchants(db: AsyncSession, user: User, slots: TopMerchantsSlots, today: date) -> ToolResult:
    period = resolve_period(slots.period, today)
    merchants = await analytics_service.get_merchants(db, user, period.start, period.end)
    shown = merchants[: slots.n]
    values = {
        "merchant_count": format_count(len(merchants), "merchant", "merchants"),
        "top": format_count(len(shown), "merchant", "merchants"),
        "merchants": "; ".join(
            f"{m.merchant} {format_rupees(m.share_paise)} ({_expenses(m.expense_count)})" for m in shown
        ),
        "period": describe_period(period),
    }
    counts = [AssistantCount(label="Merchants", value=len(merchants))]
    if not merchants:
        template = "You have no spending at a named merchant {period}."
    elif len(shown) == len(merchants):
        template = "You spent at {merchant_count} {period}: {merchants}."
    else:
        template = "You spent at {merchant_count} {period}. The top {top}: {merchants}."
        counts.append(AssistantCount(label="Merchants shown", value=len(shown)))
    return ToolResult(
        "top_merchants",
        period,
        [AssistantFigure(label=m.merchant, amount_paise=m.share_paise) for m in shown],
        counts,
        template,
        values,
        private=frozenset({"merchants"}),  # merchant names are stored text
    )


# ---------------------------------------------------------------------------
# 5. budget_status(category?)
# ---------------------------------------------------------------------------


async def category_names(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Names of the categories of the user's own budgets (a label lookup, not spending)."""
    if not ids:
        return {}
    result = await db.execute(select(Category.id, Category.name).where(Category.id.in_(ids)))
    return {cid: name for cid, name in result.all()}


def _budget_line(label: str, b: BudgetResponse) -> str:
    p = b.progress
    if p.status == "exceeded":
        tail = f"{format_rupees(p.over_by_paise)} over the limit" if p.over_by_paise else "the whole limit used"
    elif p.status == "warning":
        tail = f"{format_rupees(p.remaining_paise)} left, close to the limit"
    else:
        tail = f"{format_rupees(p.remaining_paise)} left"
    return (
        f"{label} budget: {format_rupees(p.spent_paise)} of {format_rupees(b.limit_paise)} spent "
        f"({p.percent_used}%), {tail} ({format_day(p.period_start)} – {format_day(p.period_end)})"
    )


async def budget_status(db: AsyncSession, user: User, slots: BudgetStatusSlots, today: date) -> ToolResult:
    budgets, _ = await budget_service.list_budgets(db, user, MAX_BUDGETS, 0)
    names = await category_names(db, {b.category_id for b in budgets if b.category_id is not None})
    if slots.category is not None:
        wanted = slots.category.value.casefold()
        budgets = [
            b for b in budgets if b.category_id is not None and names.get(b.category_id, "").casefold() == wanted
        ]
    values: dict[str, str] = {}
    if slots.category is not None:
        values["category"] = slots.category.value
    if not budgets:
        template = "You have no budget for {category}." if slots.category else "You have no active budgets."
        return ToolResult("budget_status", None, [], [AssistantCount(label="Budgets", value=0)], template, values)

    figures: list[AssistantFigure] = []
    lines: list[str] = []
    dates: set[date] = set()
    for b in budgets:
        scope = names.get(b.category_id, "category") if b.category_id is not None else "overall"
        label = f"{b.period.title()} {scope}"
        p = b.progress
        lines.append(_budget_line(label, b))
        figures.append(AssistantFigure(label=f"{label} budget spent", amount_paise=p.spent_paise))
        figures.append(AssistantFigure(label=f"{label} budget limit", amount_paise=b.limit_paise))
        if p.status == "exceeded":
            figures.append(AssistantFigure(label=f"{label} budget over", amount_paise=p.over_by_paise))
        else:
            figures.append(AssistantFigure(label=f"{label} budget left", amount_paise=p.remaining_paise))
        dates.update({p.period_start, p.period_end})
    over = sum(1 for b in budgets if b.progress.status == "exceeded")
    values.update(
        {
            "budgets": ". ".join(lines),
            "budget_count": format_count(len(budgets), "budget", "budgets"),
            "over_limit": format_count(over, "budget over its limit", "budgets over their limits"),
        }
    )
    period = None
    if len(budgets) == 1:
        only = budgets[0].progress
        period = Period(only.period_start, only.period_end, "this week" if budgets[0].period == "weekly" else "this month")
    return ToolResult(
        "budget_status",
        period,
        figures,
        [AssistantCount(label="Budgets", value=len(budgets)), AssistantCount(label="Over the limit", value=over)],
        "{budgets}." if len(budgets) == 1 else "You have {budget_count}. {budgets}.",
        values,
        private=frozenset({"budgets"}),  # category names can be user-defined text
        percentages=frozenset(Decimal(b.progress.percent_used) for b in budgets),
        extra_dates=frozenset(dates),
    )


# ---------------------------------------------------------------------------
# 6. owed_summary(group?)
# ---------------------------------------------------------------------------


def _group_key(name: str) -> str:
    """'The Flat Expenses group' and 'flat expenses' name the same group."""
    words = name.casefold().split()
    if words[:1] == ["the"]:
        words = words[1:]
    if words[-1:] == ["group"]:
        words = words[:-1]
    return " ".join(words)


async def owed_summary(db: AsyncSession, user: User, slots: OwedSummarySlots, today: date) -> ToolResult:
    if slots.group is None:
        s = await analytics_service.get_summary(db, user)  # balances are not limited to a range
        values: dict[str, str] = {}
        if s.owed_to_you_paise or s.you_owe_paise:
            template = "Across your groups, others owe you {owed_to_you} and you owe {you_owe}."
        else:
            template = "You are all settled up across your groups."
        private: frozenset[str] = frozenset()
    else:
        wanted = _group_key(slots.group)
        groups = [g for g in await group_service.list_user_groups(db, user) if _group_key(g.name) == wanted]
        if not groups:
            raise ToolInputError(f"I couldn't find a group called '{slots.group}' among your groups.")
        if len(groups) > 1:
            raise ToolInputError(f"You have more than one group called '{slots.group}'; open the group to see it.")
        s = await analytics_service.get_summary(db, user, group_id=groups[0].id)
        values = {"group": groups[0].name}
        if s.owed_to_you_paise or s.you_owe_paise:
            template = "In {group}, others owe you {owed_to_you} and you owe {you_owe}."
        else:
            template = "You are all settled up in {group}."
        private = frozenset({"group"})
    values.update({"owed_to_you": format_rupees(s.owed_to_you_paise), "you_owe": format_rupees(s.you_owe_paise)})
    return ToolResult(
        "owed_summary",
        None,
        [
            AssistantFigure(label="Owed to you", amount_paise=s.owed_to_you_paise),
            AssistantFigure(label="You owe", amount_paise=s.you_owe_paise),
        ],
        [],
        template,
        values,
        private=private,
    )


# ---------------------------------------------------------------------------
# 7. recurring_upcoming(days)
# ---------------------------------------------------------------------------


async def _rule_share(db: AsyncSession, user: User, rule: RecurringRuleResponse) -> int | None:
    """The user's share of one occurrence, or None if the generator would skip it."""
    if rule.group_id is None:
        return rule.amount_paise
    template = {
        "amount_paise": rule.amount_paise,
        "description": rule.description,
        "category_id": rule.category_id,
        "notes": rule.notes,
        "merchant": rule.merchant,
        "payment_mode": rule.payment_mode,
    }
    split = rule.split.model_dump(mode="json", exclude_none=True) if rule.split is not None else None
    try:
        request = recurring_service.shared_expense_request(template, split, None)
        group = await group_service.get_group_or_404(db, rule.group_id)
        _, _, shares = shared_expense_service.resolve_split(group, user, request)
    except (HTTPException, ValidationError):
        return None
    return shares.get(str(user.id), 0)


async def recurring_upcoming(
    db: AsyncSession, user: User, slots: RecurringUpcomingSlots, today: date
) -> ToolResult:
    days = slots.days
    period = Period(today, today + timedelta(days=days - 1), "today" if days == 1 else f"in the next {days} days")
    rules, _ = await recurring_service.list_rules(db, user, recurring_service.ACTIVE, MAX_RECURRING_RULES, 0)
    due: list[tuple[date, str, int]] = []
    for rule in rules:
        if rule.next_run_date is None:
            continue
        first = max(rule.next_run_date, today)  # earlier dates are already handled
        dates = recurring_service.schedule_between(rule.start_date, rule.frequency, rule.end_date, first, period.end)
        if not dates:
            continue
        share = await _rule_share(db, user, rule)
        if not share:
            continue
        due.extend((d, rule.description, share) for d in dates)
    due.sort(key=lambda item: (item[0], item[1].casefold(), item[2]))
    shown = due[:MAX_LISTED]
    total = sum(share for _, _, share in due)
    values = {
        "due": format_count(len(due), "recurring expense due", "recurring expenses due"),
        "total": format_rupees(total),
        "items": "; ".join(f"{description} {format_rupees(share)} on {format_day(d)}" for d, description, share in shown),
        "period": describe_period(period),
    }
    counts = [AssistantCount(label="Recurring expenses due", value=len(due))]
    if not due:
        template = "You have no recurring expenses due {period}."
    else:
        template = "You have {due} {period}, {total} in total: {items}."
        if len(due) > len(shown):
            template += " Plus {others}."
            values["others"] = format_count(len(due) - len(shown), "more", "more")
            counts.append(AssistantCount(label="Not listed", value=len(due) - len(shown)))
    return ToolResult(
        "recurring_upcoming",
        period,
        [
            AssistantFigure(label="Total due", amount_paise=total),
            *(AssistantFigure(label=f"{description} on {format_day(d)}", amount_paise=s) for d, description, s in shown),
        ],
        counts,
        template,
        values,
        private=frozenset({"items"}),  # rule descriptions are stored text
        extra_dates=frozenset(d for d, _, _ in shown),
    )


# ---------------------------------------------------------------------------
# 8. list_expenses(filters, limit)
# ---------------------------------------------------------------------------


def _row_text(row: analytics_service.ExpenseShareRow) -> str:
    name = row.description
    if row.merchant and not re.search(re.escape(row.merchant.strip()), name, re.IGNORECASE):
        name = f"{name} ({row.merchant.strip()})"
    return f"{format_day(row.expense_date)} {name} {format_rupees(row.share_paise)}"


async def list_expenses(db: AsyncSession, user: User, slots: ListExpensesSlots, today: date) -> ToolResult:
    f = slots.filters
    named = f.period if not f.period.is_empty() else PeriodSlots(date_range=RelativePeriod.ALL_TIME)
    period = resolve_period(named, today)
    found = await analytics_service.get_expense_rows(
        db,
        user,
        period.start,
        period.end,
        category=f.category.value if f.category is not None else None,
        merchant=f.merchant.strip() if f.merchant else None,
        sort=slots.sort,
        limit=slots.limit,
    )
    values = {
        "expenses": _expenses(found.expense_count),
        "total": format_rupees(found.total_share_paise),
        "shown": str(len(found.rows)),
        "rows": "; ".join(_row_text(r) for r in found.rows),
        "period": describe_period(period),
    }
    what = ""
    if f.category is not None:
        values["category"] = f.category.value
        what += " on {category}"
    if f.merchant:
        values["merchant"] = f.merchant.strip()
        what += " at {merchant}"
    if not found.rows:
        template = f"You have no expenses{what} recorded {{period}}."
    else:
        order = "largest" if slots.sort == "largest" else "most recent"
        if found.expense_count == len(found.rows):
            listing = f"{order.capitalize()} first"
        elif len(found.rows) == 1:
            listing = f"The {order}"
        else:
            listing = f"The {{shown}} {order}"
        template = f"You have {{expenses}}{what} {{period}}, {{total}} in total. {listing}: {{rows}}."
    return ToolResult(
        "list_expenses",
        period,
        [
            AssistantFigure(label="Total spending", amount_paise=found.total_share_paise),
            *(
                AssistantFigure(label=f"{format_day(r.expense_date)} {r.description}", amount_paise=r.share_paise)
                for r in found.rows
            ),
        ],
        [
            AssistantCount(label="Expenses", value=found.expense_count),
            AssistantCount(label="Shown", value=len(found.rows)),
        ],
        template,
        values,
        private=frozenset({"rows"}),
        extra_dates=frozenset(r.expense_date for r in found.rows),
        model_wording=False,  # rows are shown only through this template, never sent to the model
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ToolRunner = Callable[[AsyncSession, User, Any, date], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    slots: type[BaseModel]
    run: ToolRunner = field(repr=False)

    def definition(self) -> dict[str, Any]:
        """What the language model is shown: name, purpose and slot schema."""
        return {"name": self.name, "description": self.description, "slots": self.slots.model_json_schema()}


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "spend_total",
            "How much the user spent (their share) in a period, optionally in one category; also how many "
            "expenses (measure 'count') or the average per day (measure 'daily_average').",
            SpendTotalSlots,
            spend_total,
        ),
        ToolSpec(
            "spend_by_category",
            "Spending in a period split by category, largest first.",
            SpendByCategorySlots,
            spend_by_category,
        ),
        ToolSpec(
            "compare_periods",
            "Compare spending in two periods (a = the period asked about, b = the one it is compared with), "
            "optionally in one category.",
            ComparePeriodsSlots,
            compare_periods,
        ),
        ToolSpec(
            "top_merchants",
            "The merchants where the user spent the most in a period.",
            TopMerchantsSlots,
            top_merchants,
        ),
        ToolSpec(
            "budget_status",
            "Progress of the user's active budgets in the current week or month, optionally for one category.",
            BudgetStatusSlots,
            budget_status,
        ),
        ToolSpec(
            "owed_summary",
            "What others owe the user and what the user owes, across all their groups or in one named group.",
            OwedSummarySlots,
            owed_summary,
        ),
        ToolSpec(
            "recurring_upcoming",
            "Recurring expenses due in the next N days (at most 31), with the user's share of each.",
            RecurringUpcomingSlots,
            recurring_upcoming,
        ),
        ToolSpec(
            "list_expenses",
            "Show the user's expenses, newest or largest first (at most 10), filtered by period, category or "
            "merchant. Also for 'biggest expense' questions and spending at one merchant.",
            ListExpensesSlots,
            list_expenses,
        ),
    )
}

ALLOWED_TOOL_NAMES: frozenset[str] = frozenset(TOOLS)


def tool_definitions() -> list[dict[str, Any]]:
    return [spec.definition() for spec in TOOLS.values()]
