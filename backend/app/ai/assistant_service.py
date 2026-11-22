"""AI Assistant Service Orchestrator (T-57 / US-24).

Implements:
1. LLM Tool Selection across exactly eight predefined query tools.
2. User-level authorization and isolation for all queries.
3. Strict prohibition of SQL generation and arbitrary execution.
4. Deterministic Date Resolution (Asia/Kolkata timezone).
5. Grounding Guard validating all numerical claims in candidate answers.
6. Fallback suggestions for disabled AI, service outages, unsupported queries, and grounding failures.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.date_resolver import DateResolver
from app.ai.fallbacks import (
    DEFAULT_FALLBACK_SUGGESTIONS,
    create_ai_disabled_response,
    create_execution_error_response,
    create_llm_unavailable_response,
    create_unsupported_question_response,
    get_fallback_suggestions,
)
from app.ai.grounding import GroundingGuard
from app.ai.quota import AIQuotaService, get_quota_service, log_ai_usage
from app.ai.tools import (
    ALLOWED_TOOL_NAMES,
    TOOL_DEFINITIONS,
    execute_tool,
)
from app.core.config import settings
from app.schemas.assistant import AskResponseData
from app.services.groq_client import CATEGORY_LOOKUP, GroqClient

logger = logging.getLogger(__name__)

# Patterns that indicate explicit SQL injection or unsupported operations
SQL_INJECTION_PATTERN = re.compile(
    r"\b(select\s+.+\s+from|insert\s+into|drop\s+table|delete\s+from|update\s+.+\s+set|union\s+select|exec\s*\(|--|;)\b",
    re.IGNORECASE,
)

# Known merchants for deterministic rule fallback
COMMON_MERCHANTS = [
    "starbucks",
    "amazon",
    "swiggy",
    "zomato",
    "uber",
    "ola",
    "blinkit",
    "zepto",
    "flipkart",
    "myntra",
    "mcdonald's",
    "mcdonalds",
    "dominos",
    "kfc",
    "netflix",
    "spotify",
    "apple",
    "google",
    "reliance",
    "d-mart",
    "dmart",
]


def rule_based_tool_selector(question: str) -> tuple[str | None, dict[str, Any]]:
    """Deterministic, rule-based semantic parser for tool selection.

    Used when LLM is unavailable or for local deterministic verification.
    """
    clean_q = question.strip()
    norm = clean_q.lower()

    # Reject unsupported questions
    unsupported_indicators = [
        "weather",
        "joke",
        "who is",
        "who are",
        "capital of",
        "president",
        "cricket",
        "football",
        "transfer",
        "pay ",
        "send money",
        "bitcoin",
        "crypto",
        "stock advice",
        "invest in",
        "poem",
        "story",
        "sql",
        "table",
        "database",
    ]
    if any(ind in norm for ind in unsupported_indicators):
        return None, {}

    # Extract date range if present
    resolved_date = DateResolver.resolve_from_text(clean_q)
    date_range_arg = None
    if resolved_date and resolved_date.period_label:
        date_range_arg = resolved_date.period_label.replace(" ", "_")

    # 1. Daily average spending
    if re.search(r"\b(daily\s+(?:spending\s+)?average|average\s+daily|average\s+spend|average\s+expense|per\s+day)\b", norm):
        params: dict[str, Any] = {}
        if date_range_arg:
            params["date_range"] = date_range_arg
        return "get_daily_average_spending", params

    # 2. Count of expenses
    if re.search(r"\b(how\s+many|(?:total\s+)?number\s+of\s+(?:expenses|transactions)|count\s+of|how\s+many\s+times)\b", norm):
        params = {}
        if date_range_arg:
            params["date_range"] = date_range_arg
        # Check if category is mentioned
        for cat_synonym, canonical in CATEGORY_LOOKUP.items():
            if re.search(rf"\b{re.escape(cat_synonym)}\b", norm):
                params["category"] = canonical
                break
        return "get_expenses_count", params

    # 3. Highest / Largest single expense
    if re.search(r"\b(highest|largest|biggest|maximum|most\s+expensive)\b", norm):
        params = {}
        if date_range_arg:
            params["date_range"] = date_range_arg
        for cat_synonym, canonical in CATEGORY_LOOKUP.items():
            if re.search(rf"\b{re.escape(cat_synonym)}\b", norm):
                params["category"] = canonical
                break
        return "get_highest_expense", params

    # 4. Category breakdown
    if re.search(r"\b(breakdown|category\s+wise|by\s+category|top\s+categories|where\s+did\s+i\s+spend|(?:what|which)\s+categories)\b", norm):
        params = {}
        if date_range_arg:
            params["date_range"] = date_range_arg
        return "get_category_breakdown", params

    # 5. Recent expenses listing
    if re.search(r"\b(recent\s+(?:\w+\s+)?(?:expenses|purchases|transactions)|list\s+my\s+expenses|show\s+my\s+(?:\w+\s+)?expenses|show\s+expenses|latest\s+(?:\w+\s+)?(?:expenses|transactions)|what\s+were\s+my\s+(?:expenses|transactions)|recent\s+purchases)\b", norm):
        params = {}
        if date_range_arg:
            params["date_range"] = date_range_arg
        # Check category
        for cat_synonym, canonical in CATEGORY_LOOKUP.items():
            if re.search(rf"\b{re.escape(cat_synonym)}\b", norm):
                params["category"] = canonical
                break
        return "get_recent_expenses", params

    # 6. Spending by merchant
    merchant_match = re.search(r"\b(?:at|on|for)\s+([a-zA-Z0-9'\-]+)\b", clean_q, re.IGNORECASE)
    if merchant_match:
        cand_merchant = merchant_match.group(1).lower()
        if cand_merchant in COMMON_MERCHANTS or any(m in norm for m in COMMON_MERCHANTS):
            matched_m = cand_merchant if cand_merchant in COMMON_MERCHANTS else next(m for m in COMMON_MERCHANTS if m in norm)
            params = {"merchant": matched_m.capitalize()}
            if date_range_arg:
                params["date_range"] = date_range_arg
            return "get_spending_by_merchant", params

    # 7. Spending by category
    for cat_synonym, canonical in CATEGORY_LOOKUP.items():
        if re.search(rf"\b{re.escape(cat_synonym)}\b", norm):
            params = {"category": canonical}
            if date_range_arg:
                params["date_range"] = date_range_arg
            return "get_spending_by_category", params

    # 8. Total spending
    if re.search(r"\b(total\s+spend|total\s+expenses?|total\s+spending|how\s+much\s+did\s+i\s+spend|how\s+much\s+have\s+i\s+spent|what\s+is\s+my\s+total|what\s+did\s+i\s+spend)\b", norm):
        params = {}
        if date_range_arg:
            params["date_range"] = date_range_arg
        return "get_total_spending", params

    return None, {}


async def select_tool_for_question(
    question: str,
    groq_client: GroqClient | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Determine the appropriate query tool using Groq LLM with deterministic rule fallback."""
    clean_q = question.strip()

    # Reject SQL injection or malicious patterns immediately
    if SQL_INJECTION_PATTERN.search(clean_q):
        logger.warning("Rejected malicious or raw SQL query pattern: %s", clean_q)
        return None, {}

    llm = groq_client or GroqClient()

    if llm.is_configured():
        llm_selection = await llm.select_tool_call(clean_q, TOOL_DEFINITIONS)
        if llm_selection:
            tool_name = llm_selection.get("tool_name")
            parameters = llm_selection.get("parameters", {})
            if tool_name in ALLOWED_TOOL_NAMES and isinstance(parameters, dict):
                # Clean parameters to prevent parameter injection
                clean_params = {
                    k: v
                    for k, v in parameters.items()
                    if k not in ("user_id", "sql", "query_sql", "raw_query", "db")
                }
                return tool_name, clean_params
            elif tool_name is None:
                # Explicitly classified as unsupported by LLM
                return None, {}

    # Deterministic fallback parser
    return rule_based_tool_selector(clean_q)


async def ask_assistant(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    groq_client: GroqClient | None = None,
    quota_service: AIQuotaService | None = None,
) -> AskResponseData:
    """Master AI Assistant orchestrator satisfying all T-57 / US-24 requirements."""
    # 1. Check global AI_ENABLED toggle
    if not settings.AI_ENABLED:
        logger.info("AI functionality globally disabled. Returning fallback.")
        return create_ai_disabled_response()

    # 2. Check question safety & reject direct SQL
    clean_q = question.strip()
    if not clean_q or SQL_INJECTION_PATTERN.search(clean_q):
        return create_unsupported_question_response(clean_q)

    # 3. Reserve daily AI quota for 'ask' feature
    qs = quota_service or get_quota_service()
    llm = groq_client or GroqClient()

    async with qs.reserve(user_id=user_id, feature="ask", db=db) as reservation:
        if not reservation.allowed:
            logger.info("AI ask quota exhausted or unavailable for user %s", user_id)
            await log_ai_usage(
                user_id=user_id,
                feature="ask",
                provider="groq",
                model=settings.GROQ_MODEL,
                status="quota_exceeded",
                error_message="Daily quota exceeded; fallback suggestions shown",
                db=db,
            )
            return create_llm_unavailable_response("daily ask quota exceeded")

        # 4. Tool selection (LLM with rule fallback)
        tool_name, parameters = await select_tool_for_question(clean_q, llm)

        if not tool_name or tool_name not in ALLOWED_TOOL_NAMES:
            logger.info("Question could not be mapped to an allowed tool: '%s'", clean_q)
            return create_unsupported_question_response(clean_q)

        # 5. Tool execution scoped to authenticated user
        try:
            tool_result = await execute_tool(
                tool_name=tool_name,
                parameters=parameters,
                user_id=user_id,
                db=db,
            )
        except Exception as exc:
            logger.error("Error executing query tool '%s': %s", tool_name, exc)
            return create_execution_error_response(str(exc))

        # 6. Generate candidate response
        candidate_answer: str | None = None
        if llm.is_configured():
            candidate_answer = await llm.generate_grounded_answer(
                question=clean_q,
                tool_name=tool_name,
                tool_result=tool_result,
            )

        if not candidate_answer:
            candidate_answer = GroundingGuard.build_safe_template(tool_result)

        # 7. Grounding Guard verification
        grounding_result = GroundingGuard.validate_and_guard(
            candidate_answer=candidate_answer,
            tool_result=tool_result,
        )

        final_answer = grounding_result.final_answer
        is_grounded = grounding_result.is_grounded

        # If grounding guard rejected invented numbers, offer fallback suggestions
        suggestions = [] if is_grounded else get_fallback_suggestions(clean_q)

        # 8. Log successful usage
        await log_ai_usage(
            user_id=user_id,
            feature="ask",
            provider="groq",
            model=settings.GROQ_MODEL,
            status="success",
            db=db,
        )

        return AskResponseData(
            answer=final_answer,
            tool_used=tool_name,
            tool_parameters=parameters,
            tool_result=tool_result,
            grounded=is_grounded,
            fallback_suggestions=suggestions,
        )
