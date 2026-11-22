"""Comprehensive 60-Question Evaluation Test Suite (T-57 / US-24).

Targets:
1. At least 90% correct answers across 60 evaluation test questions.
2. ZERO invented numerical values (strict Grounding Guard enforcement).
3. Covers all eight query tools, multiple date boundaries, merchants, categories, and fallbacks.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from app.ai.assistant_service import ask_assistant
from app.ai.date_resolver import DateResolver
from app.ai.grounding import GroundingGuard
from app.models.category import Category
from app.models.expense import Expense
from app.models.user import User
from tests.test_assistant_tools import MockSession

# -----------------------------------------------------------------------------
# 60 Real-world Evaluation Questions Dataset
# -----------------------------------------------------------------------------
EVAL_QUESTIONS: list[dict[str, Any]] = [
    # 1-12: Category spending queries
    {"id": 1, "question": "How much did I spend on food last week?", "expected_tool": "get_spending_by_category", "expected_category": "Food & Dining"},
    {"id": 2, "question": "What was my spending on groceries this month?", "expected_tool": "get_spending_by_category", "expected_category": "Groceries"},
    {"id": 3, "question": "How much did I spend on transportation?", "expected_tool": "get_spending_by_category", "expected_category": "Travel & Transport"},
    {"id": 4, "question": "Show my bills and utilities expenses for last month.", "expected_tool": "get_spending_by_category", "expected_category": "Bills & Utilities"},
    {"id": 5, "question": "How much was spent on shopping today?", "expected_tool": "get_spending_by_category", "expected_category": "Shopping"},
    {"id": 6, "question": "How much did I spend on entertainment this week?", "expected_tool": "get_spending_by_category", "expected_category": "Entertainment"},
    {"id": 7, "question": "What were my health expenses this year?", "expected_tool": "get_spending_by_category", "expected_category": "Health"},
    {"id": 8, "question": "How much did I spend on dining yesterday?", "expected_tool": "get_spending_by_category", "expected_category": "Food & Dining"},
    {"id": 9, "question": "How much did I spend on education?", "expected_tool": "get_spending_by_category", "expected_category": "Education"},
    {"id": 10, "question": "Tell me my personal care spending this month.", "expected_tool": "get_spending_by_category", "expected_category": "Personal Care"},
    {"id": 11, "question": "How much did I spend on rent and housing?", "expected_tool": "get_spending_by_category", "expected_category": "Rent & Housing"},
    {"id": 12, "question": "What did I spend on gifts and donations?", "expected_tool": "get_spending_by_category", "expected_category": "Gifts & Donations"},

    # 13-20: Total spending across periods
    {"id": 13, "question": "What was my total spending this month?", "expected_tool": "get_total_spending"},
    {"id": 14, "question": "What did I spend yesterday?", "expected_tool": "get_total_spending"},
    {"id": 15, "question": "How much did I spend this week?", "expected_tool": "get_total_spending"},
    {"id": 16, "question": "What is my total expense this year?", "expected_tool": "get_total_spending"},
    {"id": 17, "question": "How much have I spent in total?", "expected_tool": "get_total_spending"},
    {"id": 18, "question": "Total expenses last week.", "expected_tool": "get_total_spending"},
    {"id": 19, "question": "What was my total spending last month?", "expected_tool": "get_total_spending"},
    {"id": 20, "question": "How much did I spend today?", "expected_tool": "get_total_spending"},

    # 21-27: Recent expenses listing
    {"id": 21, "question": "Show my expenses from yesterday.", "expected_tool": "get_recent_expenses"},
    {"id": 22, "question": "List my recent expenses.", "expected_tool": "get_recent_expenses"},
    {"id": 23, "question": "What were my latest transactions?", "expected_tool": "get_recent_expenses"},
    {"id": 24, "question": "Show my recent food expenses.", "expected_tool": "get_recent_expenses"},
    {"id": 25, "question": "List my expenses for this week.", "expected_tool": "get_recent_expenses"},
    {"id": 26, "question": "Show my expenses from last week.", "expected_tool": "get_recent_expenses"},
    {"id": 27, "question": "Show my recent purchases.", "expected_tool": "get_recent_expenses"},

    # 28-34: Highest single expense
    {"id": 28, "question": "What was my highest expense?", "expected_tool": "get_highest_expense"},
    {"id": 29, "question": "What is my biggest transaction this month?", "expected_tool": "get_highest_expense"},
    {"id": 30, "question": "Show my largest purchase.", "expected_tool": "get_highest_expense"},
    {"id": 31, "question": "What was my highest expense last week?", "expected_tool": "get_highest_expense"},
    {"id": 32, "question": "What was my most expensive food purchase?", "expected_tool": "get_highest_expense"},
    {"id": 33, "question": "Show my biggest expense on shopping.", "expected_tool": "get_highest_expense"},
    {"id": 34, "question": "What was my maximum expense this year?", "expected_tool": "get_highest_expense"},

    # 35-42: Spending by merchant
    {"id": 35, "question": "How much did I spend at Starbucks?", "expected_tool": "get_spending_by_merchant", "expected_merchant": "Starbucks"},
    {"id": 36, "question": "What was my total spend at Amazon?", "expected_tool": "get_spending_by_merchant", "expected_merchant": "Amazon"},
    {"id": 37, "question": "How much did I spend on Uber?", "expected_tool": "get_spending_by_merchant", "expected_merchant": "Uber"},
    {"id": 38, "question": "Show my spending at Swiggy this month.", "expected_tool": "get_spending_by_merchant", "expected_merchant": "Swiggy"},
    {"id": 39, "question": "How much did I spend at Zomato?", "expected_tool": "get_spending_by_merchant", "expected_merchant": "Zomato"},
    {"id": 40, "question": "What did I spend at Blinkit?", "expected_tool": "get_spending_by_merchant", "expected_merchant": "Blinkit"},
    {"id": 41, "question": "How much did I spend at McDonald's?", "expected_tool": "get_spending_by_merchant", "expected_merchant": "Mcdonald's"},
    {"id": 42, "question": "What was my spending at Flipkart?", "expected_tool": "get_spending_by_merchant", "expected_merchant": "Flipkart"},

    # 43-48: Category breakdown
    {"id": 43, "question": "Show my category breakdown this month.", "expected_tool": "get_category_breakdown"},
    {"id": 44, "question": "What categories did I spend on last week?", "expected_tool": "get_category_breakdown"},
    {"id": 45, "question": "Show my category wise spending.", "expected_tool": "get_category_breakdown"},
    {"id": 46, "question": "Where did I spend the most money this month?", "expected_tool": "get_category_breakdown"},
    {"id": 47, "question": "Show spending breakdown for last month.", "expected_tool": "get_category_breakdown"},
    {"id": 48, "question": "Breakdown of my expenses this week.", "expected_tool": "get_category_breakdown"},

    # 49-54: Daily average spending
    {"id": 49, "question": "What's my average daily spending this month?", "expected_tool": "get_daily_average_spending"},
    {"id": 50, "question": "Average expense per day last week.", "expected_tool": "get_daily_average_spending"},
    {"id": 51, "question": "What is my daily spending average this week?", "expected_tool": "get_daily_average_spending"},
    {"id": 52, "question": "What was my average daily spend last month?", "expected_tool": "get_daily_average_spending"},
    {"id": 53, "question": "What is my daily spending average this year?", "expected_tool": "get_daily_average_spending"},
    {"id": 54, "question": "How much do I spend on average per day this month?", "expected_tool": "get_daily_average_spending"},

    # 55-58: Transaction count
    {"id": 55, "question": "How many expenses did I record this week?", "expected_tool": "get_expenses_count"},
    {"id": 56, "question": "What is the total number of transactions last month?", "expected_tool": "get_expenses_count"},
    {"id": 57, "question": "How many times did I buy groceries?", "expected_tool": "get_expenses_count"},
    {"id": 58, "question": "How many purchases did I make yesterday?", "expected_tool": "get_expenses_count"},

    # 59-60: Unsupported questions (verifying fallback suggestions)
    {"id": 59, "question": "What is the weather in Delhi today?", "expected_tool": None},
    {"id": 60, "question": "Transfer 500 rupees to John.", "expected_tool": None},
]


@pytest.fixture
def eval_dataset():
    """Populate realistic database records for a benchmark user."""
    user = User(
        id=uuid.uuid4(),
        email="eval_user@example.com",
        name="Eval User",
        hashed_password="pw",
        is_active=True,
    )

    today = DateResolver.get_current_ist_date()
    yesterday = today - timedelta(days=1)
    last_week_day = today - timedelta(days=8)
    last_month_day = (today.replace(day=1) - timedelta(days=15))

    cat_names = [
        "Bills & Utilities", "Education", "Entertainment", "Food & Dining",
        "Gifts & Donations", "Groceries", "Health", "Other",
        "Personal Care", "Rent & Housing", "Shopping", "Travel & Transport",
    ]
    categories = [
        Category(id=uuid.uuid4(), name=name, is_default=True)
        for name in cat_names
    ]
    cat_map = {c.name: c for c in categories}

    now = datetime.now(UTC)

    # Seed varied expenses
    expenses = [
        # Today
        Expense(id=uuid.uuid4(), user_id=user.id, category_id=cat_map["Food & Dining"].id, amount_minor=35000, description="Cafe lunch", merchant="Starbucks", expense_date=today, created_at=now),
        Expense(id=uuid.uuid4(), user_id=user.id, category_id=cat_map["Shopping"].id, amount_minor=120000, description="T-shirt", merchant="Amazon", expense_date=today, created_at=now),
        # Yesterday
        Expense(id=uuid.uuid4(), user_id=user.id, category_id=cat_map["Food & Dining"].id, amount_minor=45000, description="Burger dinner", merchant="McDonald's", expense_date=yesterday, created_at=now),
        Expense(id=uuid.uuid4(), user_id=user.id, category_id=cat_map["Travel & Transport"].id, amount_minor=28000, description="Cab ride", merchant="Uber", expense_date=yesterday, created_at=now),
        # Last week
        Expense(id=uuid.uuid4(), user_id=user.id, category_id=cat_map["Groceries"].id, amount_minor=95000, description="Weekly fruits & vegetables", merchant="Blinkit", expense_date=last_week_day, created_at=now),
        Expense(id=uuid.uuid4(), user_id=user.id, category_id=cat_map["Food & Dining"].id, amount_minor=65000, description="Biryani", merchant="Swiggy", expense_date=last_week_day, created_at=now),
        Expense(id=uuid.uuid4(), user_id=user.id, category_id=cat_map["Entertainment"].id, amount_minor=50000, description="Movie tickets", merchant="PVR", expense_date=last_week_day, created_at=now),
        # Last month
        Expense(id=uuid.uuid4(), user_id=user.id, category_id=cat_map["Bills & Utilities"].id, amount_minor=220000, description="Electricity bill", merchant="Adani Power", expense_date=last_month_day, created_at=now),
        Expense(id=uuid.uuid4(), user_id=user.id, category_id=cat_map["Health"].id, amount_minor=85000, description="Vitamins", merchant="Apollo Pharmacy", expense_date=last_month_day, created_at=now),
        Expense(id=uuid.uuid4(), user_id=user.id, category_id=cat_map["Rent & Housing"].id, amount_minor=1500000, description="Monthly flat rent", merchant="Landlord", expense_date=last_month_day, created_at=now),
        Expense(id=uuid.uuid4(), user_id=user.id, category_id=cat_map["Education"].id, amount_minor=300000, description="Python course", merchant="Coursera", expense_date=last_month_day, created_at=now),
        Expense(id=uuid.uuid4(), user_id=user.id, category_id=cat_map["Personal Care"].id, amount_minor=60000, description="Haircut & Spa", merchant="Enrich", expense_date=last_month_day, created_at=now),
        Expense(id=uuid.uuid4(), user_id=user.id, category_id=cat_map["Gifts & Donations"].id, amount_minor=100000, description="Birthday gift", merchant="Ferns N Petals", expense_date=last_month_day, created_at=now),
    ]

    session = MockSession(expenses, categories, users=[user])
    return {"user": user, "session": session}


@pytest.mark.anyio
async def test_60_questions_benchmark_evaluation(eval_dataset):
    """Run the 60-question evaluation suite.

    Requirements:
    1. At least 90% correct tool selection and answering (>= 54/60).
    2. ZERO invented numerical values (0 grounding violations).
    """
    user = eval_dataset["user"]
    session = eval_dataset["session"]

    total_questions = len(EVAL_QUESTIONS)
    assert total_questions == 60, f"Evaluation suite must contain exactly 60 questions, found {total_questions}"

    correct_count = 0
    grounding_violations_count = 0
    evaluation_results = []

    for item in EVAL_QUESTIONS:
        q_id = item["id"]
        question = item["question"]
        expected_tool = item["expected_tool"]

        res = await ask_assistant(
            db=session,
            user_id=user.id,
            question=question,
        )

        tool_matched = (res.tool_used == expected_tool)
        is_grounded = res.grounded

        # Check for any invented numbers in final answer
        if res.tool_result:
            allowed = GroundingGuard.collect_allowed_numbers(res.tool_result)
            extracted = GroundingGuard.extract_numbers_from_text(res.answer)
            invented = [n for n in extracted if not any(abs(n - a) < 0.01 for a in allowed)]
            if invented:
                grounding_violations_count += 1
                is_grounded = False

        # In unsupported questions, verify fallback suggestions are provided
        if expected_tool is None:
            has_fallback = len(res.fallback_suggestions) > 0 and res.tool_used is None
            if has_fallback:
                correct_count += 1
            evaluation_results.append({
                "id": q_id,
                "question": question,
                "tool_used": res.tool_used,
                "expected_tool": None,
                "success": has_fallback,
                "answer": res.answer,
            })
        else:
            success = tool_matched and is_grounded
            if success:
                correct_count += 1
            else:
                print(f"Failed item {q_id}: {question} -> tool_used={res.tool_used}, expected={expected_tool}")
            evaluation_results.append({
                "id": q_id,
                "question": question,
                "tool_used": res.tool_used,
                "expected_tool": expected_tool,
                "success": success,
                "answer": res.answer,
            })

    accuracy_pct = (correct_count / total_questions) * 100.0
    print(f"\n=======================================================")
    print(f"60-QUESTION EVALUATION RESULTS:")
    print(f"Total Questions Evaluated: {total_questions}")
    print(f"Correct Answers: {correct_count} / {total_questions} ({accuracy_pct:.1f}%)")
    print(f"Grounding Violations Detected: {grounding_violations_count}")
    print(f"Target Accuracy: >= 90.0% | Achieved: {accuracy_pct:.1f}%")
    print(f"Target Invented Values: 0 | Achieved: {grounding_violations_count}")
    print(f"=======================================================\n")

    # STRICT ASSERTIONS
    assert grounding_violations_count == 0, f"Found {grounding_violations_count} grounding violations! ZERO permitted."
    assert accuracy_pct >= 90.0, f"Accuracy {accuracy_pct:.1f}% below required 90.0% threshold ({correct_count}/60 correct)."
