from __future__ import annotations

import uuid
from datetime import date

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


class ReceiptScanResponse(BaseSchema):
    """Standard envelope for receipt scanning endpoint."""

    data: ReceiptScanResponseData
    message: str = "Receipt processed successfully."
