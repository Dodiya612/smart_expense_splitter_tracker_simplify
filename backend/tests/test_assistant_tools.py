"""Automated tests for the eight query tools and user-level data isolation (T-57 / US-24)."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.ai.tools import (
    ALLOWED_TOOL_NAMES,
    execute_tool,
    tool_get_category_breakdown,
    tool_get_daily_average_spending,
    tool_get_expenses_count,
    tool_get_highest_expense,
    tool_get_recent_expenses,
    tool_get_spending_by_category,
    tool_get_spending_by_merchant,
    tool_get_total_spending,
)
from app.models.category import Category
from app.models.expense import Expense


class MockResult:
    def __init__(self, rows: list[Any] | None = None, tuple_res: tuple[Any, ...] | None = None):
        self._rows = rows or []
        self._tuple_res = tuple_res

    def one(self) -> tuple[Any, ...]:
        if self._tuple_res is not None:
            return self._tuple_res
        if self._rows:
            return self._rows[0]
        return (0, 0)

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        if self._tuple_res is not None:
            return self._tuple_res[0]
        if self._rows:
            return self._rows[0]
        return 0


class MockSession:
    """In-memory mock session evaluating the eight tools' SQLAlchemy queries."""

    def __init__(
        self,
        expenses: list[Expense],
        categories: list[Category],
        users: list[Any] | None = None,
    ):
        self.expenses = expenses
        self.categories = {c.id: c for c in categories}
        self.categories_by_name = {c.name.lower(): c for c in categories}
        self.users = {u.id: u for u in users} if users else {}

    def add(self, obj: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass

    async def execute(self, stmt: Any) -> MockResult:
        sql = str(stmt).lower()
        params = stmt.compile().params

        # 0. User lookup
        if "from users" in sql:
            uid = params.get("id_1") or params.get("id")
            if uid and uid in self.users:
                return MockResult(rows=[self.users[uid]])
            return MockResult(rows=list(self.users.values()))

        # Quota usage queries
        if "ai_usage_log" in sql or "pg_advisory" in sql:
            return MockResult(tuple_res=(0,))

        # Filter expenses by user_id and not deleted
        user_id = params.get("user_id_1") or params.get("user_id")
        active_expenses = [
            e for e in self.expenses
            if (user_id is None or e.user_id == user_id) and e.deleted_at is None
        ]

        # Apply date filters
        from_date = params.get("expense_date_1") or params.get("expense_date_2")
        to_date = params.get("expense_date_3") or params.get("expense_date_2") or params.get("expense_date_1")

        # In SQLAlchemy compile params:
        # Check all params for date values
        date_vals = [v for k, v in params.items() if "expense_date" in k and isinstance(v, (date, str))]
        if len(date_vals) == 2:
            s_d, e_d = sorted(date_vals)
            active_expenses = [e for e in active_expenses if s_d <= e.expense_date <= e_d]
        elif len(date_vals) == 1:
            d_val = date_vals[0]
            if ">= :expense_date" in sql:
                active_expenses = [e for e in active_expenses if e.expense_date >= d_val]
            elif "<= :expense_date" in sql:
                active_expenses = [e for e in active_expenses if e.expense_date <= d_val]

        # Check Category join filter
        cat_name_param = None
        for v in params.values():
            if isinstance(v, str) and v.lower() in self.categories_by_name:
                cat_name_param = v
                break

        if cat_name_param:
            active_expenses = [
                e for e in active_expenses
                if e.category_id in self.categories
                and self.categories[e.category_id].name.lower() == cat_name_param.lower()
            ]

        # Check Merchant filter
        merchant_param = next(
            (v for v in params.values() if isinstance(v, str) and v.startswith("%") and v.endswith("%")),
            None,
        )
        if merchant_param:
            clean_m = merchant_param.strip("%").lower()
            active_expenses = [
                e for e in active_expenses
                if clean_m in (e.merchant or "").lower() or clean_m in (e.description or "").lower()
            ]

        # 1. Category breakdown query (group by category)
        if "group by categories.name" in sql:
            cat_totals: dict[str, list[int]] = {}
            for e in active_expenses:
                c_name = self.categories[e.category_id].name if e.category_id in self.categories else "Other"
                if c_name not in cat_totals:
                    cat_totals[c_name] = [0, 0]
                cat_totals[c_name][0] += e.amount_minor
                cat_totals[c_name][1] += 1
            sorted_breakdown = sorted(
                [(c, totals[0], totals[1]) for c, totals in cat_totals.items()],
                key=lambda x: x[1],
                reverse=True,
            )
            return MockResult(rows=sorted_breakdown)

        # 2. Recent expenses query or Highest expense query
        if "order by expenses.amount_minor desc" in sql:
            sorted_e = sorted(active_expenses, key=lambda x: x.amount_minor, reverse=True)
            if sorted_e:
                e = sorted_e[0]
                c_name = self.categories[e.category_id].name if e.category_id in self.categories else "Other"
                return MockResult(rows=[(e, c_name)])
            return MockResult(rows=[])

        if "order by expenses.expense_date desc" in sql:
            sorted_e = sorted(active_expenses, key=lambda x: (x.expense_date, x.created_at), reverse=True)
            limit = stmt._limit or len(sorted_e)
            sliced = sorted_e[:limit]
            rows = [
                (e, self.categories[e.category_id].name if e.category_id in self.categories else "Other")
                for e in sliced
            ]
            return MockResult(rows=rows)

        # 3. Sum & Count aggregate queries (total_spending, spending_by_category, spending_by_merchant, daily_average)
        if "coalesce(sum(expenses.amount_minor)" in sql:
            tot = sum(e.amount_minor for e in active_expenses)
            cnt = len(active_expenses)
            return MockResult(tuple_res=(tot, cnt))

        # 4. Count query
        if "count(expenses.id)" in sql:
            return MockResult(tuple_res=(len(active_expenses),))

        return MockResult()


@pytest.fixture
def mock_dataset():
    """Build mock categories and expenses for two distinct users."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    cat_food = Category(id=uuid.uuid4(), name="Food & Dining", is_default=True)
    cat_shop = Category(id=uuid.uuid4(), name="Shopping", is_default=True)
    cat_travel = Category(id=uuid.uuid4(), name="Travel & Transport", is_default=True)
    categories = [cat_food, cat_shop, cat_travel]

    now = datetime.now(UTC)
    today = date(2026, 11, 22)

    expenses = [
        # User A expenses
        Expense(
            id=uuid.uuid4(),
            user_id=user_a,
            category_id=cat_food.id,
            amount_minor=200000,  # ₹2,000
            description="Lunch with colleagues",
            merchant="Bawarchi",
            expense_date=today,
            created_at=now,
        ),
        Expense(
            id=uuid.uuid4(),
            user_id=user_a,
            category_id=cat_food.id,
            amount_minor=45000,   # ₹450
            description="Coffee",
            merchant="Starbucks",
            expense_date=today,
            created_at=now,
        ),
        Expense(
            id=uuid.uuid4(),
            user_id=user_a,
            category_id=cat_shop.id,
            amount_minor=150000,  # ₹1,500
            description="Winter Jacket",
            merchant="Zara",
            expense_date=date(2026, 11, 20),
            created_at=now,
        ),
        # Soft-deleted expense for User A (must be ignored)
        Expense(
            id=uuid.uuid4(),
            user_id=user_a,
            category_id=cat_shop.id,
            amount_minor=500000,
            description="Cancelled Order",
            expense_date=today,
            created_at=now,
            deleted_at=now,
        ),
        # User B expenses
        Expense(
            id=uuid.uuid4(),
            user_id=user_b,
            category_id=cat_food.id,
            amount_minor=50000,   # ₹500
            description="Dinner",
            merchant="Swiggy",
            expense_date=today,
            created_at=now,
        ),
        Expense(
            id=uuid.uuid4(),
            user_id=user_b,
            category_id=cat_travel.id,
            amount_minor=80000,   # ₹800
            description="Cab to Airport",
            merchant="Uber",
            expense_date=today,
            created_at=now,
        ),
    ]

    session = MockSession(expenses, categories)
    return {
        "user_a": user_a,
        "user_b": user_b,
        "session": session,
    }


def test_exactly_eight_tools_registered():
    """Verify strictly eight fixed tools are registered."""
    assert len(ALLOWED_TOOL_NAMES) == 8
    expected_tools = {
        "get_total_spending",
        "get_spending_by_category",
        "get_category_breakdown",
        "get_recent_expenses",
        "get_highest_expense",
        "get_spending_by_merchant",
        "get_daily_average_spending",
        "get_expenses_count",
    }
    assert ALLOWED_TOOL_NAMES == expected_tools


@pytest.mark.anyio
async def test_invalid_tool_rejection(mock_dataset):
    """Attempting to execute an arbitrary/unsupported tool is strictly rejected."""
    session = mock_dataset["session"]
    user_a = mock_dataset["user_a"]

    with pytest.raises(ValueError, match="Unsupported tool"):
        await execute_tool("execute_sql_query", {}, user_id=user_a, db=session)

    with pytest.raises(ValueError, match="Unsupported tool"):
        await execute_tool("delete_all_data", {}, user_id=user_a, db=session)


@pytest.mark.anyio
async def test_unauthorized_parameter_rejection(mock_dataset):
    """Parameters attempting to inject user_id or SQL are rejected."""
    session = mock_dataset["session"]
    user_a = mock_dataset["user_a"]

    with pytest.raises(ValueError, match="Unauthorized parameter"):
        await execute_tool("get_total_spending", {"user_id": str(uuid.uuid4())}, user_id=user_a, db=session)

    with pytest.raises(ValueError, match="Unauthorized parameter"):
        await execute_tool("get_total_spending", {"sql": "SELECT 1"}, user_id=user_a, db=session)


@pytest.mark.anyio
async def test_user_level_data_isolation(mock_dataset):
    """User A and User B cannot access each other's expenses."""
    session = mock_dataset["session"]
    user_a = mock_dataset["user_a"]
    user_b = mock_dataset["user_b"]

    # User A: 2000 + 450 + 1500 = 3950 rupees (395000 paise), 3 transactions
    res_a = await tool_get_total_spending(db=session, user_id=user_a)
    assert res_a["total_paise"] == 395000
    assert res_a["total_rupees"] == 3950.0
    assert res_a["transaction_count"] == 3

    # User B: 500 + 800 = 1300 rupees (130000 paise), 2 transactions
    res_b = await tool_get_total_spending(db=session, user_id=user_b)
    assert res_b["total_paise"] == 130000
    assert res_b["total_rupees"] == 1300.0
    assert res_b["transaction_count"] == 2

    # Category isolation
    cat_a = await tool_get_spending_by_category(db=session, user_id=user_a, category="Food & Dining")
    assert cat_a["total_paise"] == 245000  # 2000 + 450
    assert cat_a["transaction_count"] == 2

    cat_b = await tool_get_spending_by_category(db=session, user_id=user_b, category="Food & Dining")
    assert cat_b["total_paise"] == 50000   # 500
    assert cat_b["transaction_count"] == 1

    # User B has no shopping expenses
    cat_b_shop = await tool_get_spending_by_category(db=session, user_id=user_b, category="Shopping")
    assert cat_b_shop["total_paise"] == 0
    assert cat_b_shop["transaction_count"] == 0


@pytest.mark.anyio
async def test_tool_get_category_breakdown(mock_dataset):
    """Verify category breakdown returns sorted categories."""
    session = mock_dataset["session"]
    user_a = mock_dataset["user_a"]

    res = await tool_get_category_breakdown(db=session, user_id=user_a)
    assert res["total_paise"] == 395000
    breakdown = res["breakdown"]
    assert len(breakdown) == 2
    # Food & Dining: 245000, Shopping: 150000 -> Food is highest
    assert breakdown[0]["category"] == "Food & Dining"
    assert breakdown[0]["total_paise"] == 245000
    assert breakdown[1]["category"] == "Shopping"
    assert breakdown[1]["total_paise"] == 150000


@pytest.mark.anyio
async def test_tool_get_recent_expenses(mock_dataset):
    """Verify recent expenses returns records for user with proper limit."""
    session = mock_dataset["session"]
    user_a = mock_dataset["user_a"]

    res = await tool_get_recent_expenses(db=session, user_id=user_a, limit=2)
    assert len(res["expenses"]) == 2
    assert res["count"] == 2


@pytest.mark.anyio
async def test_tool_get_highest_expense(mock_dataset):
    """Verify highest expense for User A is ₹2,000."""
    session = mock_dataset["session"]
    user_a = mock_dataset["user_a"]

    res = await tool_get_highest_expense(db=session, user_id=user_a)
    exp = res["expense"]
    assert exp is not None
    assert exp["amount_paise"] == 200000
    assert exp["amount_rupees"] == 2000.0
    assert exp["description"] == "Lunch with colleagues"


@pytest.mark.anyio
async def test_tool_get_spending_by_merchant(mock_dataset):
    """Verify merchant spending for Starbucks."""
    session = mock_dataset["session"]
    user_a = mock_dataset["user_a"]

    res = await tool_get_spending_by_merchant(db=session, user_id=user_a, merchant="Starbucks")
    assert res["total_paise"] == 45000
    assert res["total_rupees"] == 450.0
    assert res["transaction_count"] == 1


@pytest.mark.anyio
async def test_tool_get_daily_average_spending(mock_dataset):
    """Verify daily average spending over 1 day."""
    session = mock_dataset["session"]
    user_a = mock_dataset["user_a"]

    res = await tool_get_daily_average_spending(
        db=session,
        user_id=user_a,
        start_date="2026-11-22",
        end_date="2026-11-22",
    )
    assert res["days"] == 1
    assert res["total_paise"] == 245000  # On 2026-11-22 User A spent 2000 + 450
    assert res["average_daily_paise"] == 245000


@pytest.mark.anyio
async def test_tool_get_expenses_count(mock_dataset):
    """Verify counting transactions."""
    session = mock_dataset["session"]
    user_a = mock_dataset["user_a"]

    res = await tool_get_expenses_count(db=session, user_id=user_a)
    assert res["transaction_count"] == 3

    res_food = await tool_get_expenses_count(db=session, user_id=user_a, category="Food & Dining")
    assert res_food["transaction_count"] == 2


@pytest.mark.anyio
async def test_empty_query_results():
    """Verify clean response when user has zero recorded expenses."""
    empty_session = MockSession([], [])
    random_user = uuid.uuid4()

    res = await tool_get_total_spending(db=empty_session, user_id=random_user)
    assert res["total_paise"] == 0
    assert res["transaction_count"] == 0

    highest = await tool_get_highest_expense(db=empty_session, user_id=random_user)
    assert highest["expense"] is None
