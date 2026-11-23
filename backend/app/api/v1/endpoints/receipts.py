"""Receipts API Endpoints (US-16).

Provides:
- POST /api/v1/receipts/scan: Upload and process receipt bill image, check quota, store privately, and extract fields.
- GET /api/v1/receipts/{receipt_id}/image: Securely view receipt image for owner or group expense members.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.bill_review import build_review
from app.ai.line_items import structure_line_items
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import image_too_large_error
from app.models.user import User
from app.schemas.receipt import (
    ReceiptLineItem,
    ReceiptReviewWarning,
    ReceiptScanResponse,
    ReceiptScanResponseData,
)
from app.services.receipt_service import get_receipt_image, scan_and_store_receipt

router = APIRouter()

MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post(
    "/scan",
    response_model=ReceiptScanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Scan and process a receipt bill image",
    description="Uploads a receipt image (JPEG or PNG), validates magic bytes, strips EXIF/GPS, "
    "compresses below 1 MB, stores privately under a random key, checks daily AI quota, and runs extraction. "
    "The result is a draft for the review screen (T-54): line items whose numbers are all printed on the "
    "bill, warnings, and the fields to highlight. Nothing is saved as an expense until the user confirms "
    "(POST /expenses with receiptId); an unconfirmed scan is deleted after 24 hours.",
)
async def scan_receipt_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File(description="Receipt image file (JPEG or PNG, max 5 MB)")],
) -> ReceiptScanResponse:
    # Read with 5 MB + 1 byte guard
    raw_bytes = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(raw_bytes) > MAX_UPLOAD_SIZE:
        raise image_too_large_error("Uploaded image exceeds the 5 MB limit.")

    receipt, extracted = await scan_and_store_receipt(
        db=db,
        current_user=current_user,
        raw_bytes=raw_bytes,
    )

    # T-54: line items (LLM structures, code checks every number) and the review warnings.
    line_items = await structure_line_items(extracted.raw_text, list(extracted.items or []))
    review = build_review(extracted, line_items)

    return ReceiptScanResponse(
        data=ReceiptScanResponseData(
            receipt_id=receipt.id,
            merchant=review.merchant,
            amount_minor=review.amount_paise,
            amount_paise=review.amount_paise,
            expense_date=review.expense_date,
            category=extracted.category,
            notes=extracted.notes,
            file_size=receipt.file_size,
            items=[
                ReceiptLineItem(
                    name=i.name,
                    amount_paise=i.amount_paise,
                    quantity=i.quantity,
                    unit_price_paise=i.unit_price_paise,
                )
                for i in review.items
            ],
            items_source=review.items_source,
            warnings=[ReceiptReviewWarning(code=w.code, message=w.message, field=w.field) for w in review.warnings],
            low_confidence_fields=review.low_confidence_fields,
            confidence=extracted.confidence if hasattr(extracted, "confidence") else None,
            is_draft=True,
            ocr_engine=getattr(extracted, "ocr_engine_used", None),
        ),
        message="Receipt processed successfully.",
    )


@router.get(
    "/{receipt_id}/image",
    summary="Retrieve receipt image content",
    description="Retrieves the stored receipt image bytes. Accessible only by the receipt owner. Returns 404 for unauthorized users.",
)
async def get_receipt_image_endpoint(
    receipt_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    data, content_type = await get_receipt_image(
        db=db,
        receipt_id=receipt_id,
        current_user=current_user,
    )

    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
