"""Grounding guard (app/ai/grounding.py): placeholders, then a type-aware number check."""

from datetime import date
from decimal import Decimal

import pytest

from app.ai.grounding import (
    AllowedFigures,
    fill_placeholders,
    find_violations,
    format_count,
    format_rupees,
    percentage,
)

ALLOWED = AllowedFigures(
    amounts_paise=frozenset({245000, 12345600, 0}),
    counts=frozenset({40, 7}),
    percentages=frozenset({Decimal("42.9")}),
    dates=frozenset({date(2026, 11, 1), date(2026, 11, 30)}),
)
VALUES = {"total": "₹2,450.00", "expenses": "40 expenses", "period": "this month (1 Nov 2026 – 30 Nov 2026)"}


# ---- formatting ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("paise", "text"),
    [(0, "₹0.00"), (5, "₹0.05"), (99900, "₹999.00"), (100000, "₹1,000.00"), (245050, "₹2,450.50"),
     (12345600, "₹1,23,456.00"), (1234567890, "₹1,23,45,678.90")],
)
def test_rupees_use_indian_grouping_and_two_decimals(paise, text):
    assert format_rupees(paise) == text


def test_counts_and_percentages():
    assert format_count(1, "expense", "expenses") == "1 expense"
    assert format_count(3, "expense", "expenses") == "3 expenses"
    assert percentage(30000, 70000) == Decimal("42.9")
    assert percentage(1, 0) == Decimal("0.0")


# ---- step 1: placeholders -----------------------------------------------------------------


def test_placeholders_are_filled_from_backend_values():
    assert fill_placeholders("You spent {total} {period}.", VALUES) == (
        "You spent ₹2,450.00 this month (1 Nov 2026 – 30 Nov 2026)."
    )


@pytest.mark.parametrize(
    "text",
    [
        None, "", "   ",
        "You spent fifteen hundred rupees {period}.",  # number words
        "You spent two lakh {period}.",
        "You spent ₹२,४५० {period}.",  # Devanagari digits
        "You spent {total} and saved {savings}.",  # unknown placeholder
        "You spent {total {period}.",  # broken braces
        "Nothing to report.",  # no placeholder at all
        "x" * 600 + "{total}",  # too long
    ],
)
def test_model_text_that_cannot_be_checked_is_rejected(text):
    assert fill_placeholders(text, VALUES) is None


# ---- step 2: type-aware backstop ----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "You spent ₹2,450.00 across 40 expenses this month (1 Nov 2026 – 30 Nov 2026).",
        "You spent ₹2450 in total.",
        "You spent Rs. 2,450.00 in November 2026.",
        "You spent 2,450 rupees.",
        "You spent ₹1,23,456.00 overall.",  # Indian grouping of a real figure
        "You spent ₹123,456.00 overall.",  # western grouping of the same figure
        "Food was 42.9% of it.",
        "You recorded 7 expenses, your 7th was the largest.",
        "From 2026-11-01 to 2026-11-30 you spent ₹0.00.",
    ],
)
def test_supported_figures_pass(text):
    assert find_violations(text, ALLOWED) == []


@pytest.mark.parametrize(
    "text",
    [
        "You spent ₹24.50 this month.",  # the total divided by 100
        "You spent ₹2,45,000.00 this month.",  # paise shown as rupees
        "You spent 30% more than last month.",  # made-up percentage
        "You spent ₹25 on coffee.",  # small made-up amount
        "You recorded 41 expenses.",  # extra count
        "You recorded 3 expenses.",  # a count the tool did not return
        "You spent ₹2.45 lakh.",  # shorthand
        "You spent ₹2.4k.",
        "You spent ₹-2,450.00.",  # sign
        "Your balance is -₹2,450.00.",  # sign before the rupee symbol
        "Your balance is - Rs 2,450.00.",
        "You spent ₹2,450.00 on 25 Dec 2026.",  # wrong date
        "You spent ₹2,450.00 on 2026-12-25.",
        "You spent ₹2,450.00 in December 2026.",  # wrong month
        "You spent ₹12,34,56.00 overall.",  # invalid grouping
        "You spent fifteen hundred rupees.",  # number words
        "You spent ₹२,४५०.",  # Devanagari digits
        "You will spend about ₹5,000.00 next month.",
        "You spent ₹2,450.004.",  # fraction of a paisa
    ],
)
def test_unsupported_figures_are_violations(text):
    assert find_violations(text, ALLOWED), text


def test_numbers_inside_code_written_phrases_are_not_counts():
    allowed = AllowedFigures(
        amounts_paise=frozenset({70000}), counts=frozenset({6}), percentages=frozenset(),
        dates=frozenset({date(2026, 11, 18), date(2026, 11, 24)}), phrases=frozenset({"in the last 7 days"}),
    )
    assert find_violations("You spent ₹700.00 across 6 expenses in the last 7 days (18 Nov 2026 – 24 Nov 2026).",
                           allowed) == []
    assert find_violations("You recorded 7 expenses in the last 7 days.", allowed) == ["7"]
