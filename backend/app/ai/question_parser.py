"""Offline question parser for the expense assistant (T-57 / US-24).

Picks one of the eight query tools and fills its slots without a language model.
It is used when no model is configured or the model cannot be reached, and it is
measured on the same 60 questions as the model (evals/assistant).

All matching is on whole words, so "vegetables" never matches "table" and
"chocolates" never matches the merchant "Ola". A question that asks for
something no tool can do (another user's data, one person's balance, spending
in one group, an item such as "coffee", money transfers, trends over time) is
refused with a reason instead of being answered as a different question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from app.ai.category_terms import CategoryName, find_category
from app.services.date_ranges import (
    Month,
    PeriodError,
    PeriodSlots,
    RelativePeriod,
    month_range,
    periods_from_text,
    today_in_kolkata,
    week_range,
)

Outcome = Literal["tool", "unsupported", "unsupported_filter", "unsupported_scope", "period"]


@dataclass(frozen=True)
class ParsedQuestion:
    outcome: Outcome
    tool: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None


# Merchants the parser recognises anywhere in a question (display name by lowercase word).
KNOWN_MERCHANTS: dict[str, str] = {
    "starbucks": "Starbucks",
    "amazon": "Amazon",
    "swiggy": "Swiggy",
    "zomato": "Zomato",
    "uber": "Uber",
    "ola": "Ola",
    "rapido": "Rapido",
    "blinkit": "Blinkit",
    "zepto": "Zepto",
    "bigbasket": "BigBasket",
    "flipkart": "Flipkart",
    "myntra": "Myntra",
    "mcdonald's": "McDonald's",
    "mcdonalds": "McDonald's",
    "domino's": "Domino's",
    "dominos": "Domino's",
    "kfc": "KFC",
    "netflix": "Netflix",
    "spotify": "Spotify",
    "dmart": "DMart",
    "d-mart": "DMart",
    "bookmyshow": "BookMyShow",
    "pvr": "PVR",
    "irctc": "IRCTC",
    "airtel": "Airtel",
    "jio": "Jio",
}

MAX_RECURRING_DAYS = 31
MAX_LISTED = 10


def _words(*phrases: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w'-])(?:" + "|".join(phrases) + r")(?![\w'-])")


_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_INJECTION = re.compile(
    r"\bignore\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier)?\s*instructions\b"
    r"|\bsystem\s+prompt\b|\bjailbreak\b|\byou\s+are\s+now\b|\bdeveloper\s+mode\b"
)
_OFF_TOPIC = _words(
    "weather", "jokes?", "poems?", "story", "stories", "news", "cricket", "football", "capital of",
    "president", "prime minister", "bitcoin", "crypto", "cryptocurrency", "stocks?", "invest",
    "investing", "investment", "password", "api key",
)
_MOVE_MONEY = _words("transfer", "send money", "send", "pay back", "repay", "refund")
_OTHER_PEOPLE = re.compile(
    r"\b(?:all|other|every|another)\s+users?\b|\beveryone\b|\beverybody\b|\bsomeone\s+else\b"
    r"|\bother\s+people\b|\b(?:his|her|their)\s+(?:spending|expenses?|budgets?)\b|\bfriend's\b"
    r"|\b(?:what|how\s+much)\s+did\s+(?!i\b|we\b)[a-z]+\s+spend\b"
)
# One person's balance ("How much does Blair owe me?", "How much do I owe Casey?").
_ONE_PERSON = re.compile(
    r"\b(?:does|did|do)\s+(?!i\b|we\b|you\b)[a-z]+\s+owe\b"
    r"|\bowe\s+(?!me\b|anyone\b|anybody\b|in\b|across\b|to\b|for\b|on\b|the\b|my\b|overall\b|altogether\b"
    r"|in\s+total\b|right\b|now\b|at\b|from\b|with\b)[a-z]+\b"
)
_GROUP = _words("groups?")
_MONEY_WORDS = _words(
    "spend", "spent", "spending", "expenses?", "costs?", "paid", "pay", "owe", "owes", "owed", "owing",
    "balances?", "settled", "total", "average", "avg", "breakdown", "categor(?:y|ies)", "transactions?",
    "purchases?", "history", "trends?", "bought", "buy", "money", "budgets?", "recurring", "subscriptions?",
    "upcoming", "due", "coming up", "merchants?", "shops?", "stores?", "orders?", "payments?", "bills?",
    "compare", "rides?",
)

_TREND = _words(
    "trends?", "over time", "by day", "by week", "by month", "day by day", "week by week", "month by month",
    "each day", "each week", "each month", "every day", "every week", "every month", "graph", "chart",
)
_BUDGET = _words("budgets?", "spending limits?", "over my limit", "within my limit")
_RECURRING = _words("recurring", "subscriptions?", "upcoming", "coming up", "due", "scheduled", "repeat(?:ing)?")
_BALANCES = _words("owe", "owes", "owed", "owing", "balances?", "settle up", "settled up")
_COMPARE = _words(r"compare[sd]?", "comparison", "compared", r"vs\.?", "versus", "difference between")
_THAN = _words("than")
_MERCHANTS = re.compile(
    r"\b(?:top|which|what|my)\s+(?:\d{1,2}\s+)?(?:merchants?|shops?|stores?|payees?)\b"
    r"|\bmerchants?\b|\bwhere\s+do\s+i\s+shop\b|\bwho\s+(?:did|do)\s+i\s+pay\s+the\s+most\b"
)
_BREAKDOWN = re.compile(
    r"\bbreak\s*down\b|\bby\s+category\b|\bper\s+category\b|\bcategory[\s-]wise\b|\beach\s+category\b"
    r"|\b(?:which|what|top)\s+(?:\d{1,2}\s+)?categor(?:y|ies)\b"
    r"|\b(?:biggest|largest|highest|top)\s+(?:spending\s+)?categor(?:y|ies)\b"
    r"|\bwhere\s+(?:did|do)\s+i\s+spend\b|\bwhere\s+(?:does|did)\s+(?:all\s+)?my\s+money\s+go\b|\bmost\s+money\b"
)
_EXPENSE_NOUNS = r"(?:expenses|transactions|purchases|orders|payments|bills|rides)"
_LIST = re.compile(
    rf"\b(?:show|list|see|display|give)\b.*\b{_EXPENSE_NOUNS}\b"
    rf"|\b(?:recent|latest)\s+(?:\w+\s+)?(?:expenses?|transactions?|purchases?|orders?)\b"
    r"|\b(?:biggest|largest|highest|costliest|most\s+expensive)\s+(?:\w+\s+)?"
    r"(?:expenses?|transactions?|purchases?|orders?|bills?|payments?|spends?)\b"
    r"|\b(?:last|top)\s+\d{1,2}\s+(?:expenses|transactions|purchases)\b"
    r"|\b(?:expense|transaction)\s+history\b"
)
_LARGEST = _words("biggest", "largest", "highest", "costliest", "most expensive", "top")
_SINGULAR_LARGEST = re.compile(
    r"\b(?:biggest|largest|highest|costliest|most\s+expensive)\s+(?:\w+\s+)?"
    r"(?:expense|transaction|purchase|order|bill|payment|spend)\b(?!s)"
)
_LIST_COUNT = re.compile(rf"\b(\d{{1,3}})\s+(?:(?:most\s+)?\w+\s+)?{_EXPENSE_NOUNS}\b")
_TOP_N = re.compile(r"\btop\s+(\d{1,3})\b")
_RECENT = re.compile(rf"\b(?:recent|latest|newest)\b|\blast\s+(?:\d{{1,3}}\s+)?{_EXPENSE_NOUNS}\b")
_AVERAGE = _words("average", "avg", "per day", "a day")
_COUNT = _words("how many", "number of", "count of", "count")
_TOTAL = _words("how much", "total", "spend", "spent", "spending", "expenses?")
_AT_NAME = re.compile(r"\bat\s+([A-Z][\w'&.-]*(?:\s+[A-Z][\w'&.-]*){0,2})")
_ON_WORD = re.compile(r"\bon\s+([a-z][a-z'-]*)")
_NOT_AN_ITEM = {
    "a", "an", "the", "my", "me", "it", "this", "that", "these", "those", "what", "which", "each",
    "every", "all", "average", "avg", "total", "expenses", "expense", "spending", "things", "stuff",
    "everything", "anything", "record", "purchases", "transactions", "track",
}
_NEXT_DAYS = re.compile(r"\b(?:next|coming|following)\s+(\d{1,3})\s+days?\b|\b(\d{1,3})\s+days?\b")

# A group named in a balance question.
_GROUP_NAMED = [
    re.compile(r"\b(?:in|for|from|with|of)\s+(?:the\s+|my\s+|our\s+)?([A-Za-z0-9][\w&'.,()-]*(?:\s+[\w&'.,()-]+){0,5}?)\s+group\b", re.I),
    re.compile(r"\bgroup\s+(?:called\s+|named\s+)?[\"“']?([A-Za-z0-9][^\"”'?!.,]*?)[\"”']?\s*(?:[?.!]|$)", re.I),
    re.compile(r"\b(?:in|for)\s+[\"“']([^\"”']{1,60})[\"”']"),
    re.compile(r"\b(?:in|for)\s+([A-Z][\w&'.-]*(?:\s+[A-Z][\w&'.-]*){0,4})"),
]
_NOT_A_GROUP = {"my", "all", "any", "every", "each", "your", "our", "the", "total", "a", "this", "that"}
_MONTH_WORDS = {m.value for m in Month} | {"jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
                                            "nov", "dec"}


def _merchant(question: str, norm: str) -> str | None:
    for word, display in KNOWN_MERCHANTS.items():
        if re.search(r"(?<![\w'-])" + re.escape(word) + r"(?![\w'-])", norm):
            return display
    match = _AT_NAME.search(question)
    if match:
        name = match.group(1).strip(" .")
        if find_category(name) is None and not re.search(r"\d", name) and name.lower() not in _MONTH_WORDS:
            return name[:40]
    return None


def _group_named(question: str) -> str | None:
    for pattern in _GROUP_NAMED:
        match = pattern.search(question)
        if not match:
            continue
        name = match.group(1).strip(" .,'\"")
        words = name.lower().split()
        if not words or words[0] in _NOT_A_GROUP or words[-1] == "groups":
            continue
        if words[0] in _MONTH_WORDS or find_category(name) is not None:
            continue
        return name[:60]
    return None


def _period_slot(period: PeriodSlots | None) -> dict[str, Any]:
    if period is None or period.is_empty():
        return {}
    return {"period": period.model_dump(exclude_none=True, mode="json")}


def _with_category(slots: dict[str, Any], category: CategoryName | None) -> dict[str, Any]:
    if category is not None:
        slots["category"] = category.value
    return slots


def _recurring_days(norm: str, today: date) -> int:
    match = _NEXT_DAYS.search(norm)
    if match:
        return int(match.group(1) or match.group(2))
    if re.search(r"\btoday\b", norm):
        return 1
    if re.search(r"\btomorrow\b", norm):
        return 2
    if re.search(r"\b(?:rest\s+of\s+)?(?:this|current)\s+week\b", norm):
        return (week_range(today)[1] - today).days + 1
    if re.search(r"\b(?:rest\s+of\s+)?(?:this|current)\s+month\b", norm):
        return (month_range(today)[1] - today).days + 1
    if re.search(r"\b(?:next|coming)\s+month\b|\bmonth\b", norm):
        return MAX_RECURRING_DAYS
    return 7  # "next week", "soon", or nothing said


# The period a one-period comparison is compared against ("than last month" means this month).
_COMPARED_WITH: dict[RelativePeriod, RelativePeriod] = {
    RelativePeriod.YESTERDAY: RelativePeriod.TODAY,
    RelativePeriod.LAST_WEEK: RelativePeriod.THIS_WEEK,
    RelativePeriod.LAST_MONTH: RelativePeriod.THIS_MONTH,
    RelativePeriod.LAST_YEAR: RelativePeriod.THIS_YEAR,
}


def _compare(periods: list[PeriodSlots], category: CategoryName | None) -> ParsedQuestion:
    if len(periods) == 1 and periods[0].date_range in _COMPARED_WITH:
        periods = [PeriodSlots(date_range=_COMPARED_WITH[periods[0].date_range]), periods[0]]
    if len(periods) != 2:
        return ParsedQuestion(
            "period", reason="I can compare two periods, for example this month and last month."
        )
    slots = {
        "a": periods[0].model_dump(exclude_none=True, mode="json"),
        "b": periods[1].model_dump(exclude_none=True, mode="json"),
    }
    return ParsedQuestion("tool", "compare_periods", _with_category(slots, category))


def _list(norm: str, period: PeriodSlots | None, category: CategoryName | None, merchant: str | None) -> ParsedQuestion:
    filters = _with_category(_period_slot(period), category)
    if merchant is not None:
        filters["merchant"] = merchant
    slots: dict[str, Any] = {"filters": filters} if filters else {}
    largest = bool(_LARGEST.search(norm)) and not _RECENT.search(norm)
    if largest:
        slots["sort"] = "largest"
    count = _LIST_COUNT.search(norm) or _TOP_N.search(norm)
    if count:
        n = int(count.group(1))
        if not 1 <= n <= MAX_LISTED:
            return ParsedQuestion("unsupported_filter", reason=f"I can show at most {MAX_LISTED} expenses at a time.")
        slots["limit"] = n
    elif largest and _SINGULAR_LARGEST.search(norm):
        slots["limit"] = 1
    return ParsedQuestion("tool", "list_expenses", slots)


def parse_question(question: str, today: date | None = None) -> ParsedQuestion:
    """Choose a tool and its slots for a question, or say why it cannot be answered."""
    today = today or today_in_kolkata()
    text = " ".join(question.replace("’", "'").replace("“", '"').replace("”", '"').split())
    norm = text.lower()

    if not norm or _INJECTION.search(norm) or _OFF_TOPIC.search(norm):
        return ParsedQuestion("unsupported")
    if _MOVE_MONEY.search(norm):
        return ParsedQuestion("unsupported", reason="I can't move money. I can only answer questions about your spending.")
    if _UUID.search(norm) or _OTHER_PEOPLE.search(norm):
        return ParsedQuestion("unsupported_scope")
    if not _MONEY_WORDS.search(norm):
        return ParsedQuestion("unsupported")
    if _TREND.search(norm):
        return ParsedQuestion(
            "unsupported_filter",
            reason="Spending over time is on the Insights screen. I can compare two periods, for example this "
            "month and last month.",
        )

    category = find_category(norm)
    if _BUDGET.search(norm):
        return ParsedQuestion("tool", "budget_status", _with_category({}, category))
    if _RECURRING.search(norm):
        days = _recurring_days(norm, today)
        if not 1 <= days <= MAX_RECURRING_DAYS:
            return ParsedQuestion("period", reason=f"I can look at most {MAX_RECURRING_DAYS} days ahead.")
        return ParsedQuestion("tool", "recurring_upcoming", {} if days == 7 else {"days": days})
    if _BALANCES.search(norm):
        if _ONE_PERSON.search(norm):
            return ParsedQuestion(
                "unsupported_filter",
                reason="I can't show what you owe one person. Open the group's balances to see each member.",
            )
        group = _group_named(text)
        return ParsedQuestion("tool", "owed_summary", {"group": group} if group else {})
    if _GROUP.search(norm):
        return ParsedQuestion(
            "unsupported_filter",
            reason="I can't answer for a single group yet. Ask about all your spending, or open the group to see "
            "its expenses.",
        )

    try:
        periods = periods_from_text(text, today)
    except PeriodError as exc:
        return ParsedQuestion("period", reason=str(exc))

    if _COMPARE.search(norm) or (_THAN.search(norm) and periods):
        return _compare(periods, category)
    if len(periods) > 1:
        return ParsedQuestion("period", reason="I can answer for one period at a time.")
    period = periods[0] if periods else None
    merchant = _merchant(text, norm)

    if _MERCHANTS.search(norm):
        slots = _period_slot(period)
        top = _TOP_N.search(norm)
        if top:
            n = int(top.group(1))
            if not 1 <= n <= MAX_LISTED:
                return ParsedQuestion("unsupported_filter", reason=f"I can name at most {MAX_LISTED} merchants.")
            slots["n"] = n
        return ParsedQuestion("tool", "top_merchants", slots)
    if _BREAKDOWN.search(norm):
        slots = _period_slot(period)
        top = _TOP_N.search(norm)
        if top and 1 <= int(top.group(1)) <= 12:
            slots["limit"] = int(top.group(1))
        return ParsedQuestion("tool", "spend_by_category", slots)
    if _LIST.search(norm) or merchant is not None:
        return _list(norm, period, category, merchant)
    if _AVERAGE.search(norm):
        return ParsedQuestion("tool", "spend_total", _with_category({**_period_slot(period), "measure": "daily_average"}, category))
    if _COUNT.search(norm):
        return ParsedQuestion("tool", "spend_total", _with_category({**_period_slot(period), "measure": "count"}, category))
    if category is not None:
        return ParsedQuestion("tool", "spend_total", _with_category(_period_slot(period), category))

    for match in _ON_WORD.finditer(norm):
        word = match.group(1)
        if word not in _NOT_AN_ITEM and word not in _MONTH_WORDS:
            return ParsedQuestion(
                "unsupported_filter",
                reason=(
                    f"I can't filter by '{word}'. I can answer by category (for example Food & Dining) "
                    "or by merchant (for example Swiggy)."
                ),
            )

    if _TOTAL.search(norm):
        return ParsedQuestion("tool", "spend_total", _period_slot(period))
    return ParsedQuestion("unsupported")

