"""Budget recommendation service (US-25 / T-55).

Calculates realistic monthly budget goals based on spending patterns from the
last 3 completed calendar months (Asia/Kolkata).

Principles:
- Spending is the user's allocated share of every expense (never cash paid or settlements).
- Soft-deleted expenses are excluded.
- One-off spikes are trimmed: transaction > 50% of that month's category total OR
  > 2× the category's typical monthly baseline.
- Typical monthly baseline is the median of the 3 raw monthly totals.
- Recommendation is median of trimmed monthly totals minus user-selected savings (0%, 5%, 10%),
  rounded to the nearest ₹100 (10,000 paise).
- Groq generates only a one-sentence explanation, guarded against hallucinated numbers.
- Advisory-only: never creates or modifies Budget records.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import BigInteger, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.quota import get_quota_service, log_ai_usage
from app.core.authorization import Action, CategoryPolicy
from app.core.config import settings
from app.models.category import Category
from app.models.user import User
from app.schemas.budget_recommendation import (
    BudgetRecommendationRequest,
    BudgetRecommendationResponse,
    HistoricalMonthSpend,
)
from app.services.analytics_service import AnalyticsFilter, AnySelect, ledger_rows
from app.services.groq_client import GroqClient
from app.services.settlement_service import IST

logger = logging.getLogger("app.budget_recommendation")

RECOMMENDATION_SPENDING_OPTION = "budget_recommendation_spending"
_groq_client: GroqClient | None = None


def get_groq_client() -> GroqClient:
    """Singleton getter for Groq client."""
    global _groq_client
    if _groq_client is None:
        _groq_client = GroqClient(timeout=3.0)
    return _groq_client


def set_groq_client(client: GroqClient | None) -> None:
    """Override Groq client (used in tests)."""
    global _groq_client
    _groq_client = client


# ==============================================================================
# Date & Window Calculations (pure)
# ==============================================================================


def get_last_three_completed_months(reference_date: date | None = None) -> list[tuple[date, date]]:
    """Return [(start_date, end_date), ...] for the last 3 completed calendar months in Asia/Kolkata.
    
    Chronological order (oldest month first).
    """
    if reference_date is None:
        reference_date = datetime.now(IST).date()

    curr_first = date(reference_date.year, reference_date.month, 1)
    months: list[tuple[date, date]] = []
    for _ in range(3):
        prev_end = curr_first - timedelta(days=1)
        prev_start = date(prev_end.year, prev_end.month, 1)
        months.append((prev_start, prev_end))
        curr_first = prev_start

    months.reverse()
    return months


# ==============================================================================
# Maths & Spike Trimming (pure)
# ==============================================================================


def compute_median(values: list[int]) -> int:
    """Compute the integer median of a list of integer values."""
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    mid1, mid2 = s[n // 2 - 1], s[n // 2]
    return (mid1 + mid2 + 1) // 2


def round_to_nearest_100_rupees(amount_paise: int) -> int:
    """Round integer paise to the nearest ₹100 (10,000 paise).
    
    If amount_paise > 0 and rounding yields 0, clamp to minimum ₹100 (10,000 paise).
    """
    if amount_paise <= 0:
        return 0
    # Standard half-up integer rounding to nearest 10,000
    rounded = ((amount_paise + 5000) // 10000) * 10000
    if rounded == 0 and amount_paise > 0:
        return 10000
    return rounded


def trim_monthly_spikes(
    months_txs: list[tuple[str, list[int]]],
) -> tuple[list[HistoricalMonthSpend], int]:
    """Trim one-off transaction spikes per month using the product rule:
    
    A transaction is a spike if:
      - amount > 50% of that month's category total, OR
      - amount > 2× the category's typical monthly baseline.

    The typical monthly baseline is the median of the 3 raw monthly totals.
    Returns: (list of HistoricalMonthSpend, baseline_paise).
    """
    raw_totals = [sum(txs) for _, txs in months_txs]
    baseline_paise = compute_median(raw_totals)

    result_months: list[HistoricalMonthSpend] = []
    for (m_str, txs), month_total in zip(months_txs, raw_totals, strict=True):
        spike_paise = 0
        for tx in txs:
            is_over_50_percent = (month_total > 0) and (tx * 2 > month_total)
            is_over_2x_baseline = (baseline_paise > 0) and (tx > 2 * baseline_paise)
            if is_over_50_percent or is_over_2x_baseline:
                spike_paise += tx

        net_paise = max(0, month_total - spike_paise)
        result_months.append(
            HistoricalMonthSpend(
                month=m_str,
                spent_paise=month_total,
                spike_paise=spike_paise,
                net_paise=net_paise,
            )
        )

    return result_months, baseline_paise


# ==============================================================================
# Grounding Guard & AI Explanation
# ==============================================================================


def verify_grounded_numbers(text: str, allowed_numbers: set[int]) -> bool:
    """Verify that every number present in text is in allowed_numbers.
    
    Strips currency symbols (₹), commas, and percentage signs before checking.
    """
    # Find all contiguous digit sequences
    matches = re.findall(r"\b\d+(?:,\d+)*\b", text)
    for m in matches:
        clean = m.replace(",", "")
        try:
            val = int(clean)
            if val not in allowed_numbers:
                logger.warning("Ungrounded number %d detected in AI explanation: '%s'", val, text)
                return False
        except ValueError:
            return False
    return True


def generate_template_explanation(
    category_name: str,
    raw_median_paise: int,
    savings_level_percent: int,
    recommended_limit_paise: int,
    has_sufficient_history: bool,
) -> str:
    """Deterministic fallback explanation."""
    target_name = category_name or "overall"
    rec_rupees = recommended_limit_paise // 100
    median_rupees = raw_median_paise // 100

    if not has_sufficient_history:
        return f"With limited spending history, your suggested {target_name} budget is ₹{rec_rupees:,}."

    if savings_level_percent == 0:
        return (
            f"Based on your median monthly spending of ₹{median_rupees:,}, "
            f"your recommended {target_name} budget is ₹{rec_rupees:,}."
        )

    return (
        f"Based on your median monthly spending of ₹{median_rupees:,} with a "
        f"{savings_level_percent}% savings target, your recommended {target_name} budget is ₹{rec_rupees:,}."
    )


async def generate_ai_explanation(
    db: AsyncSession,
    user: User,
    category_name: str,
    raw_median_paise: int,
    savings_level_percent: int,
    recommended_limit_paise: int,
    has_sufficient_history: bool,
    baseline_paise: int,
    historical_months: list[HistoricalMonthSpend],
) -> tuple[str, str]:
    """Generate a one-sentence explanation using Groq, with grounding guard and quota management."""
    # Build fallback template
    fallback_text = generate_template_explanation(
        category_name,
        raw_median_paise,
        savings_level_percent,
        recommended_limit_paise,
        has_sufficient_history,
    )

    if not settings.AI_ENABLED:
        return fallback_text, "template_fallback"

    client = get_groq_client()
    if not client.is_configured():
        return fallback_text, "template_fallback"

    # Build set of allowed numbers (in rupees and percentage units)
    allowed: set[int] = {
        recommended_limit_paise // 100,
        raw_median_paise // 100,
        savings_level_percent,
        baseline_paise // 100,
        3,  # "3 months"
        100,  # "₹100 rounding"
    }
    for m in historical_months:
        allowed.add(m.spent_paise // 100)
        allowed.add(m.net_paise // 100)
        allowed.add(m.spike_paise // 100)

    # Format numbers for prompt
    rec_rupees = recommended_limit_paise // 100
    med_rupees = raw_median_paise // 100
    target_name = category_name or "overall"

    prompt = (
        f"You are a personal finance assistant. Write exactly one concise sentence explaining a budget goal.\n"
        f"Category: {target_name}\n"
        f"Median monthly spending: ₹{med_rupees:,}\n"
        f"Savings target: {savings_level_percent}%\n"
        f"Recommended budget: ₹{rec_rupees:,}\n"
        f"CRITICAL RULES:\n"
        f"1. You must output exactly ONE sentence.\n"
        f"2. You must ONLY use the provided numbers (₹{med_rupees:,}, {savings_level_percent}%, ₹{rec_rupees:,}). "
        f"Do NOT invent or calculate any other numbers.\n"
        f"3. Do not include markdown bolding, quotes, or preambles."
    )

    qs = get_quota_service()
    try:
        async with qs.reserve(user_id=user.id, feature="budget_goals", db=db) as reservation:
            if not reservation.allowed:
                logger.info("AI budget_goals quota exceeded for user %s; using template", user.id)
                await log_ai_usage(
                    user_id=user.id,
                    feature="budget_goals",
                    provider="groq",
                    model=settings.GROQ_MODEL,
                    status="quota_exceeded",
                    error_message="Daily quota exceeded; fallback to template",
                    db=db,
                )
                return fallback_text, "template_fallback"

            start_t = time.perf_counter()
            try:
                import httpx

                url = f"{client.base_url}/chat/completions"
                headers = {"Authorization": f"Bearer {client.api_key}", "Content-Type": "application/json"}
                req_json = {
                    "model": client.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 80,
                }

                if client._custom_client is not None:
                    response = await client._custom_client.post(
                        url,
                        headers=headers,
                        json=req_json,
                        timeout=client.timeout,
                    )
                else:
                    async with httpx.AsyncClient(timeout=client.timeout) as http_client:
                        response = await http_client.post(
                            url,
                            headers=headers,
                            json=req_json,
                        )
                latency_ms = (time.perf_counter() - start_t) * 1000.0

                if response.status_code != 200:
                    await reservation.finalize(
                        status="error",
                        error_message=f"Groq HTTP {response.status_code}",
                        latency_ms=latency_ms,
                        db=db,
                    )
                    return fallback_text, "template_fallback"

                payload = response.json()
                raw_text = payload["choices"][0]["message"]["content"].strip()
                # Clean up any quotes
                ai_sentence = raw_text.strip('"').strip()

                # Verify single sentence and grounding guard
                is_grounded = verify_grounded_numbers(ai_sentence, allowed)
                sentence_count = len([s for s in re.split(r"[.!?]+", ai_sentence) if s.strip()])

                if not is_grounded or sentence_count > 2 or not ai_sentence:
                    logger.warning("Groq output failed grounding or format check: '%s'", ai_sentence)
                    await reservation.finalize(
                        status="error",
                        error_message="Ungrounded numbers or multiple sentences generated",
                        latency_ms=latency_ms,
                        db=db,
                    )
                    return fallback_text, "template_fallback"

                await reservation.finalize(
                    status="success",
                    latency_ms=latency_ms,
                    db=db,
                )
                return ai_sentence, "ai"

            except Exception as exc:  # noqa: BLE001
                latency_ms = (time.perf_counter() - start_t) * 1000.0
                logger.warning("Groq call for budget recommendation explanation failed: %s", exc)
                await reservation.finalize(
                    status="error",
                    error_message=str(exc),
                    latency_ms=latency_ms,
                    db=db,
                )
                return fallback_text, "template_fallback"

    except Exception as exc:  # noqa: BLE001
        logger.warning("AI Quota reservation error: %s", exc)
        return fallback_text, "template_fallback"


# ==============================================================================
# Recommendation Orchestration (DB query & assembly)
# ==============================================================================


async def recommend_budget(
    db: AsyncSession,
    user: User,
    payload: BudgetRecommendationRequest,
) -> BudgetRecommendationResponse:
    """Recommend a budget for the given category or overall based on the last 3 completed months."""
    category_name: str | None = None
    if payload.category_id is not None:
        cat_stmt = CategoryPolicy.scope_query(
            select(Category).where(Category.id == payload.category_id), user.id
        )
        cat_result = (await db.execute(cat_stmt)).scalar_one_or_none()
        if cat_result is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_CATEGORY",
                    "message": f"Category '{payload.category_id}' does not exist or is not accessible.",
                },
            )
        CategoryPolicy.authorize(user, cat_result, Action.READ)
        category_name = cat_result.name

    completed_months = get_last_three_completed_months()
    overall_start = completed_months[0][0]
    overall_end = completed_months[-1][1]

    # Query user's allocated share for expenses in the 3-month window
    f = AnalyticsFilter(user_id=user.id, start=overall_start, end=overall_end)
    rows = ledger_rows(f)

    stmt = select(
        rows.c.expense_id,
        rows.c.expense_date,
        rows.c.category_id,
        cast(func.sum(rows.c.share_paise), BigInteger).label("share_paise"),
    ).where(rows.c.share_paise > 0)

    if payload.category_id is not None:
        stmt = stmt.where(rows.c.category_id == payload.category_id)

    stmt = stmt.group_by(rows.c.expense_id, rows.c.expense_date, rows.c.category_id)
    stmt = stmt.execution_options(**{RECOMMENDATION_SPENDING_OPTION: {"filter": f}})

    result = await db.execute(stmt)
    tx_rows = result.all()

    # Bucket transaction amounts by month
    months_txs: list[tuple[str, list[int]]] = []
    for m_start, m_end in completed_months:
        m_str = m_start.strftime("%Y-%m")
        m_txs = [
            int(r.share_paise)
            for r in tx_rows
            if m_start <= r.expense_date <= m_end
        ]
        months_txs.append((m_str, m_txs))

    # Evaluate history sufficiency
    # Sufficient history requires user to have had an account during the period and non-zero spending
    user_created_date = (
        user.created_at.astimezone(IST).date()
        if hasattr(user, "created_at") and user.created_at is not None
        else date(2000, 1, 1)
    )
    total_window_spend = sum(sum(txs) for _, txs in months_txs)
    has_sufficient_history = (
        (user_created_date <= overall_start or user_created_date <= completed_months[1][0])
        and total_window_spend > 0
    )

    # Trim spikes
    historical_months, baseline_paise = trim_monthly_spikes(months_txs)

    # Compute median of trimmed monthly totals
    raw_median_paise = compute_median([m.net_paise for m in historical_months])

    # Deduct savings
    savings_paise = (raw_median_paise * payload.savings_level_percent + 50) // 100
    after_savings = max(0, raw_median_paise - savings_paise)

    # Round to nearest ₹100
    recommended_limit_paise = round_to_nearest_100_rupees(after_savings)

    # Explanation
    explanation, source = await generate_ai_explanation(
        db=db,
        user=user,
        category_name=category_name or "Overall",
        raw_median_paise=raw_median_paise,
        savings_level_percent=payload.savings_level_percent,
        recommended_limit_paise=recommended_limit_paise,
        has_sufficient_history=has_sufficient_history,
        baseline_paise=baseline_paise,
        historical_months=historical_months,
    )

    return BudgetRecommendationResponse(
        category_id=payload.category_id,
        category_name=category_name,
        savings_level_percent=payload.savings_level_percent,
        has_sufficient_history=has_sufficient_history,
        historical_months=historical_months,
        baseline_paise=baseline_paise,
        raw_median_paise=raw_median_paise,
        savings_paise=savings_paise,
        recommended_limit_paise=recommended_limit_paise,
        explanation=explanation,
        source=source,
    )
