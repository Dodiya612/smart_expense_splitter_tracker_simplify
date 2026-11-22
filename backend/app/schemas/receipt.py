from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import Field

from app.schemas.common import BaseSchema


class ReceiptLineItem(BaseSchema):
    """One line item read from the bill (T-54). Every number was checked against the OCR text."""

    name: str
    amount_paise: int = Field(..., description="Line amount in integer paise, as printed on the bill.")
    quantity: str | None = Field(None, description="Quantity as printed (e.g. '2'), if it is on the bill.")
    unit_price_paise: int | None = Field(None, description="Unit price in integer paise, if it is on the bill.")


class ReceiptReviewWarning(BaseSchema):
    """Something the user should check before confirming (T-54)."""

    code: str = Field(..., description="e.g. TOTAL_NOT_FOUND, LOW_CONFIDENCE, DATE_IN_FUTURE, ITEMS_DONT_ADD_UP.")
    message: str
    field: Literal["amount", "date", "merchant", "items"] | None = Field(
        None, description="The form field this warning is about, if any."
    )


class ReceiptScanResponseData(BaseSchema):
    """Extracted receipt information returned to client. It is a draft: nothing is saved
    until the user confirms the expense (POST /expenses with receiptId)."""

    receipt_id: uuid.UUID
    merchant: str | None = None
    amount_minor: int | None = None
    amount_paise: int | None = Field(None, description="Same as amountMinor (integer paise).")
    expense_date: date | None = None
    category: str | None = None
    notes: str | None = None
    file_size: int
    items: list[ReceiptLineItem] = Field(
        default_factory=list,
        description="Line items (T-54). Amounts are integer paise and every number is printed on the bill.",
    )
    items_source: Literal["llm", "rules", "none"] = Field(
        "none", description="llm = structured by the LLM and number-checked; rules = rule parser; none = no items."
    )
    warnings: list[ReceiptReviewWarning] = Field(default_factory=list)
    low_confidence_fields: list[Literal["amount", "date", "merchant", "items"]] = Field(
        default_factory=list, description="Fields the review screen highlights."
    )
    confidence: dict[str, float] | None = None
    is_draft: bool = True
    ocr_engine: str | None = None


class ReceiptScanResponse(BaseSchema):
    """Standard envelope for receipt scanning endpoint."""

    data: ReceiptScanResponseData
    message: str = "Receipt processed successfully."


class ReceiptDraftResponse(BaseSchema):
    """Response model for the OCR draft endpoint (T-53, app/api/v1/endpoints/ocr.py)."""

    data: ReceiptScanResponseData
    message: str = "Draft receipt created successfully."


class ReceiptConfirmResponse(BaseSchema):
    """Response model for the OCR confirm endpoint (T-53, app/api/v1/endpoints/ocr.py)."""

    message: str = "Receipt confirmed and saved."
