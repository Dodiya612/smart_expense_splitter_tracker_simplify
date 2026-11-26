"""Fallback suggestions and safe error responses (T-57 / US-24).

Implements deterministic fallback recommendations for:
- AI functionality disabled.
- LLM service unavailable or failing.
- Questions that cannot be mapped to an allowed tool.
- Insufficient tool information.
- Query security or grounding guard violations.
"""

from __future__ import annotations

from typing import Any

from app.schemas.assistant import AskResponseData

# Core predefined suggestions per requirements
DEFAULT_FALLBACK_SUGGESTIONS: list[str] = [
    "How much did I spend this week?",
    "Show my food expenses.",
    "What were my expenses yesterday?",
    "Show my monthly spending.",
]

CONTEXTUAL_FALLBACK_SUGGESTIONS: dict[str, list[str]] = {
    "food": [
        "How much did I spend on food this month?",
        "Show my food expenses from last week.",
        "What were my expenses yesterday?",
    ],
    "shopping": [
        "How much did I spend on shopping this month?",
        "What was my largest shopping expense?",
        "Show my recent expenses.",
    ],
    "travel": [
        "How much did I spend on transportation this month?",
        "Show my travel expenses for last week.",
        "What was my total spending this month?",
    ],
}


def get_fallback_suggestions(hint: str | None = None) -> list[str]:
    """Retrieve fallback suggestions, optionally contextualized by query hint."""
    if hint:
        norm = hint.lower()
        for key, suggestions in CONTEXTUAL_FALLBACK_SUGGESTIONS.items():
            if key in norm:
                return suggestions
    return list(DEFAULT_FALLBACK_SUGGESTIONS)


def create_ai_disabled_response() -> AskResponseData:
    """Return fallback response when AI is globally disabled."""
    return AskResponseData(
        answer=(
            "The AI assistant is currently disabled. You can track and view your expenses "
            "directly or use one of the standard queries below."
        ),
        tool_used=None,
        tool_parameters=None,
        tool_result=None,
        grounded=True,
        fallback_suggestions=get_fallback_suggestions(),
    )


def create_llm_unavailable_response(reason: str = "service temporarily unavailable") -> AskResponseData:
    """Return fallback response when the LLM service is unconfigured or unreachable."""
    return AskResponseData(
        answer=(
            "I'm unable to process your request right now because the AI service is "
            "temporarily unavailable. Please try one of these standard queries:"
        ),
        tool_used=None,
        tool_parameters=None,
        tool_result=None,
        grounded=True,
        fallback_suggestions=get_fallback_suggestions(),
    )


def create_unsupported_question_response(question: str) -> AskResponseData:
    """Return fallback response when a question cannot be mapped to any of the eight query tools."""
    return AskResponseData(
        answer=(
            "I can only help with questions about your recorded expenses, spending by category, "
            "recent transactions, merchants, and date ranges. Here are some questions you can ask:"
        ),
        tool_used=None,
        tool_parameters=None,
        tool_result=None,
        grounded=True,
        fallback_suggestions=get_fallback_suggestions(question),
    )


def create_execution_error_response(error_message: str | None = None) -> AskResponseData:
    """Return fallback response when tool execution encounters an error."""
    return AskResponseData(
        answer="I encountered an issue retrieving your expense records. Please try asking again or select one of these queries:",
        tool_used=None,
        tool_parameters=None,
        tool_result=None,
        grounded=True,
        fallback_suggestions=get_fallback_suggestions(),
    )
