"""Deterministic Grounding Guard for AI Assistant (T-57 / US-24).

Strict Invariants:
1. Every numerical value in the generated response must be strictly supported by tool results.
2. If any numerical value is not supported, the response is rejected and replaced by a safe,
   predefined template sentence.
3. Zero invented numerical values are permitted in user-facing output.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GroundingCheckResult:
    """Result of deterministic grounding validation."""

    is_grounded: bool
    violations: list[float]
    final_answer: str
    rejection_reason: str | None = None


class GroundingGuard:
    """Deterministic validation guard preventing LLM numerical hallucination."""

    # Regex capturing potential numbers in text (amounts, integers, floats, percentages)
    NUMBER_PATTERN = re.compile(
        r"(?:₹|Rs\.?|INR\s*)?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)(?:st|nd|rd|th)?%?",
        re.IGNORECASE,
    )

    @classmethod
    def collect_allowed_numbers(cls, tool_result: dict[str, Any]) -> set[float]:
        """Extract all valid, supported numerical values from tool result data."""
        allowed: set[float] = set()

        # Add 0 by default (zero transactions or zero amount is always valid)
        allowed.add(0.0)

        def add_num(val: Any) -> None:
            if val is None:
                return
            if isinstance(val, (int, float)):
                allowed.add(float(val))
                # If amount is in paise (>= 100), also allow its rupee representation
                if val >= 100:
                    allowed.add(round(float(val) / 100.0, 2))
                    allowed.add(float(val) / 100.0)
            elif isinstance(val, str):
                # Check if it's an ISO date or contains digits
                date_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", val.strip())
                if date_match:
                    allowed.add(float(date_match.group(1)))  # Year
                    allowed.add(float(date_match.group(2)))  # Month
                    allowed.add(float(date_match.group(3)))  # Day
                else:
                    try:
                        f = float(val.replace(",", "").strip())
                        allowed.add(f)
                    except ValueError:
                        pass

        def scan_dict(d: dict[str, Any]) -> None:
            for k, v in d.items():
                if isinstance(v, (int, float)):
                    add_num(v)
                    if "paise" in k:
                        allowed.add(round(v / 100.0, 2))
                        allowed.add(v / 100.0)
                elif isinstance(v, str):
                    add_num(v)
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            scan_dict(item)
                        else:
                            add_num(item)
                elif isinstance(v, dict):
                    scan_dict(v)

        scan_dict(tool_result)

        # Allow indices 1..count if a list of items is returned
        if "count" in tool_result and isinstance(tool_result["count"], int):
            for i in range(1, tool_result["count"] + 1):
                allowed.add(float(i))
        if "transaction_count" in tool_result and isinstance(tool_result["transaction_count"], int):
            for i in range(1, min(tool_result["transaction_count"] + 1, 100)):
                allowed.add(float(i))

        return allowed

    @classmethod
    def extract_numbers_from_text(cls, text: str) -> list[float]:
        """Extract all standalone numbers from response text."""
        numbers: list[float] = []
        for match in cls.NUMBER_PATTERN.finditer(text):
            raw = match.group(1).replace(",", "")
            try:
                val = float(raw)
                numbers.append(val)
            except ValueError:
                continue
        return numbers

    @classmethod
    def build_safe_template(cls, tool_result: dict[str, Any]) -> str:
        """Construct a safe, predefined template sentence containing only verified facts."""
        tool_name = tool_result.get("tool", "")
        period = tool_result.get("period_label", "the specified period")
        period_str = f"for {period}" if period and period != "all time" else "overall"

        if tool_name == "get_spending_by_category":
            category = tool_result.get("category", "this category")
            amt = tool_result.get("total_rupees", 0.0)
            cnt = tool_result.get("transaction_count", 0)
            if cnt == 0:
                return f"Based on your verified records, you have no expenses for {category} {period_str}."
            return (
                f"Based on your verified records, you spent ₹{amt:.2f} across "
                f"{cnt} transactions on {category} {period_str}."
            )

        if tool_name == "get_total_spending":
            amt = tool_result.get("total_rupees", 0.0)
            cnt = tool_result.get("transaction_count", 0)
            if cnt == 0:
                return f"Based on your verified records, you have no recorded expenses {period_str}."
            return (
                f"Based on your verified records, your total spending {period_str} "
                f"is ₹{amt:.2f} across {cnt} transactions."
            )

        if tool_name == "get_category_breakdown":
            breakdown = tool_result.get("breakdown", [])
            amt = tool_result.get("total_rupees", 0.0)
            cnt = tool_result.get("transaction_count", 0)
            if not breakdown or cnt == 0:
                return f"Based on your verified records, no expenses were found {period_str}."
            lines = [f"{item['category']}: ₹{item['total_rupees']:.2f}" for item in breakdown[:5]]
            summary = ", ".join(lines)
            return (
                f"Based on your verified records, your top category spending {period_str} "
                f"totals ₹{amt:.2f} ({summary})."
            )

        if tool_name == "get_recent_expenses":
            expenses = tool_result.get("expenses", [])
            if not expenses:
                return f"Based on your verified records, no expenses were found {period_str}."
            lines = [f"{e['description']} (₹{e['amount_rupees']:.2f})" for e in expenses[:5]]
            summary = ", ".join(lines)
            return f"Based on your verified records, your recent expenses {period_str} are: {summary}."

        if tool_name == "get_highest_expense":
            exp = tool_result.get("expense")
            if not exp:
                return f"Based on your verified records, no expenses were found {period_str}."
            return (
                f"Based on your verified records, your highest single expense {period_str} was "
                f"'{exp['description']}' for ₹{exp['amount_rupees']:.2f} in {exp['category']}."
            )

        if tool_name == "get_spending_by_merchant":
            merchant = tool_result.get("merchant", "this merchant")
            amt = tool_result.get("total_rupees", 0.0)
            cnt = tool_result.get("transaction_count", 0)
            if cnt == 0:
                return f"Based on your verified records, you have no recorded spending at {merchant} {period_str}."
            return (
                f"Based on your verified records, you spent ₹{amt:.2f} across "
                f"{cnt} transactions at {merchant} {period_str}."
            )

        if tool_name == "get_daily_average_spending":
            avg = tool_result.get("average_daily_rupees", 0.0)
            tot = tool_result.get("total_rupees", 0.0)
            days = tool_result.get("days", 1)
            return (
                f"Based on your verified records, your average daily spending {period_str} "
                f"was ₹{avg:.2f} per day over {days} days (total ₹{tot:.2f})."
            )

        if tool_name == "get_expenses_count":
            cnt = tool_result.get("transaction_count", 0)
            cat = tool_result.get("category")
            if cat:
                return f"Based on your verified records, you recorded {cnt} transactions for {cat} {period_str}."
            return f"Based on your verified records, you recorded {cnt} transactions {period_str}."

        # Generic safe summary
        tot = tool_result.get("total_rupees", 0.0)
        cnt = tool_result.get("transaction_count", 0)
        return (
            f"Based on your verified records, you have {cnt} transactions totaling "
            f"₹{tot:.2f} {period_str}."
        )

    @classmethod
    def validate_and_guard(
        cls,
        candidate_answer: str,
        tool_result: dict[str, Any],
    ) -> GroundingCheckResult:
        """Validate that all numbers in candidate_answer are strictly present in tool_result.

        If ungrounded numbers are detected, reject candidate_answer and replace with
        predefined safe template sentence.
        """
        allowed_numbers = cls.collect_allowed_numbers(tool_result)
        extracted_numbers = cls.extract_numbers_from_text(candidate_answer)

        violations: list[float] = []
        for num in extracted_numbers:
            # Check with small float tolerance
            matched = any(abs(num - allowed) < 0.01 for allowed in allowed_numbers)
            if not matched:
                violations.append(num)

        if violations:
            logger.warning(
                "Grounding violation detected! Unverified numbers in LLM answer: %s. Allowed: %s",
                violations,
                sorted(allowed_numbers),
            )
            safe_template = cls.build_safe_template(tool_result)
            return GroundingCheckResult(
                is_grounded=False,
                violations=violations,
                final_answer=safe_template,
                rejection_reason=f"Detected unverified numerical value(s): {violations}",
            )

        return GroundingCheckResult(
            is_grounded=True,
            violations=[],
            final_answer=candidate_answer,
        )
