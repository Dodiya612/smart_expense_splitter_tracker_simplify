"""The eight assistant query tools (app/ai/tools.py) on fixed service figures (no database).

Real PostgreSQL figures, the user's share and other users' data are covered in
tests/test_assistant_eval_pg.py.
"""

import json
import uuid
from datetime import date
from decimal import Decimal
from typing import get_args

import pytest
from pydantic import ValidationError

from app.ai import tools
from app.ai.grounding import find_violations
from app.models.user import User
from app.schemas.assistant import ToolName
from tests.assistant_fakes import FOOD_ID, GROUP_ID, FakeServices, budget, rule

TODAY = date(2026, 11, 24)  # a Tuesday
USER = User(id=uuid.uuid4(), email="alex@example.com", name="Alex", hashed_password="x", is_active=True)
DOCUMENTED = {
    "spend_total", "spend_by_category", "compare_periods", "top_merchants",
    "budget_status", "owed_summary", "recurring_upcoming", "list_expenses",
}


async def run(name: str, **slots):
    spec = tools.TOOLS[name]
    return await spec.run(None, USER, spec.slots.model_validate(slots), TODAY)


def pairs(result):
    return [(f.label, f.amount_paise) for f in result.figures], [(c.label, c.value) for c in result.counts]


def _keys(schema) -> set[str]:
    found: set[str] = set()
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties":
                found |= set(value)
            found |= _keys(value)
    elif isinstance(schema, list):
        for value in schema:
            found |= _keys(value)
    return found


def test_exactly_the_eight_documented_tools_and_no_id_slots():
    assert set(tools.TOOLS) == DOCUMENTED == tools.ALLOWED_TOOL_NAMES == set(get_args(ToolName))
    for definition in tools.tool_definitions():
        keys = _keys(definition["slots"])
        assert not any("id" in k.split("_") or k in {"user", "users", "sql", "query"} for k in keys), keys


# ---- 1. spend_total ---------------------------------------------------------------------


@pytest.mark.anyio
async def test_spend_total_is_the_analytics_share_for_the_period(monkeypatch):
    fake = FakeServices(share_paise=70000, expense_count=3).install(monkeypatch)
    result = await run("spend_total", period={"date_range": "last_week"})
    assert fake.calls == [("summary", {"from": date(2026, 11, 16), "to": date(2026, 11, 22), "group_id": None})]
    assert pairs(result) == ([("Total spending", 70000)], [("Expenses", 3)])
    assert result.template_answer() == "You spent ₹700.00 across 3 expenses last week (16 Nov 2026 – 22 Nov 2026)."


@pytest.mark.anyio
async def test_spend_total_in_one_category_and_as_a_count(monkeypatch):
    FakeServices(categories=[("Food & Dining", 50000, 2), ("Groceries", 20000, 1)]).install(monkeypatch)
    food = await run("spend_total", category="Food & Dining", period={"date_range": "this_month"})
    assert pairs(food) == ([("Food & Dining spending", 50000)], [("Expenses", 2)])
    count = await run("spend_total", category="Groceries", measure="count")
    assert count.template_answer() == (
        "You recorded 1 expense in Groceries this month so far (1 Nov 2026 – 24 Nov 2026), ₹200.00 in total."
    )
    none = await run("spend_total", category="Health")
    assert none.template_answer().startswith("You have no spending on Health recorded")


@pytest.mark.anyio
async def test_daily_average_ends_today_and_rounds_to_the_nearest_paisa(monkeypatch):
    fake = FakeServices(share_paise=100001, expense_count=4).install(monkeypatch)
    result = await run("spend_total", measure="daily_average", period={"date_range": "this_month"})
    # This month is 1-30 Nov, but only 24 days have happened: average over 24, not 30.
    assert fake.calls[0][1]["to"] == TODAY
    assert result.period.label == "this month so far" and result.period.days == 24
    assert pairs(result) == (
        [("Average per day", 4167), ("Total spending", 100001)],  # 100001 / 24 = 4166.7
        [("Days", 24), ("Expenses", 4)],
    )


# ---- 2. spend_by_category ---------------------------------------------------------------


@pytest.mark.anyio
async def test_category_breakdown_total_is_the_real_total_not_the_sum_of_the_top(monkeypatch):
    cats = [(f"Cat {i}", 1000 * (10 - i), 1) for i in range(7)]
    FakeServices(categories=cats).install(monkeypatch)
    result = await run("spend_by_category", limit=3)
    figures, counts = pairs(result)
    assert figures[0] == ("Total spending", sum(c[1] for c in cats))
    assert figures[1:] == [("Cat 0", 10000), ("Cat 1", 9000), ("Cat 2", 8000)]
    assert counts == [("Categories", 7), ("Categories not listed", 4)]
    assert "Plus 4 more categories." in result.template_answer()
    assert result.percentages == {Decimal("20.4"), Decimal("18.4"), Decimal("16.3")}  # of 49000, not of 27000


# ---- 3. compare_periods -----------------------------------------------------------------


@pytest.mark.anyio
async def test_compare_periods_states_both_totals_the_difference_and_the_change(monkeypatch):
    fake = FakeServices().install(monkeypatch)
    totals = iter([(90000, 3), (60000, 2)])

    async def spending(db, user, period, category):
        return next(totals)

    monkeypatch.setattr(tools, "_spending", spending)
    result = await run("compare_periods", a={"date_range": "this_month"}, b={"date_range": "last_month"})
    assert pairs(result) == (
        [("Spending this month", 90000), ("Spending last month", 60000), ("Difference", 30000)],
        [("Expenses this month", 3), ("Expenses last month", 2)],
    )
    assert result.template_answer() == (
        "You spent ₹900.00 this month (1 Nov 2026 – 30 Nov 2026), ₹300.00 more than the ₹600.00 "
        "last month (1 Oct 2026 – 31 Oct 2026). That is 50.0% more."
    )
    assert result.period.label == "this month" and fake.calls == []
    assert not find_violations(result.template_answer(), result.allowed())


@pytest.mark.anyio
async def test_compare_periods_in_a_category_and_the_same_period_twice(monkeypatch):
    FakeServices(categories=[("Food & Dining", 50000, 2)]).install(monkeypatch)
    result = await run("compare_periods", a={"month": "october"}, b={"month": "november"}, category="Food & Dining")
    assert result.figures[0].label == "Food & Dining spending in October 2026"
    assert "₹500.00 on Food & Dining both" in result.template_answer()
    with pytest.raises(tools.ToolInputError):
        await run("compare_periods", a={"date_range": "last_week"}, b={"date_range": "last_week"})


# ---- 4. top_merchants -------------------------------------------------------------------


@pytest.mark.anyio
async def test_top_merchants_names_the_largest_and_keeps_names_from_the_model(monkeypatch):
    FakeServices(merchants=[("Swiggy", 40000, 2), ("Uber", 30000, 1), ("PVR", 5000, 1)]).install(monkeypatch)
    result = await run("top_merchants", n=2, period={"date_range": "last_month"})
    assert pairs(result) == ([("Swiggy", 40000), ("Uber", 30000)], [("Merchants", 3), ("Merchants shown", 2)])
    assert result.template_answer() == (
        "You spent at 3 merchants last month (1 Oct 2026 – 31 Oct 2026). The top 2 merchants: "
        "Swiggy ₹400.00 (2 expenses); Uber ₹300.00 (1 expense)."
    )
    assert "Swiggy" not in json.dumps(result.shared_values())


# ---- 5. budget_status -------------------------------------------------------------------


@pytest.mark.anyio
async def test_budget_status_lists_each_budget_with_its_progress(monkeypatch):
    week = (date(2026, 11, 23), date(2026, 11, 29))
    month = (date(2026, 11, 1), date(2026, 11, 30))
    FakeServices(budgets=[
        budget("monthly", 2000000, 1700000, *month),
        budget("weekly", 100000, 125000, *week, category_id=FOOD_ID),
    ]).install(monkeypatch)
    result = await run("budget_status")
    assert result.template_answer() == (
        "You have 2 budgets. Monthly overall budget: ₹17,000.00 of ₹20,000.00 spent (85%), ₹3,000.00 left, "
        "close to the limit (1 Nov 2026 – 30 Nov 2026). Weekly Food & Dining budget: ₹1,250.00 of ₹1,000.00 "
        "spent (125%), ₹250.00 over the limit (23 Nov 2026 – 29 Nov 2026)."
    )
    assert pairs(result)[1] == [("Budgets", 2), ("Over the limit", 1)]
    assert result.percentages == {Decimal(85), Decimal(125)} and result.period is None
    food = await run("budget_status", category="Food & Dining")
    assert food.period.label == "this week" and [f.amount_paise for f in food.figures] == [125000, 100000, 25000]
    none = await run("budget_status", category="Health")
    assert none.template_answer() == "You have no budget for Health." and none.figures == []


# ---- 6. owed_summary --------------------------------------------------------------------


@pytest.mark.anyio
async def test_owed_summary_across_groups_and_for_one_named_group(monkeypatch):
    fake = FakeServices(owed_to_you_paise=156666, you_owe_paise=0, groups=["Flat Expenses"]).install(monkeypatch)
    every = await run("owed_summary")
    assert every.template_answer() == "Across your groups, others owe you ₹1,566.66 and you owe ₹0.00."
    one = await run("owed_summary", group="the flat expenses group")
    assert ("summary", {"from": None, "to": None, "group_id": GROUP_ID}) in fake.calls
    assert one.template_answer() == "In Flat Expenses, others owe you ₹1,566.66 and you owe ₹0.00."
    with pytest.raises(tools.ToolInputError, match="couldn't find a group called 'Goa Trip'"):
        await run("owed_summary", group="Goa Trip")


# ---- 7. recurring_upcoming --------------------------------------------------------------


@pytest.mark.anyio
async def test_recurring_upcoming_lists_occurrences_due_in_the_window(monkeypatch):
    FakeServices(rules=[
        rule("Netflix", 64900, date(2026, 1, 28)),  # monthly on the 28th
        rule("Gym", 150000, date(2026, 1, 5)),  # next on 5 Dec: outside 7 days
        rule("Milk", 6000, date(2026, 11, 1), frequency="weekly", next_run=date(2026, 11, 22)),  # Sundays
    ]).install(monkeypatch)
    result = await run("recurring_upcoming", days=7)
    assert (result.period.start, result.period.end, result.period.label) == (TODAY, date(2026, 11, 30), "in the next 7 days")
    assert pairs(result) == (
        [("Total due", 70900), ("Netflix on 28 Nov 2026", 64900), ("Milk on 29 Nov 2026", 6000)],
        [("Recurring expenses due", 2)],
    )
    month = await run("recurring_upcoming", days=31)
    assert [f.label for f in month.figures[1:]] == [
        "Netflix on 28 Nov 2026", "Milk on 29 Nov 2026", "Gym on 5 Dec 2026", "Milk on 6 Dec 2026",
        "Milk on 13 Dec 2026", "Milk on 20 Dec 2026",
    ]
    assert "Netflix" not in json.dumps(result.shared_values())


# ---- 8. list_expenses -------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_expenses_rows_come_only_from_the_template(monkeypatch):
    fake = FakeServices().install(monkeypatch)
    result = await run("list_expenses", filters={"merchant": "Swiggy", "category": "Food & Dining"}, sort="largest")
    (_, call), = fake.calls
    assert call == {"from": date(2024, 11, 24), "to": TODAY, "category": "Food & Dining", "merchant": "Swiggy",
                    "sort": "largest", "limit": 5}  # no period named: the last two years
    assert result.model_wording is False
    assert result.template_answer() == (
        "You have 2 expenses on Food & Dining at Swiggy in the last 2 years (24 Nov 2024 – 24 Nov 2026), ₹700.00 in "
        "total. Largest first: 20 Nov 2026 Dinner (Swiggy) ₹400.00; 18 Nov 2026 Cab (Uber) ₹300.00."
    )
    assert "Dinner" not in json.dumps(result.shared_values())


# ---- every tool ---------------------------------------------------------------------------

CASES = [
    ("spend_total", {"period": {"date_range": "this_week"}}),
    ("spend_total", {"measure": "daily_average", "category": "Groceries"}),
    ("spend_total", {"measure": "count", "period": {"last_days": 7}}),
    ("spend_by_category", {"period": {"month": "october"}}),
    ("compare_periods", {"a": {"date_range": "this_week"}, "b": {"date_range": "last_week"}}),
    ("top_merchants", {"period": {"date_range": "all_time"}}),
    ("budget_status", {}),
    ("owed_summary", {"group": "Flat Expenses"}),
    ("recurring_upcoming", {"days": 31}),
    ("list_expenses", {"filters": {"period": {"start_date": "2026-11-01", "end_date": "2026-11-20"}}}),
]


@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "slots"), CASES)
@pytest.mark.parametrize("empty", [False, True])
async def test_every_template_passes_the_grounding_guard(monkeypatch, tool, slots, empty):
    if empty:
        FakeServices(share_paise=0, expense_count=0, categories=[], merchants=[], rows=[]).install(monkeypatch)
    else:
        FakeServices(
            owed_to_you_paise=12345, you_owe_paise=678,
            budgets=[budget("monthly", 500000, 412300, date(2026, 11, 1), date(2026, 11, 30))],
            rules=[rule("Rent 2BHK, flat 4", 1500000, date(2026, 1, 1))],
            rows=[(date(2026, 11, 2), "2 pizzas for 4 people", None, "Food & Dining", 99900)],
        ).install(monkeypatch)
    result = await run(tool, **slots)
    assert find_violations(result.template_answer(), result.allowed()) == [], result.template_answer()


@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "slots"), CASES)
async def test_values_shared_with_the_model_hold_no_stored_text_or_ids(monkeypatch, tool, slots):
    secret = "Dinner with Priya at 22 Baker Street"
    FakeServices(
        categories=[(secret, 50000, 1)], merchants=[(secret, 50000, 1)],
        rows=[(date(2026, 11, 2), secret, secret, secret, 50000)],
        budgets=[budget("monthly", 500000, 1000, date(2026, 11, 1), date(2026, 11, 30), category_id=FOOD_ID)],
        names={FOOD_ID: secret}, rules=[rule(secret, 1000, date(2026, 11, 25))], groups=[secret],
    ).install(monkeypatch)
    try:
        result = await run(tool, **slots)
    except tools.ToolInputError:
        return  # "Flat Expenses" is not among the user's groups here
    shared = json.dumps(result.shared_values())
    assert secret not in shared and str(USER.id) not in shared


@pytest.mark.parametrize(
    ("tool", "slots"),
    [
        ("spend_total", {"user_id": str(uuid.uuid4())}),
        ("spend_total", {"period": {"date_range": "last_week", "month": "may"}}),
        ("spend_total", {"category": "Coffee"}),
        ("spend_total", {"measure": "median"}),
        ("spend_by_category", {"limit": 13}),
        ("compare_periods", {"a": {"date_range": "this_month"}}),
        ("top_merchants", {"n": 11}),
        ("budget_status", {"budget_id": str(uuid.uuid4())}),
        ("owed_summary", {"group_id": str(GROUP_ID)}),
        ("owed_summary", {"group": "x" * 61}),
        ("recurring_upcoming", {"days": 32}),
        ("list_expenses", {"limit": 11}),
        ("list_expenses", {"filters": {"merchant": "Swiggy'; DROP TABLE expenses; --"}}),
        ("list_expenses", {"filters": {"expense_id": str(uuid.uuid4())}}),
    ],
)
def test_invalid_slots_are_rejected(tool, slots):
    with pytest.raises(ValidationError):
        tools.TOOLS[tool].slots.model_validate(slots)
