#!/usr/bin/env python3
"""Evaluation runner for the expense assistant (T-57 / US-24).

Measures the language model's tool selection on the frozen 60 questions in
evals/assistant/questions.json, and checks that no invented number reaches an
answer.

For every question:
1. The model picks a tool and slots (GroqClient.select_tool_call). The choice is
   validated exactly as in production (app/ai/assistant_service.py) and counts as
   correct when the tool and the slots match the question (so the period, which
   code resolves from the slots, matches too).
   For questions no tool can answer, the correct choice is "no tool".
2. For answerable questions the tool runs on fixed sample figures for every
   service (no database) and the model words the answer (GroqClient.write_answer;
   list_expenses is never worded by the model). The answer shown to
   the user is the model's wording if the grounding guard accepts it, otherwise
   the template. An invented number is any number in that final answer that the
   tool did not return; the target is zero.

Usage (from backend/, with the backend virtual environment):

    GROQ_API_KEY=... PYTHONPATH=.. .venv/bin/python ../evals/assistant/run_eval.py
    PYTHONPATH=.. .venv/bin/python ../evals/assistant/run_eval.py --stub   # offline check

Exit code 0 when accuracy >= 90% and no invented number reached an answer, else 1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from app.ai import tools as assistant_tools  # noqa: E402
from app.ai.assistant_service import choose_from_model, word_answer  # noqa: E402
from app.ai.grounding import find_violations  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.analytics import (  # noqa: E402
    AnalyticsCategoriesResponse,
    AnalyticsSummaryResponse,
    CategoryBreakdownItem,
)
from app.schemas.budget import BudgetResponse  # noqa: E402
from app.schemas.group import GroupListItemResponse  # noqa: E402
from app.schemas.recurring import RecurringRuleResponse  # noqa: E402
from app.services import analytics_service, budget_service, group_service, recurring_service  # noqa: E402
from app.services.groq_client import GroqClient  # noqa: E402

QUESTIONS_FILE = PROJECT_ROOT / "evals" / "assistant" / "questions.json"
ACCURACY_TARGET = 90.0
FOOD_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 11, 1, tzinfo=UTC)


class SampleServices:
    """Fixed sample figures for every service the tools read, so the wording check needs no database."""

    async def get_summary(self, db: Any, user: Any, from_date: date | None = None, to_date: date | None = None,
                          group_id: Any = None) -> AnalyticsSummaryResponse:
        start, end = from_date or date(2026, 11, 1), to_date or date(2026, 11, 24)
        return AnalyticsSummaryResponse(from_date=start, to_date=end, share_paise=245050, cash_paid_paise=300000,
                                        expense_count=7, owed_to_you_paise=120000, you_owe_paise=35000)

    async def get_categories(self, db: Any, user: Any, from_date: date | None = None,
                             to_date: date | None = None, group_id: Any = None) -> AnalyticsCategoriesResponse:
        items = [
            CategoryBreakdownItem(category_id=uuid.uuid4(), category_name=name, share_paise=share,
                                  cash_paid_paise=share, expense_count=count)
            for name, share, count in (("Food & Dining", 120000, 4), ("Groceries", 80050, 2), ("Health", 45000, 1))
        ]
        return AnalyticsCategoriesResponse(from_date=from_date or date(2026, 11, 1), to_date=to_date or date(2026, 11, 24),
                                           categories=items, total_share_paise=245050, total_cash_paid_paise=245050)

    async def get_merchants(self, db: Any, user: Any, from_date: date | None = None,
                            to_date: date | None = None) -> list[analytics_service.MerchantTotal]:
        return [analytics_service.MerchantTotal("Swiggy", 90000, 3), analytics_service.MerchantTotal("Uber", 42000, 2)]

    async def get_expense_rows(self, db: Any, user: Any, from_date: date | None = None, to_date: date | None = None,
                               **filters: Any) -> analytics_service.ExpenseShareRows:
        rows = [
            analytics_service.ExpenseShareRow(date(2026, 11, 20), "Dinner", "Swiggy", "Food & Dining", 45000),
            analytics_service.ExpenseShareRow(date(2026, 11, 18), "Cab", "Uber", "Travel & Transport", 21000),
        ]
        return analytics_service.ExpenseShareRows(from_date or date(2026, 11, 1), to_date or date(2026, 11, 24),
                                                  rows[: filters.get("limit", 10)], 2, 66000)

    async def list_budgets(self, db: Any, user: Any, limit: int, offset: int) -> tuple[list[BudgetResponse], int]:
        def one(category_id: uuid.UUID | None, limit_paise: int, spent: int) -> BudgetResponse:
            progress = budget_service.build_progress(spent, limit_paise, date(2026, 11, 1), date(2026, 11, 30))
            return BudgetResponse(id=uuid.uuid4(), period="monthly", category_id=category_id, limit_paise=limit_paise,
                                  created_at=NOW, updated_at=NOW, progress=progress)
        budgets = [one(None, 500000, 245050), one(FOOD_ID, 100000, 120000)]
        return budgets, len(budgets)

    async def category_names(self, db: Any, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        return {i: "Food & Dining" for i in ids if i == FOOD_ID}

    async def list_rules(self, db: Any, owner: Any, rule_status: str | None, limit: int,
                         offset: int) -> tuple[list[RecurringRuleResponse], int]:
        rule = RecurringRuleResponse(
            id=uuid.uuid4(), frequency="monthly", start_date=date(2026, 1, 28), next_run_date=date(2026, 11, 28),
            status="active", amount_paise=64900, category_id=FOOD_ID, description="Netflix", created_at=NOW,
            updated_at=NOW,
        )
        return [rule], 1

    async def list_user_groups(self, db: Any, user: Any) -> list[GroupListItemResponse]:
        return [GroupListItemResponse(id=uuid.uuid4(), name="Flat Expenses", type="flat", created_by=uuid.uuid4(),
                                      created_at=NOW, member_count=3, current_user_role="member")]

    def install(self) -> None:
        analytics_service.get_summary = self.get_summary  # type: ignore[method-assign]
        analytics_service.get_categories = self.get_categories  # type: ignore[method-assign]
        analytics_service.get_merchants = self.get_merchants  # type: ignore[method-assign]
        analytics_service.get_expense_rows = self.get_expense_rows  # type: ignore[method-assign]
        budget_service.list_budgets = self.list_budgets  # type: ignore[method-assign]
        recurring_service.list_rules = self.list_rules  # type: ignore[method-assign]
        group_service.list_user_groups = self.list_user_groups  # type: ignore[method-assign]
        assistant_tools.category_names = self.category_names  # type: ignore[method-assign]


class StubClient:
    """Answers like a perfect model; only for checking the runner offline."""

    def __init__(self, questions: list[dict[str, Any]]) -> None:
        self._expected = {q["question"]: q for q in questions}

    def is_configured(self) -> bool:
        return True

    async def select_tool_call(self, question: str, tool_definitions: list[dict[str, Any]]) -> dict[str, Any]:
        q = self._expected[question]
        return {"tool": q["expected_tool"], "slots": q["expected_slots"]}

    async def write_answer(self, question: str, tool_name: str, facts: dict[str, str]) -> str:
        return "Here is what I found: " + ", ".join("{" + name + "}" for name in facts) + "."


def _choice_matches(choice: Any, item: dict[str, Any]) -> bool:
    expected_tool = item["expected_tool"]
    if expected_tool is None:
        return choice.fallback is not None
    if choice.fallback is not None or choice.tool != expected_tool:
        return False
    spec = assistant_tools.TOOLS[expected_tool]
    expected = spec.slots.model_validate(item["expected_slots"])
    return choice.slots.model_dump() == expected.model_dump()


async def run(client: Any, delay: float) -> int:
    doc = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    today = date.fromisoformat(doc["reference_date"])
    questions = doc["questions"]
    SampleServices().install()
    user = User(id=uuid.uuid4(), email="eval@example.com", name="Eval", hashed_password="x", is_active=True)

    correct = 0
    invented = 0
    rejected_wordings = 0
    for item in questions:
        selection = await client.select_tool_call(item["question"], assistant_tools.tool_definitions())
        choice = choose_from_model(selection) if selection is not None else None
        ok = choice is not None and _choice_matches(choice, item)
        correct += ok
        note = "ok" if ok else f"MISS (model chose {selection!r})"

        if ok and choice.tool is not None:
            try:
                result = await assistant_tools.TOOLS[choice.tool].run(None, user, choice.slots, today)  # type: ignore[arg-type]
            except assistant_tools.TOOL_INPUT_ERRORS:
                print(f"[{item['id']:2d}] {note:12s} {item['question']}  (answered with a fallback)")
                continue
            response = await word_answer(item["question"], result, client)
            if response.source == "template" and result.model_wording:
                rejected_wordings += 1
            leaked = find_violations(response.answer, result.allowed())
            if leaked:
                invented += 1
                note += f" INVENTED {leaked}"
        print(f"[{item['id']:2d}] {note:12s} {item['question']}")
        if delay:
            await asyncio.sleep(delay)

    accuracy = 100.0 * correct / len(questions)
    print()
    print(f"Tool selection: {correct}/{len(questions)} correct ({accuracy:.1f}%), target >= {ACCURACY_TARGET:.0f}%")
    print(f"Model wordings replaced by the template: {rejected_wordings}")
    print(f"Invented numbers in answers: {invented} (target 0)")
    return 0 if accuracy >= ACCURACY_TARGET and invented == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the expense assistant on the frozen 60 questions.")
    parser.add_argument("--stub", action="store_true", help="Use a stub model instead of Groq (offline check).")
    parser.add_argument("--timeout", type=float, default=10.0, help="Seconds per Groq call (default 10).")
    parser.add_argument("--delay", type=float, default=2.5,
                        help="Seconds between questions, to stay under Groq rate limits (default 2.5).")
    args = parser.parse_args()

    if args.stub:
        questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]
        return asyncio.run(run(StubClient(questions), delay=0.0))
    client = GroqClient(api_key=os.getenv("GROQ_API_KEY"), timeout=args.timeout)
    if not client.is_configured():
        print("GROQ_API_KEY is not set. Set it, or run with --stub for an offline check.")
        return 2
    return asyncio.run(run(client, delay=args.delay))


if __name__ == "__main__":
    sys.exit(main())
