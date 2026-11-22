"""Bill line items with a number check (US-16 / T-54).

The LLM only *structures* line items from the OCR text: it copies each item's name and
the numbers printed next to it. It never calculates anything. Every number it returns is
checked against the numbers that actually appear in the OCR text; an amount that is not
on the bill drops the whole item, and a quantity or unit price that is not on the bill is
cleared. Money is converted to integer paise with Decimal (no floats).

Fallbacks, in order: LLM switched off, no API key, timeout, bad JSON or no valid items ->
the rule parser's items (T-47), which come straight from the text and pass the same check.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_ITEMS = 50
MAX_NAME_LENGTH = 100
MAX_OCR_CHARS = 6000
CENT = Decimal("0.01")

# A number as printed on a bill: 1,234.50 / 1234.5 / 120 / 2
_NUMBER_RE = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|(?<![\d.,])\d+(?:\.\d+)?")

LlmCall = Callable[[str], Awaitable[str | None]]
ItemsSource = Literal["llm", "rules", "none"]


@dataclass(frozen=True)
class LineItem:
    name: str
    amount_paise: int
    quantity: str | None = None
    unit_price_paise: int | None = None


@dataclass(frozen=True)
class LineItemsResult:
    items: list[LineItem] = field(default_factory=list)
    source: ItemsSource = "none"
    dropped: int = 0  # items the LLM returned that failed the number check


# ==============================================================================
# Numbers (pure)
# ==============================================================================


def to_decimal(value: Any) -> Decimal | None:
    """A printed number ("1,234.50", "120", 2) as a Decimal rounded to paise; None if not a number."""
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip().replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    if not text or not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    try:
        return Decimal(text).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def to_paise(value: Any) -> int | None:
    amount = to_decimal(value)
    if amount is None:
        return None
    return int(amount * 100)


def numbers_in_text(text: str) -> set[Decimal]:
    """Every number printed in the OCR text, normalised to two decimals."""
    found: set[Decimal] = set()
    for match in _NUMBER_RE.findall(text or ""):
        amount = to_decimal(match)
        if amount is not None:
            found.add(amount)
    return found


def on_bill(value: Any, printed: set[Decimal]) -> bool:
    amount = to_decimal(value)
    return amount is not None and amount in printed


def _clean_name(value: Any) -> str:
    name = " ".join(str(value or "").split())
    return name[:MAX_NAME_LENGTH]


def checked_item(raw: Any, printed: set[Decimal]) -> LineItem | None:
    """One item from the LLM (or rules) kept only if its amount is printed on the bill."""
    if not isinstance(raw, dict):
        return None
    name = _clean_name(raw.get("name") or raw.get("item_name"))
    amount_raw = raw.get("amount", raw.get("total_price"))
    if not name or not on_bill(amount_raw, printed):
        return None
    amount_paise = to_paise(amount_raw)
    if amount_paise is None or amount_paise <= 0:
        return None
    qty_raw = raw.get("quantity")
    unit_raw = raw.get("unit_price")
    qty = to_decimal(qty_raw) if on_bill(qty_raw, printed) else None
    quantity = format(qty.normalize(), "f") if qty is not None and qty > 0 else None
    unit_price_paise = to_paise(unit_raw) if on_bill(unit_raw, printed) else None
    return LineItem(name=name, amount_paise=amount_paise, quantity=quantity, unit_price_paise=unit_price_paise)


def check_items(raw_items: Any, raw_text: str) -> tuple[list[LineItem], int]:
    """(items that pass the number check, how many were dropped)."""
    if not isinstance(raw_items, list):
        return [], 0
    printed = numbers_in_text(raw_text)
    kept: list[LineItem] = []
    dropped = 0
    for raw in raw_items[:MAX_ITEMS]:
        item = checked_item(raw, printed)
        if item is None:
            dropped += 1
        else:
            kept.append(item)
    return kept, dropped


def rule_items(items: list[dict[str, Any]], raw_text: str) -> list[LineItem]:
    """The rule parser's items (floats from T-47), converted to paise and checked the same way."""
    converted = [
        {
            "name": i.get("item_name"),
            # repr of a float like 120.0 is "120.0"; Decimal keeps it exact before rounding to paise
            "amount": repr(i.get("total_price")) if isinstance(i.get("total_price"), float) else i.get("total_price"),
            "quantity": repr(i.get("quantity")) if isinstance(i.get("quantity"), float) else i.get("quantity"),
            "unit_price": repr(i.get("unit_price")) if isinstance(i.get("unit_price"), float) else i.get("unit_price"),
        }
        for i in items or []
        if isinstance(i, dict)
    ]
    kept, _ = check_items(converted, raw_text)
    return kept


# ==============================================================================
# LLM (Groq) - outside call with a timeout; any failure means "no answer"
# ==============================================================================

SYSTEM_PROMPT = (
    "You read the OCR text of a shop bill and list its line items. "
    "Copy each item's name, quantity, unit price and line amount EXACTLY as printed. "
    "Never calculate, round or invent a number; leave a field out if it is not printed. "
    "Skip totals, subtotals, taxes, discounts and payment lines. "
    'Reply with JSON only: {"items": [{"name": "...", "quantity": "...", "unit_price": "...", "amount": "..."}]}'
)


async def groq_line_items(ocr_text: str, *, http_client: httpx.AsyncClient | None = None) -> str | None:
    """Ask Groq for line items. Returns the raw JSON string, or None on any failure."""
    api_key = settings.GROQ_API_KEY
    if not api_key or not api_key.strip():
        return None
    payload = {
        "model": settings.GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": ocr_text[:MAX_OCR_CHARS]},
        ],
        "temperature": 0.0,
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    timeout = settings.BILL_LINE_ITEMS_TIMEOUT_SECONDS
    url = "https://api.groq.com/openai/v1/chat/completions"
    try:
        if http_client is not None:
            response = await http_client.post(url, json=payload, headers=headers, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return content if isinstance(content, str) else None
    except Exception as exc:  # noqa: BLE001 - the rule parser is the fallback
        logger.warning("Line-item LLM call failed (%s); using rule-parser items", type(exc).__name__)
        return None


def _parse_llm_items(content: str | None) -> Any:
    if not content:
        return None
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return None
    return data.get("items") if isinstance(data, dict) else None


async def structure_line_items(
    raw_text: str | None,
    parser_items: list[dict[str, Any]] | None,
    *,
    llm_call: LlmCall | None = None,
) -> LineItemsResult:
    """Line items for the review screen: LLM (checked) first, then the rule parser's items."""
    text = raw_text or ""
    if not text.strip():
        return LineItemsResult()

    use_llm = settings.AI_ENABLED and settings.BILL_LINE_ITEMS_LLM_ENABLED
    if use_llm:
        call = llm_call or groq_line_items
        try:
            content = await call(text)
        except Exception as exc:  # noqa: BLE001 - never let the LLM break a scan
            logger.warning("Line-item LLM raised %s; using rule-parser items", type(exc).__name__)
            content = None
        kept, dropped = check_items(_parse_llm_items(content), text)
        if dropped:
            logger.info("Line-item number check dropped %d item(s) not printed on the bill", dropped)
        if kept:
            return LineItemsResult(items=kept, source="llm", dropped=dropped)
        fallback = rule_items(parser_items or [], text)
        return LineItemsResult(items=fallback, source="rules" if fallback else "none", dropped=dropped)

    fallback = rule_items(parser_items or [], text)
    return LineItemsResult(items=fallback, source="rules" if fallback else "none")
