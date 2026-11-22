"""Unit tests for Grounding Guard and safe template generation (T-57 / US-24)."""

import pytest

from app.ai.grounding import GroundingGuard


def test_collect_allowed_numbers():
    """Verify numbers in tool results (paise, rupees, counts, dates) are recognized."""
    tool_result = {
        "tool": "get_total_spending",
        "total_paise": 245000,
        "total_rupees": 2450.0,
        "transaction_count": 4,
        "start_date": "2026-11-16",
        "end_date": "2026-11-22",
    }
    allowed = GroundingGuard.collect_allowed_numbers(tool_result)

    assert 245000.0 in allowed
    assert 2450.0 in allowed
    assert 4.0 in allowed
    assert 2026.0 in allowed
    assert 11.0 in allowed
    assert 16.0 in allowed
    assert 22.0 in allowed
    assert 0.0 in allowed


def test_grounded_answer_passes():
    """Candidate answer containing only supported figures passes validation."""
    tool_result = {
        "tool": "get_spending_by_category",
        "category": "Food & Dining",
        "total_paise": 245000,
        "total_rupees": 2450.0,
        "transaction_count": 4,
        "period_label": "last week",
    }
    candidate = "You spent ₹2,450.00 on Food & Dining across 4 transactions for last week."

    res = GroundingGuard.validate_and_guard(candidate, tool_result)
    assert res.is_grounded is True
    assert res.violations == []
    assert res.final_answer == candidate


def test_hallucinated_amount_rejected():
    """Candidate answer with invented expense amount is rejected and replaced."""
    tool_result = {
        "tool": "get_spending_by_category",
        "category": "Food & Dining",
        "total_paise": 245000,
        "total_rupees": 2450.0,
        "transaction_count": 4,
        "period_label": "last week",
    }
    # LLM hallucinates ₹5,000.00
    candidate = "You spent ₹5,000.00 on Food & Dining across 4 transactions."

    res = GroundingGuard.validate_and_guard(candidate, tool_result)
    assert res.is_grounded is False
    assert 5000.0 in res.violations
    assert "₹5,000.00" not in res.final_answer
    assert "₹2450.00" in res.final_answer or "₹2,450.00" in res.final_answer
    assert "Food & Dining" in res.final_answer


def test_hallucinated_count_rejected():
    """Candidate answer with invented transaction count is rejected."""
    tool_result = {
        "tool": "get_total_spending",
        "total_paise": 150000,
        "total_rupees": 1500.0,
        "transaction_count": 2,
        "period_label": "this month",
    }
    # LLM hallucinates 10 transactions
    candidate = "Your total spending this month is ₹1,500.00 across 10 transactions."

    res = GroundingGuard.validate_and_guard(candidate, tool_result)
    assert res.is_grounded is False
    assert 10.0 in res.violations
    assert "10" not in res.final_answer
    assert "2 transactions" in res.final_answer


def test_hallucinated_percentage_rejected():
    """Candidate answer with invented percentage or comparison statistic is rejected."""
    tool_result = {
        "tool": "get_total_spending",
        "total_paise": 150000,
        "total_rupees": 1500.0,
        "transaction_count": 2,
        "period_label": "this month",
    }
    candidate = "You spent ₹1,500.00 across 2 transactions, which is 25% lower than normal."

    res = GroundingGuard.validate_and_guard(candidate, tool_result)
    assert res.is_grounded is False
    assert 25.0 in res.violations
    assert "25%" not in res.final_answer


def test_safe_template_contains_zero_invented_numbers():
    """Verify that template replacement contains only numbers from the tool result."""
    tool_result = {
        "tool": "get_spending_by_category",
        "category": "Travel & Transport",
        "total_paise": 78000,
        "total_rupees": 780.0,
        "transaction_count": 3,
        "period_label": "this week",
    }
    template = GroundingGuard.build_safe_template(tool_result)

    # Re-extract numbers from the template and ensure all are allowed
    allowed = GroundingGuard.collect_allowed_numbers(tool_result)
    template_numbers = GroundingGuard.extract_numbers_from_text(template)

    for num in template_numbers:
        assert any(abs(num - a) < 0.01 for a in allowed)


def test_empty_results_template():
    """Verify safe template when transaction count and total spending are zero."""
    tool_result = {
        "tool": "get_spending_by_category",
        "category": "Entertainment",
        "total_paise": 0,
        "total_rupees": 0.0,
        "transaction_count": 0,
        "period_label": "last month",
    }
    template = GroundingGuard.build_safe_template(tool_result)
    assert "no expenses" in template.lower()
    assert "Entertainment" in template


def test_highest_expense_grounding():
    """Verify grounding on get_highest_expense tool."""
    tool_result = {
        "tool": "get_highest_expense",
        "expense": {
            "id": "11111111-1111-4111-8111-111111111111",
            "description": "Flight Ticket",
            "amount_paise": 850000,
            "amount_rupees": 8500.0,
            "date": "2026-11-10",
            "category": "Travel & Transport",
            "merchant": "IndiGo",
        },
        "period_label": "this month",
    }
    candidate_good = "Your highest expense this month was Flight Ticket for ₹8,500.00."
    res1 = GroundingGuard.validate_and_guard(candidate_good, tool_result)
    assert res1.is_grounded is True

    candidate_bad = "Your highest expense this month was Flight Ticket for ₹9,200.00."
    res2 = GroundingGuard.validate_and_guard(candidate_bad, tool_result)
    assert res2.is_grounded is False
    assert 9200.0 in res2.violations
    assert "₹8500.00" in res2.final_answer or "₹8,500.00" in res2.final_answer
