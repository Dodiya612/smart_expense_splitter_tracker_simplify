"""The assistant on real PostgreSQL: the frozen 60 questions (T-57 Done-when).

A throwaway database is built by the Alembic migrations (the fixtures of
tests/test_analytics_pg.py) and dropped afterwards; without a local PostgreSQL
the module is skipped with the reason. Same COINSCIOUS_TEST_PG_URL setting as
the other *_pg.py tests; it never connects anywhere else and never calls Groq.

Dataset (reference date 2026-11-24, from evals/assistant/questions.json): Alex
has personal expenses, shares of four expenses in the Flat Expenses group with
Blair and Casey, a settlement from Blair, a deleted expense, three budgets and
recurring rules (personal, one group rule, one paused). Blair and Sam (a
stranger) have expenses, a budget and a rule of their own with marker amounts
that must never appear in Alex's answers.

Checks:
1. Stubbed model (returns the expected tool call): every question gets the right
   tool and slots, the exact period, and figures equal both to the frozen values
   in questions.json and to the services (analytics, budget, recurring, group
   balances) for Alex and that period (exact paise).
2. Offline parser (no model) on the same questions: accuracy at least 90%.
3. Adversarial wording: a model that rewrites answers with wrong numbers never
   gets one to the user; the right figure in Indian or western grouping is kept.
4. Quota: one answered question writes exactly one ai_usage_log row; over quota
   gives the fallback with HTTP 200 and no row; no model means no quota use.
5. The ₹700 example: personal ₹200 + share ₹200 of a ₹600 bill Alex paid + share
   ₹300 of Blair's ₹900 bill is ₹700, not ₹800.
6. Every fallback suggestion is answered through the API; list_expenses rows
   never reach the model; a stranger sees none of Alex's figures; the T-52
   total-spending shortcut uses the two-year cap.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.ai import assistant_service, fallbacks, tools
from app.ai.grounding import format_rupees
from app.core.config import settings
from app.models.ai_usage_log import AIUsageLog
from app.models.budget import Budget
from app.models.category import Category
from app.models.recurring import RecurringRule
from app.services import analytics_service, budget_service, group_service, recurring_service, shared_expense_service
from app.services.date_ranges import PeriodSlots, RelativePeriod, format_day, resolve_period
from tests import test_analytics_pg as analytics_pg
from tests.assistant_fakes import StubLLM
from tests.test_analytics_pg import FOOD, GROCERIES, TRAVEL, add_shared, bearer, seed_demo, settle

# Fixtures from tests/test_analytics_pg.py: a database migrated by Alembic, a fresh copy
# per test (dropped afterwards), and the app running on it.
migrated_template = analytics_pg.migrated_template
pg = analytics_pg.pg
api = analytics_pg.api

QUESTIONS = json.loads(
    (Path(__file__).resolve().parents[2] / "evals" / "assistant" / "questions.json").read_text(encoding="utf-8")
)
TODAY = date.fromisoformat(QUESTIONS["reference_date"])
ITEMS: list[dict[str, Any]] = QUESTIONS["questions"]
ASK = "/api/v1/ai/ask"
NOW = datetime(2026, 11, 1, tzinfo=UTC)


def cat(n: int) -> uuid.UUID:
    return uuid.UUID(f"00000000-0000-4000-8000-{n:012d}")


SHOPPING, BILLS, RENT, ENTERTAINMENT, HEALTH, EDUCATION, PERSONAL_CARE, GIFTS = (cat(n) for n in range(4, 12))
STRANGER_MARKERS = ("7,777", "7777", "777777", "4,444", "4444", "444444")


@pytest.fixture(autouse=True)
def assistant_settings(monkeypatch):
    """Reference date, room for many questions, and never the real Groq API."""
    monkeypatch.setattr(assistant_service, "today_in_kolkata", lambda: TODAY)
    monkeypatch.setattr(budget_service, "today_in_kolkata", lambda: TODAY)
    monkeypatch.setattr(assistant_service, "get_llm_client", lambda: StubLLM(configured=False))
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    monkeypatch.setattr(settings, "AI_QUOTA_ASK_DAILY", 10_000)
    monkeypatch.setattr(settings, "RATE_LIMIT_AI_BURST_USER_MAX", 10_000)


async def add_personal(api, user, amount, category, day, description, merchant=None):
    body = {"amount_paise": amount, "description": description, "category_id": str(category),
            "expense_date": day.isoformat()}
    if merchant:
        body["merchant"] = merchant
    resp = await api.post("/api/v1/expenses", json=body, headers=bearer(user))
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def add_group_expense(api, group, payer, amount, category, day, description, merchant=None):
    body = {"amount_paise": amount, "description": description, "category_id": str(category),
            "split_mode": "equal", "expense_date": day.isoformat()}
    if merchant:
        body["merchant"] = merchant
    resp = await api.post(f"/api/v1/groups/{group.id}/expenses", json=body, headers=bearer(payer))
    assert resp.status_code == 201, resp.text


def add_rule(session, owner, description, amount, category, start, frequency="monthly", next_run=None,
             group=None, status="active"):
    session.add(RecurringRule(
        id=uuid.uuid4(), owner_id=owner.id, group_id=group.id if group else None, frequency=frequency,
        start_date=start, next_run_date=next_run or start, status=status, amount_paise=amount,
        category_id=category, description=description, created_at=NOW, updated_at=NOW,
    ))


@pytest.fixture
async def world(pg, api):
    w = await seed_demo(pg["sessions"])
    alex, blair, sam, group = w["alex"], w["blair"], w["sam"], w["group"]
    d = date
    for amount, category, day, description, merchant in [
        (35000, FOOD, d(2026, 11, 24), "Cafe latte", "Starbucks"),
        (28000, TRAVEL, d(2026, 11, 23), "Cab to office", "Uber"),
        (95000, GROCERIES, d(2026, 11, 18), "Weekly vegetables", "Blinkit"),
        (50000, ENTERTAINMENT, d(2026, 11, 17), "Movie tickets", "PVR"),
        (120000, SHOPPING, d(2026, 11, 5), "T-shirt and jeans", "Amazon"),
        (220000, BILLS, d(2026, 11, 10), "Electricity bill", "Adani Power"),
        (1500000, RENT, d(2026, 10, 15), "Flat rent", "Landlord"),
        (85000, HEALTH, d(2026, 10, 20), "Vitamins", "Apollo Pharmacy"),
        (300000, EDUCATION, d(2026, 10, 8), "Python course", "Coursera"),
        (45000, FOOD, d(2026, 10, 12), "Lunch order", "Swiggy"),
        (100000, GIFTS, d(2025, 12, 12), "Birthday gift", "Ferns N Petals"),
        (60000, PERSONAL_CARE, d(2026, 3, 14), "Haircut", "Enrich"),
        (12500000, SHOPPING, d(2026, 6, 10), "Laptop", "Croma"),
    ]:
        await add_personal(api, alex, amount, category, day, description, merchant)
    deleted = await add_personal(api, alex, 999900, FOOD, d(2026, 11, 20), "Late night order", "Swiggy")
    assert (await api.delete(f"/api/v1/expenses/{deleted['id']}", headers=bearer(alex))).status_code == 200

    # Group of three (Alex, Blair, Casey), equal splits; Alex gets the extra paisa.
    await add_group_expense(api, group, alex, 60000, FOOD, d(2026, 11, 19), "Swiggy dinner", "Swiggy")  # 20000
    await add_group_expense(api, group, blair, 90000, GROCERIES, d(2026, 11, 21), "Groceries", "DMart")  # 30000
    await add_group_expense(api, group, w["casey"], 10000, FOOD, d(2026, 11, 24), "Chai")  # 3334
    await add_group_expense(api, group, alex, 300000, TRAVEL, d(2026, 10, 28), "Airport cab", "Uber")  # 100000
    await settle(api, group, blair, alex, 50000)  # never spending

    # Other people's data with marker amounts.
    await add_personal(api, blair, 444444, FOOD, d(2026, 11, 20), "Dinner", "Swiggy")
    await add_personal(api, sam, 777777, FOOD, d(2026, 11, 22), "Dinner", "Swiggy")

    async with pg["sessions"]() as s:
        s.add_all([
            Budget(id=uuid.uuid4(), user_id=alex.id, period="monthly", category_id=None, limit_paise=700000,
                   created_at=NOW, updated_at=NOW),
            Budget(id=uuid.uuid4(), user_id=alex.id, period="monthly", category_id=FOOD, limit_paise=50000,
                   created_at=NOW + timedelta(seconds=1), updated_at=NOW),
            Budget(id=uuid.uuid4(), user_id=alex.id, period="weekly", category_id=GROCERIES, limit_paise=100000,
                   created_at=NOW + timedelta(seconds=2), updated_at=NOW),
            Budget(id=uuid.uuid4(), user_id=blair.id, period="monthly", category_id=None, limit_paise=444444,
                   created_at=NOW, updated_at=NOW),
        ])
        add_rule(s, alex, "Netflix", 64900, ENTERTAINMENT, d(2026, 1, 28), next_run=d(2026, 11, 28))
        add_rule(s, alex, "Gym membership", 150000, HEALTH, d(2026, 1, 5), next_run=d(2026, 12, 5))
        add_rule(s, alex, "Milk", 6000, GROCERIES, d(2026, 11, 1), frequency="weekly", next_run=d(2026, 11, 29))
        add_rule(s, alex, "Flat internet", 90000, BILLS, d(2026, 6, 26), next_run=d(2026, 11, 26), group=group)
        add_rule(s, alex, "Magazine", 25000, ENTERTAINMENT, d(2026, 11, 25), status="paused")
        add_rule(s, blair, "Music", 444444, ENTERTAINMENT, d(2026, 11, 25))
        await s.commit()
    return w


async def ask(api, user, question):
    resp = await api.post(ASK, json={"question": question}, headers=bearer(user))
    assert resp.status_code == 200, resp.text
    for marker in STRANGER_MARKERS:
        assert marker not in resp.text, (question, marker)
    return resp.json()["data"]


def item_for(question: str) -> dict[str, Any]:
    return next(i for i in ITEMS if i["question"] == question)


def expected_choice(question: str) -> dict[str, Any]:
    item = item_for(question)
    return {"tool": item["expected_tool"], "slots": item["expected_slots"]}


def as_pairs(data: dict[str, Any]) -> tuple[list[list[Any]], list[list[Any]]]:
    return (
        [[f["label"], f["amountPaise"]] for f in data["figures"]],
        [[c["label"], c["value"]] for c in data["counts"]],
    )


# ---------------------------------------------------------------------------
# Expected figures, straight from the services
# ---------------------------------------------------------------------------


def _half_up(total: int, days: int) -> int:
    return int((Decimal(total) / days).quantize(Decimal(1), rounding=ROUND_HALF_UP))


async def _spending(s, user, start, end, category):
    if category is None:
        r = await analytics_service.get_summary(s, user, start, end)
        return r.share_paise, r.expense_count
    c = await analytics_service.get_categories(s, user, start, end)
    items = [i for i in c.categories if i.category_name == category]
    return sum(i.share_paise for i in items), sum(i.expense_count for i in items)


def _period(slots: dict[str, Any] | None, default: PeriodSlots | None = None):
    period = PeriodSlots.model_validate(slots or {})
    if period.is_empty() and default is not None:
        period = default
    return resolve_period(period, TODAY)


async def service_figures(sessions, user, tool: str, slots: dict[str, Any]):
    """(figures, counts) as [label, value] lists, computed from the services for this user."""
    async with sessions() as s:
        if tool == "spend_total":
            p = _period(slots.get("period"))
            category = slots.get("category")
            measure = slots.get("measure", "total")
            if measure == "daily_average":
                p = type(p)(p.start, min(p.end, TODAY), p.label)
            total, count = await _spending(s, user, p.start, p.end, category)
            label = f"{category} spending" if category else "Total spending"
            if measure == "daily_average":
                return [["Average per day", _half_up(total, p.days)], [label, total]], [["Days", p.days], ["Expenses", count]]
            return [[label, total]], [["Expenses", count]]
        if tool == "spend_by_category":
            p = _period(slots.get("period"))
            c = await analytics_service.get_categories(s, user, p.start, p.end)
            spent = [i for i in c.categories if i.share_paise > 0]
            limit = slots.get("limit", 5)
            counts = [["Categories", len(spent)]]
            if len(spent) > limit:
                counts.append(["Categories not listed", len(spent) - limit])
            return [["Total spending", c.total_share_paise], *([i.category_name, i.share_paise] for i in spent[:limit])], counts
        if tool == "compare_periods":
            a, b = _period(slots["a"]), _period(slots["b"])
            category = slots.get("category")
            ta, ca = await _spending(s, user, a.start, a.end, category)
            tb, cb = await _spending(s, user, b.start, b.end, category)
            prefix = f"{category} spending" if category else "Spending"
            return (
                [[f"{prefix} {a.label}", ta], [f"{prefix} {b.label}", tb], ["Difference", abs(ta - tb)]],
                [[f"Expenses {a.label}", ca], [f"Expenses {b.label}", cb]],
            )
        if tool == "top_merchants":
            p = _period(slots.get("period"))
            merchants = await analytics_service.get_merchants(s, user, p.start, p.end)
            n = slots.get("n", 5)
            counts = [["Merchants", len(merchants)]]
            if len(merchants) > n:
                counts.append(["Merchants shown", n])
            return [[m.merchant, m.share_paise] for m in merchants[:n]], counts
        if tool == "budget_status":
            budgets, _ = await budget_service.list_budgets(s, user, 100, 0)
            names = dict((await s.execute(select(Category.id, Category.name))).all())
            if "category" in slots:
                budgets = [b for b in budgets if b.category_id and names[b.category_id] == slots["category"]]
            figures = []
            for b in budgets:
                label = f"{b.period.title()} {names[b.category_id] if b.category_id else 'overall'} budget"
                p = b.progress
                last = [f"{label} over", p.over_by_paise] if p.status == "exceeded" else [f"{label} left", p.remaining_paise]
                figures += [[f"{label} spent", p.spent_paise], [f"{label} limit", b.limit_paise], last]
            if not budgets:
                return [], [["Budgets", 0]]
            over = sum(1 for b in budgets if b.progress.status == "exceeded")
            return figures, [["Budgets", len(budgets)], ["Over the limit", over]]
        if tool == "owed_summary":
            group_id = None
            if "group" in slots:
                mine = await group_service.list_user_groups(s, user)
                group_id = next(g.id for g in mine if g.name.casefold() == slots["group"].casefold())
            r = await analytics_service.get_summary(s, user, group_id=group_id)
            return [["Owed to you", r.owed_to_you_paise], ["You owe", r.you_owe_paise]], []
        if tool == "recurring_upcoming":
            days = slots.get("days", 7)
            last = TODAY + timedelta(days=days - 1)
            rules, _ = await recurring_service.list_rules(s, user, "active", 100, 0)
            due = []
            for r in rules:
                share = r.amount_paise
                if r.group_id is not None:
                    group = await group_service.get_group_or_404(s, r.group_id)
                    request = recurring_service.shared_expense_request(
                        {"amount_paise": r.amount_paise, "description": r.description, "category_id": r.category_id},
                        None, None,
                    )
                    share = shared_expense_service.resolve_split(group, user, request)[2][str(user.id)]
                for day in recurring_service.schedule_between(r.start_date, r.frequency, r.end_date,
                                                              max(r.next_run_date, TODAY), last):
                    due.append((day, r.description, share))
            due.sort()
            return (
                [["Total due", sum(x[2] for x in due)], *([f"{desc} on {format_day(day)}", sh] for day, desc, sh in due[:10])],
                [["Recurring expenses due", len(due)]],
            )
        # list_expenses
        filters = slots.get("filters", {})
        p = _period(filters.get("period"), PeriodSlots(date_range=RelativePeriod.ALL_TIME))
        found = await analytics_service.get_expense_rows(
            s, user, p.start, p.end, category=filters.get("category"), merchant=filters.get("merchant"),
            sort=slots.get("sort", "recent"), limit=slots.get("limit", 5),
        )
        return (
            [["Total spending", found.total_share_paise],
             *([f"{format_day(r.expense_date)} {r.description}", r.share_paise] for r in found.rows)],
            [["Expenses", found.expense_count], ["Shown", len(found.rows)]],
        )


def expected_source(item: dict[str, Any], model: bool) -> str:
    if item["expected_answer"] == "fallback":
        return "fallback"
    return "llm" if model and item["expected_tool"] != "list_expenses" else "template"


def check(data: dict[str, Any], item: dict[str, Any], model: bool) -> None:
    assert data["source"] == expected_source(item, model), item
    if item["expected_answer"] == "fallback":
        assert data["tool"] is None and data["figures"] == [] and data["counts"] == [] and data["suggestions"]
        if item.get("expected_reason"):
            assert data["answer"].startswith(item["expected_reason"]), data["answer"]
        return
    assert data["tool"] == item["expected_tool"], item
    assert data["period"] == item["expected_period"], item
    assert as_pairs(data) == (item["expected_figures"], item["expected_counts"]), item


# ---------------------------------------------------------------------------
# 1. Stubbed model: tool, slots, period, exact figures
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sixty_questions_with_a_stubbed_model_match_the_frozen_and_service_figures(
    pg, api, world, monkeypatch, record_property
):
    stub = StubLLM(selection=expected_choice)
    monkeypatch.setattr(assistant_service, "get_llm_client", lambda: stub)
    alex = world["alex"]
    assert len(ITEMS) == 60

    correct = 0
    for item in ITEMS:
        data = await ask(api, alex, item["question"])
        if item["expected_tool"] is not None:
            # The model's slots validate to exactly the expected slots.
            choice = assistant_service.choose_from_model(expected_choice(item["question"]))
            assert choice.tool == item["expected_tool"] and choice.fallback is None
            if item["expected_answer"] != "fallback":
                assert as_pairs(data) == tuple(
                    await service_figures(pg["sessions"], alex, item["expected_tool"], item["expected_slots"])
                ), item
        check(data, item, model=True)
        correct += 1
    # The model saw each question once, with only the tool definitions.
    assert [q for q, _ in stub.selection_calls] == [i["question"] for i in ITEMS]
    record_property("stubbed_model_correct", f"{correct}/60")
    assert correct == 60


# ---------------------------------------------------------------------------
# 2. Offline parser on the same questions
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_offline_parser_answers_at_least_ninety_percent(pg, api, world, record_property):
    alex = world["alex"]
    misses = []
    for item in ITEMS:
        data = await ask(api, alex, item["question"])
        try:
            check(data, item, model=False)
        except AssertionError:
            misses.append(item["id"])
    correct = len(ITEMS) - len(misses)
    record_property("offline_parser_correct", f"{correct}/60")
    assert correct >= 54, f"offline parser {correct}/60, missed {misses}"


# ---------------------------------------------------------------------------
# 3. Adversarial wording
# ---------------------------------------------------------------------------


def _western(paise: int) -> str:
    rupees, rest = divmod(paise, 100)
    return f"₹{rupees:,}.{rest:02d}"


def attacks(main_paise: int | None, count: int | None, p: str) -> list[tuple[str, str, int | None, int | None]]:
    """(name, wording, wrong amount in paise, wrong count) - each must never reach the user."""
    out: list[tuple[str, str, int | None, int | None]] = [
        ("number words", f"You spent fifteen hundred rupees, {p}.", None, None),
        ("made-up percentage", f"That is 37.5% more than usual, {p}.", None, None),
        ("wrong date", f"Your biggest day was 25 Dec 2026, {p}.", None, None),
        ("devanagari digits", f"You spent ₹१,२००.०० {p}.", None, None),
        ("shorthand", f"You spent about ₹2.4k {p}.", None, None),
        ("made-up amount in Indian grouping", f"You spent ₹1,23,456.78 {p}.", 12345678, None),
    ]
    if main_paise:
        out.append(("negative of a real amount", f"Your balance is -{format_rupees(main_paise)} {p}.", None, None))
    if main_paise is not None and main_paise >= 100:
        out.append(("amount divided by 100", f"You spent {format_rupees(main_paise // 100)} {p}.", main_paise // 100, None))
        out.append(("paise shown as rupees", f"You spent {format_rupees(main_paise * 100)} {p}.", main_paise * 100, None))
    if count is not None:
        out.append(("extra count", f"You recorded {count + 1} expenses, {p}.", None, count + 1))
    return out


@pytest.mark.anyio
async def test_a_model_writing_wrong_numbers_never_reaches_the_user(pg, api, world, monkeypatch, record_property):
    alex = world["alex"]
    stub = StubLLM(selection=expected_choice)
    monkeypatch.setattr(assistant_service, "get_llm_client", lambda: stub)
    attempts = blocked = leaked = correct_kept = 0

    for item in ITEMS:
        if item["expected_answer"] == "fallback":
            continue
        stub.wording = None  # no wording: the template sentence
        template = await ask(api, alex, item["question"])
        assert template["source"] == "template"
        allowed_amounts = {f["amountPaise"] for f in template["figures"]}
        allowed_counts = {c["value"] for c in template["counts"]}
        main = template["figures"][0]["amountPaise"] if template["figures"] else None
        count = template["counts"][0]["value"] if template["counts"] else None
        facts = stub.wording_calls[-1][2] if stub.wording_calls and item["expected_tool"] != "list_expenses" else {}
        placeholder = "{" + next(iter(facts), "period") + "}"

        for name, wording, amount, stated_count in attacks(main, count, placeholder):
            if amount in allowed_amounts or stated_count in allowed_counts:
                continue  # the number is one the tool returned, so not wrong for this question
            stub.wording = wording
            data = await ask(api, alex, item["question"])
            attempts += 1
            if data["source"] == "template" and data["answer"] == template["answer"]:
                blocked += 1
            else:
                leaked += 1
                pytest.fail(f"{name} reached the user for question {item['id']}: {data['answer']}")

        if main is not None and item["expected_tool"] != "list_expenses":
            for text in (format_rupees(main), _western(main)):  # the right figure, either grouping
                stub.wording = f"That comes to {text}, {placeholder}."
                data = await ask(api, alex, item["question"])
                assert data["source"] == "llm" and text in data["answer"], (item["id"], text, data["answer"])
                correct_kept += 1

    record_property("adversarial", f"attempts={attempts} blocked={blocked} leaked={leaked} correct_kept={correct_kept}")
    assert attempts > 0 and leaked == 0 and blocked == attempts
    # The dataset makes Indian grouping real: this year's total is over ₹1,00,000.
    assert format_rupees(12500000) == "₹1,25,000.00"


# ---------------------------------------------------------------------------
# 4. Quota: one row per answered question; over quota is a 200 fallback
# ---------------------------------------------------------------------------


async def usage_rows(sessions) -> list[tuple[str, str]]:
    async with sessions() as s:
        rows = (await s.execute(select(AIUsageLog.feature, AIUsageLog.status).order_by(AIUsageLog.created_at))).all()
    return [tuple(r) for r in rows]


@pytest.mark.anyio
async def test_quota_one_usage_row_per_answer_and_a_fallback_over_quota(pg, api, world, monkeypatch):
    alex = world["alex"]
    question = "How much did I spend this week?"
    sessions = pg["sessions"]

    # No model configured: answered offline, no quota used.
    data = await ask(api, alex, question)
    assert data["source"] == "template" and await usage_rows(sessions) == []

    # With a model: exactly one row, finalized as success.
    monkeypatch.setattr(assistant_service, "get_llm_client", lambda: StubLLM(selection=expected_choice))
    monkeypatch.setattr(settings, "AI_QUOTA_ASK_DAILY", 1)
    data = await ask(api, alex, question)
    assert data["source"] == "llm"
    assert await usage_rows(sessions) == [("ask", "success")]

    # Over quota: HTTP 200 fallback with suggestions, and no new row.
    data = await ask(api, alex, question)
    assert data["source"] == "fallback" and data["suggestions"] and data["tool"] is None
    assert await usage_rows(sessions) == [("ask", "success")]
    async with sessions() as s:
        assert (await s.execute(select(func.count()).select_from(AIUsageLog))).scalar_one() == 1


# ---------------------------------------------------------------------------
# 5. The ₹700 example
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_assistant_total_is_the_users_share_700_not_800(pg, api):
    w = await seed_demo(pg["sessions"])
    alex, blair, group = w["alex"], w["blair"], w["group"]
    day = date(2026, 11, 20)
    await add_personal(api, alex, 20000, FOOD, day, "Lunch")  # personal ₹200
    await add_shared(api, group, alex, 60000, FOOD, day)  # Alex paid ₹600, share ₹200
    await add_shared(api, group, blair, 90000, FOOD, day)  # Blair paid ₹900, Alex's share ₹300
    await settle(api, group, w["casey"], alex, 10000)  # a settlement never counts
    deleted = await add_personal(api, alex, 55500, FOOD, day, "Deleted")
    assert (await api.delete(f"/api/v1/expenses/{deleted['id']}", headers=bearer(alex))).status_code == 200

    data = await ask(api, alex, "How much have I spent this month?")
    assert data["tool"] == "spend_total"
    assert data["figures"] == [{"label": "Total spending", "amountPaise": 70000}]
    assert "₹700.00" in data["answer"] and "₹800.00" not in data["answer"]
    month = resolve_period(PeriodSlots(date_range="this_month"), TODAY)
    async with pg["sessions"]() as s:
        summary = await analytics_service.get_summary(s, alex, month.start, month.end)
    assert summary.share_paise == 70000 and summary.cash_paid_paise == 80000

    # The same share in every tool that sums spending: by category, compared, listed.
    data = await ask(api, alex, "Show my spending by category this month.")
    assert data["figures"][:2] == [{"label": "Total spending", "amountPaise": 70000},
                                   {"label": "Food & Dining", "amountPaise": 70000}]
    data = await ask(api, alex, "Compare my spending this month with last month.")
    assert data["figures"][0] == {"label": "Spending this month", "amountPaise": 70000}
    data = await ask(api, alex, "List my food expenses this month")
    assert data["figures"][0] == {"label": "Total spending", "amountPaise": 70000}
    assert sorted(f["amountPaise"] for f in data["figures"][1:]) == [20000, 20000, 30000]


# ---------------------------------------------------------------------------
# 6. Suggestions, rows kept from the model, strangers, the T-52 shortcut
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_every_fallback_suggestion_is_answered_through_the_api(pg, api, world):
    for question in fallbacks.SUGGESTIONS:
        data = await ask(api, world["alex"], question)
        assert data["source"] == "template" and data["tool"] in tools.TOOLS, (question, data)
        assert data["figures"] or data["counts"], question


@pytest.mark.anyio
async def test_list_expenses_rows_never_reach_the_model(pg, api, world, monkeypatch):
    stub = StubLLM(selection=expected_choice)
    monkeypatch.setattr(assistant_service, "get_llm_client", lambda: stub)
    data = await ask(api, world["alex"], "Show my Swiggy orders")
    assert data["tool"] == "list_expenses" and data["source"] == "template"
    assert "Lunch order" in data["answer"] and "Swiggy dinner" in data["answer"]
    assert "Late night order" not in data["answer"]  # deleted
    assert stub.wording_calls == []
    assert "Lunch order" not in json.dumps(stub.selection_calls)


@pytest.mark.anyio
async def test_a_stranger_sees_only_their_own_figures(pg, api, world):
    sam = world["sam"]
    resp = await api.post(ASK, json={"question": "Show my 5 most recent expenses."}, headers=bearer(sam))
    data = resp.json()["data"]
    assert data["figures"] == [{"label": "Total spending", "amountPaise": 777777},
                               {"label": "22 Nov 2026 Dinner", "amountPaise": 777777}]
    for question in ("How am I doing on my budgets?", "What's coming up in the next 31 days?",
                     "How much do I owe in the Flat Expenses group?"):
        resp = await api.post(ASK, json={"question": question}, headers=bearer(sam))
        body = resp.text
        assert resp.status_code == 200
        assert "Netflix" not in body and "7,000.00" not in body and "1,566.66" not in body, (question, body)
    assert "couldn't find a group called 'Flat Expenses'" in body


@pytest.mark.anyio
async def test_t52_total_spending_uses_the_two_year_cap(pg, api, world, monkeypatch):
    monkeypatch.setattr("app.api.v1.endpoints.analytics_tools.today_in_kolkata", lambda: TODAY)
    resp = await api.get("/api/v1/analytics-tools/total-spending", headers=bearer(world["alex"]))
    assert resp.status_code == 200, resp.text  # never 400 RANGE_TOO_LARGE
    body = resp.json()
    assert (body["from_date"], body["to_date"]) == ("2024-11-24", "2026-11-24")  # 731 days, inclusive
    assert body["share_paise"] == 15291334  # every expense of Alex's in the last two years
