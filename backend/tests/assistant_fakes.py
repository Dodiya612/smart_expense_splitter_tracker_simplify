"""Test doubles for the expense assistant (T-57): a stub language model and fixed service figures.

No test ever calls the real Groq API: the stub records what it was sent so tests
can check that only totals, periods and labels reach the model.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any

from app.ai import tools
from app.schemas.analytics import AnalyticsCategoriesResponse, AnalyticsSummaryResponse, CategoryBreakdownItem
from app.schemas.budget import BudgetResponse
from app.schemas.group import GroupListItemResponse
from app.schemas.recurring import RecurringRuleResponse
from app.services import analytics_service, budget_service, group_service, recurring_service

Selection = dict[str, Any] | None
FOOD_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
GROUP_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
NOW = datetime(2026, 11, 1, tzinfo=UTC)


def placeholder_sentence(facts: dict[str, str]) -> str:
    return "Here is what I found: " + ", ".join("{" + name + "}" for name in facts) + "."


class StubLLM:
    """Stands in for GroqClient: a fixed (or computed) tool call and wording."""

    def __init__(
        self,
        selection: Selection | Callable[[str], Selection] = None,
        wording: str | Callable[[dict[str, str]], str | None] | None = placeholder_sentence,
        configured: bool = True,
    ) -> None:
        self.selection = selection
        self.wording = wording
        self.configured = configured
        self.selection_calls: list[tuple[str, list[dict[str, Any]]]] = []
        self.wording_calls: list[tuple[str, str, dict[str, str]]] = []

    def is_configured(self) -> bool:
        return self.configured

    async def select_tool_call(self, question: str, tool_definitions: list[dict[str, Any]]) -> Selection:
        self.selection_calls.append((question, tool_definitions))
        return self.selection(question) if callable(self.selection) else self.selection

    async def write_answer(self, question: str, tool_name: str, facts: dict[str, str]) -> str | None:
        self.wording_calls.append((question, tool_name, dict(facts)))
        return self.wording(facts) if callable(self.wording) else self.wording


def budget(period: str, limit: int, spent: int, start: date, end: date, category_id: uuid.UUID | None = None):
    return budget_service.to_response(
        budget_service.Measured(
            budget=_BudgetRow(uuid.uuid4(), period, category_id, limit), start=start, end=end, spent_paise=spent
        )
    )


class _BudgetRow:
    def __init__(self, budget_id: uuid.UUID, period: str, category_id: uuid.UUID | None, limit: int) -> None:
        self.id = budget_id
        self.period = period
        self.category_id = category_id
        self.limit_paise = limit
        self.created_at = self.updated_at = NOW


def rule(description: str, amount: int, start: date, frequency: str = "monthly", next_run: date | None = None,
         merchant: str | None = None) -> RecurringRuleResponse:
    return RecurringRuleResponse(
        id=uuid.uuid4(), frequency=frequency, start_date=start, next_run_date=next_run or start, status="active",
        amount_paise=amount, category_id=FOOD_ID, description=description, merchant=merchant,
        created_at=NOW, updated_at=NOW,
    )


class FakeServices:
    """Fixed figures for every service the tools read; records each call (kind and arguments)."""

    def __init__(
        self,
        share_paise: int = 70000,
        expense_count: int = 3,
        categories: list[tuple[str, int, int]] | None = None,
        owed_to_you_paise: int = 0,
        you_owe_paise: int = 0,
        merchants: list[tuple[str, int, int]] | None = None,
        rows: list[tuple[date, str, str | None, str, int]] | None = None,
        budgets: list[BudgetResponse] | None = None,
        names: dict[uuid.UUID, str] | None = None,
        rules: list[RecurringRuleResponse] | None = None,
        groups: list[str] | None = None,
    ) -> None:
        self.share_paise = share_paise
        self.expense_count = expense_count
        self.categories = categories if categories is not None else [("Food & Dining", 50000, 2), ("Groceries", 20000, 1)]
        self.owed_to_you_paise = owed_to_you_paise
        self.you_owe_paise = you_owe_paise
        self.merchants = merchants if merchants is not None else [("Swiggy", 40000, 2), ("Uber", 30000, 1)]
        self.rows = rows if rows is not None else [
            (date(2026, 11, 20), "Dinner", "Swiggy", "Food & Dining", 40000),
            (date(2026, 11, 18), "Cab", "Uber", "Travel & Transport", 30000),
        ]
        self.budgets = budgets if budgets is not None else []
        self.names = names if names is not None else {FOOD_ID: "Food & Dining"}
        self.rules = rules if rules is not None else []
        self.groups = groups if groups is not None else ["Flat Expenses"]
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def install(self, monkeypatch: Any) -> FakeServices:
        monkeypatch.setattr(analytics_service, "get_summary", self.get_summary)
        monkeypatch.setattr(analytics_service, "get_categories", self.get_categories)
        monkeypatch.setattr(analytics_service, "get_merchants", self.get_merchants)
        monkeypatch.setattr(analytics_service, "get_expense_rows", self.get_expense_rows)
        monkeypatch.setattr(budget_service, "list_budgets", self.list_budgets)
        monkeypatch.setattr(recurring_service, "list_rules", self.list_rules)
        monkeypatch.setattr(group_service, "list_user_groups", self.list_user_groups)
        monkeypatch.setattr(tools, "category_names", self.category_names)
        return self

    async def get_summary(self, db: Any, user: Any, from_date: date | None = None, to_date: date | None = None,
                          group_id: Any = None) -> AnalyticsSummaryResponse:
        self.calls.append(("summary", {"from": from_date, "to": to_date, "group_id": group_id}))
        return AnalyticsSummaryResponse(
            from_date=from_date or date(2026, 11, 1), to_date=to_date or date(2026, 11, 24), group_id=group_id,
            share_paise=self.share_paise, cash_paid_paise=self.share_paise, expense_count=self.expense_count,
            owed_to_you_paise=self.owed_to_you_paise, you_owe_paise=self.you_owe_paise,
        )

    async def get_categories(self, db: Any, user: Any, from_date: date | None = None,
                             to_date: date | None = None, group_id: Any = None) -> AnalyticsCategoriesResponse:
        self.calls.append(("categories", {"from": from_date, "to": to_date}))
        items = [
            CategoryBreakdownItem(category_id=uuid.uuid4(), category_name=name, share_paise=share,
                                  cash_paid_paise=share, expense_count=count)
            for name, share, count in self.categories
        ]
        return AnalyticsCategoriesResponse(
            from_date=from_date or date(2026, 11, 1), to_date=to_date or date(2026, 11, 24), categories=items,
            total_share_paise=sum(i.share_paise for i in items),
            total_cash_paid_paise=sum(i.cash_paid_paise for i in items),
        )

    async def get_merchants(self, db: Any, user: Any, from_date: date | None = None,
                            to_date: date | None = None) -> list[analytics_service.MerchantTotal]:
        self.calls.append(("merchants", {"from": from_date, "to": to_date}))
        return [analytics_service.MerchantTotal(m, share, count) for m, share, count in self.merchants]

    async def get_expense_rows(self, db: Any, user: Any, from_date: date | None = None, to_date: date | None = None,
                               **filters: Any) -> analytics_service.ExpenseShareRows:
        self.calls.append(("expense_rows", {"from": from_date, "to": to_date, **filters}))
        rows = [analytics_service.ExpenseShareRow(*r) for r in self.rows]
        return analytics_service.ExpenseShareRows(
            from_date or date(2026, 11, 1), to_date or date(2026, 11, 24), rows[: filters.get("limit", 10)],
            len(rows), sum(r.share_paise for r in rows),
        )

    async def list_budgets(self, db: Any, user: Any, limit: int, offset: int) -> tuple[list[BudgetResponse], int]:
        self.calls.append(("budgets", {"limit": limit, "offset": offset}))
        return self.budgets, len(self.budgets)

    async def category_names(self, db: Any, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        return {i: self.names[i] for i in ids if i in self.names}

    async def list_rules(self, db: Any, owner: Any, rule_status: str | None, limit: int,
                         offset: int) -> tuple[list[RecurringRuleResponse], int]:
        self.calls.append(("recurring", {"status": rule_status, "limit": limit}))
        return self.rules, len(self.rules)

    async def list_user_groups(self, db: Any, user: Any) -> list[GroupListItemResponse]:
        self.calls.append(("groups", {}))
        return [
            GroupListItemResponse(id=GROUP_ID, name=name, type="flat", created_by=uuid.uuid4(), created_at=NOW,
                                  member_count=3, current_user_role="member")
            for name in self.groups
        ]


class FakeReservation:
    def __init__(self, quota: FakeQuota) -> None:
        self._quota = quota

    @property
    def allowed(self) -> bool:
        return self._quota.allowed

    async def finalize(self, status: str = "success", **_: Any) -> None:
        self._quota.finalized.append(status)


class FakeQuota:
    """Stands in for AIQuotaService: records reservations and how each was finalized."""

    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.reserve_calls: list[dict[str, Any]] = []
        self.finalized: list[str] = []

    @asynccontextmanager
    async def reserve(self, **kwargs: Any) -> AsyncIterator[FakeReservation]:
        self.reserve_calls.append(kwargs)
        yield FakeReservation(self)


class _UserResult:
    def __init__(self, user: Any) -> None:
        self._user = user

    def scalar_one_or_none(self) -> Any:
        return self._user


class UserOnlySession:
    """A session that can only load the signed-in user (get_current_user); tools use FakeServices."""

    def __init__(self, users: list[Any]) -> None:
        self._users = {u.id: u for u in users}

    async def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> _UserResult:
        params = stmt.compile().params
        user_id = next((v for v in params.values() if isinstance(v, uuid.UUID)), None)
        return _UserResult(self._users.get(user_id))
