"""Bill review draft (US-16 / T-54): what the review screen shows after a scan.

Pure functions over the OCR result (T-47) and the checked line items. They decide which
fields to highlight and which warnings to show; nothing is saved here. The expense is
created only when the user confirms the reviewed form (POST /expenses with receiptId).
Any sum shown in a warning is computed here in code from paise, never by the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.ai.line_items import ItemsSource, LineItem, LineItemsResult, to_paise
from app.ai.receipt import ExtractedReceiptData

IST = ZoneInfo("Asia/Kolkata")
LOW_CONFIDENCE = 0.6
OLD_BILL_DAYS = 365

ReviewField = Literal["amount", "date", "merchant", "items"]


@dataclass(frozen=True)
class ReviewWarning:
    code: str
    message: str
    field: ReviewField | None = None


@dataclass(frozen=True)
class BillReview:
    amount_paise: int | None
    expense_date: date | None
    merchant: str | None
    items: list[LineItem]
    items_source: ItemsSource
    warnings: list[ReviewWarning] = field(default_factory=list)
    low_confidence_fields: list[ReviewField] = field(default_factory=list)


def today_in_kolkata(now: datetime | None = None) -> date:
    return (now or datetime.now(IST)).astimezone(IST).date()


def format_inr(paise: int) -> str:
    """₹1,23,456.50 (Indian digit grouping), for warning text only."""
    rupees, rest = divmod(abs(paise), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join([*groups, tail])
    return f"{'-' if paise < 0 else ''}₹{digits}.{rest:02d}"


def _confidence(extracted: ExtractedReceiptData, key: str) -> float:
    value = (extracted.confidence or {}).get(key)
    return float(value) if isinstance(value, (int, float)) else 0.0


def build_review(
    extracted: ExtractedReceiptData,
    line_items: LineItemsResult,
    *,
    today: date | None = None,
) -> BillReview:
    """Warnings and highlighted fields for one scanned bill."""
    today = today or today_in_kolkata()
    warnings: list[ReviewWarning] = []
    low: list[ReviewField] = []

    def flag(field_name: ReviewField) -> None:
        if field_name not in low:
            low.append(field_name)

    amount = extracted.amount_minor if isinstance(extracted.amount_minor, int) and extracted.amount_minor > 0 else None
    bill_date = extracted.expense_date
    merchant = (extracted.merchant or "").strip() or None
    has_text = bool((extracted.raw_text or "").strip()) and extracted.ocr_engine_used not in (None, "none")

    if not has_text:
        warnings.append(
            ReviewWarning(
                "NO_TEXT",
                "We couldn't read this bill. The photo is saved; please fill in the details yourself.",
            )
        )
        return BillReview(
            amount_paise=None,
            expense_date=None,
            merchant=None,
            items=[],
            items_source="none",
            warnings=warnings,
            low_confidence_fields=["amount", "date", "merchant"],
        )

    # Total
    if amount is None:
        warnings.append(ReviewWarning("TOTAL_NOT_FOUND", "We couldn't find the total. Please enter the amount.", "amount"))
        flag("amount")
    elif _confidence(extracted, "total") < LOW_CONFIDENCE:
        warnings.append(ReviewWarning("LOW_CONFIDENCE", "Check the amount – we're not sure we read it right.", "amount"))
        flag("amount")

    # Date
    if bill_date is None:
        warnings.append(ReviewWarning("DATE_NOT_FOUND", "We couldn't find the date. Today's date is filled in.", "date"))
        flag("date")
    else:
        if bill_date > today:
            warnings.append(ReviewWarning("DATE_IN_FUTURE", "The bill date is in the future. Please check it.", "date"))
            flag("date")
        elif bill_date < today - timedelta(days=OLD_BILL_DAYS):
            warnings.append(ReviewWarning("DATE_OLD", "This bill is more than a year old. Please check the date.", "date"))
            flag("date")
        elif _confidence(extracted, "date") < LOW_CONFIDENCE:
            warnings.append(ReviewWarning("LOW_CONFIDENCE", "Check the date – we're not sure we read it right.", "date"))
            flag("date")

    # Merchant
    if merchant is None:
        warnings.append(ReviewWarning("MERCHANT_NOT_FOUND", "We couldn't find the shop name.", "merchant"))
        flag("merchant")
    elif _confidence(extracted, "merchant") < LOW_CONFIDENCE:
        warnings.append(ReviewWarning("LOW_CONFIDENCE", "Check the shop name – we're not sure we read it right.", "merchant"))
        flag("merchant")

    # Line items
    items = line_items.items
    if line_items.dropped:
        warnings.append(
            ReviewWarning(
                "ITEMS_DROPPED",
                "Some line items were left out because their amounts aren't printed on the bill.",
                "items",
            )
        )
        flag("items")
    if items and amount is not None:
        items_sum = sum(i.amount_paise for i in items)
        subtotal = to_paise(repr(extracted.subtotal)) if isinstance(extracted.subtotal, float) else None
        if items_sum not in (amount, subtotal):
            warnings.append(
                ReviewWarning(
                    "ITEMS_DONT_ADD_UP",
                    f"The line items add up to {format_inr(items_sum)}, but the total says "
                    f"{format_inr(amount)}. Check the amount (tax or discounts can explain it).",
                    "amount",
                )
            )
            flag("amount")

    return BillReview(
        amount_paise=amount,
        expense_date=bill_date,
        merchant=merchant,
        items=items,
        items_source=line_items.source,
        warnings=warnings,
        low_confidence_fields=low,
    )
