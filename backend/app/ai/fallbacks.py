"""Fallback answers and suggested questions for the expense assistant (T-57 / US-24).

A fallback is returned when the assistant cannot answer: AI switched off, the
daily quota used up, a question no tool can answer, a period it cannot work out,
or a tool choice from the model that fails validation. Fallbacks contain no
figures. Every suggestion is a question the assistant answers without a language
model (tests/test_assistant_fallbacks.py runs each one end to end).
"""

from __future__ import annotations

from app.schemas.assistant import AskResponseData

SUGGESTIONS: tuple[str, ...] = (
    "How much did I spend this week?",
    "Show my spending by category this month.",
    "Compare my spending this month with last month.",
    "Who are my top merchants this month?",
    "How am I doing on my budgets?",
    "How much do I owe across my groups?",
    "What recurring expenses are due in the next 7 days?",
    "Show my 5 most recent expenses.",
)


def fallback(answer: str) -> AskResponseData:
    return AskResponseData(answer=answer, source="fallback", suggestions=list(SUGGESTIONS))


def ai_disabled() -> AskResponseData:
    return fallback(
        "The assistant is switched off right now. You can still see your spending on the dashboard."
    )


def quota_used_up() -> AskResponseData:
    return fallback(
        "You have used today's assistant questions. They reset tomorrow; until then the dashboard "
        "shows your spending."
    )


def unsupported() -> AskResponseData:
    return fallback(
        "I can answer questions about your own spending: totals, categories, comparisons, "
        "merchants, budgets, group balances, upcoming recurring expenses and your recent "
        "expenses. Try one of these:"
    )


def unsupported_scope() -> AskResponseData:
    return fallback("I can only answer questions about your own expenses. Try one of these:")


def with_reason(reason: str) -> AskResponseData:
    return fallback(f"{reason} Try one of these:")


def not_understood() -> AskResponseData:
    return fallback("I couldn't work out how to answer that. Try one of these:")
