from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from app.schemas.common import BaseSchema


class ReceiptScanResponseData(BaseSchema):
    """Extracted receipt information returned to client."""

    receipt_id: uuid.UUID
    merchant: str | None = None
    amount_minor: int | None = None
    expense_date: date | None = None
    category: str | None = None
    notes: str | None = None
    file_size: int
    items: list[dict[str, Any]] | None = None
    confidence: dict[str, float] | None = None
    is_draft: bool = True
    ocr_engine: str | None = None


class ReceiptScanResponse(BaseSchema):
    """Standard envelope for receipt scanning endpoint."""

    data: ReceiptScanResponseData
    message: str = "Receipt processed successfully."
