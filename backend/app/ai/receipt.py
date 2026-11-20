"""Receipt Information Extraction Service (US-16 / T-47).

Owned by Parthiv Panchal.
Provides a multi-tier OCR pipeline for extracting fields from processed receipt images:
1. Primary Cloud Reader: OCR.space API (fast, handles skewed bills, table structures).
2. Offline Local Reader: Tesseract OCR fallback (when OCR.space fails or times out).
3. Rule Parser: Extracts merchant, date, total, line items, and confidence per field.
4. Pre-filled Draft: Prepares draft expense payload; nothing saves without user confirmation.
5. Safe Empty Fallback: When both engines fail or are disabled, returns an empty draft form
   with the image safely retained in storage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.ai.ocr_space import extract_text_ocr_space
from app.ai.rule_parser import RuleParser
from app.ai.tesseract import extract_text_tesseract

try:
    from app.core.config import settings
except ImportError:
    settings = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractedReceiptData:
    """Fields extracted from bill image by LLM/OCR."""

    merchant: str | None = None
    amount_minor: int | None = None  # in paise (integer)
    expense_date: date | None = None
    category: str | None = None
    notes: str | None = None
    raw_text: str | None = None
    total_amount: float | None = None  # in rupees (float)
    subtotal: float | None = None
    tax: float | None = None
    payment_mode: str | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    confidence: dict[str, float] = field(default_factory=dict)
    confidence_merchant: float | None = None
    confidence_amount: float | None = None
    confidence_date: float | None = None
    is_draft: bool = True
    ocr_engine_used: str | None = None


async def extract_receipt_data(
    image_bytes: bytes,
    *,
    ocr_space_enabled: bool | None = None,
    tesseract_enabled: bool | None = None,
    timeout_ocr_space: float | None = None,
    timeout_tesseract: float | None = None,
) -> ExtractedReceiptData:
    """Execute the multi-tier OCR pipeline to extract bill fields.

    Pipeline:
    1. Try OCR.space API with timeout.
    2. Fall back to Tesseract OCR if OCR.space fails or times out.
    3. If both engines fail or are switched off, gracefully return an empty draft.
    4. Pass extracted text to RuleParser for merchant, date, total, and confidence calculation.
    """
    use_ocr_space = (
        ocr_space_enabled
        if ocr_space_enabled is not None
        else (getattr(settings, "OCR_SPACE_ENABLED", True) if settings else True)
    )
    use_tesseract = (
        tesseract_enabled
        if tesseract_enabled is not None
        else (getattr(settings, "TESSERACT_ENABLED", True) if settings else True)
    )

    raw_text: str | None = None
    engine_used = "none"

    # Step 1: Attempt OCR.space cloud extraction
    if use_ocr_space:
        try:
            logger.info("Attempting OCR extraction via OCR.space API...")
            raw_text = await extract_text_ocr_space(
                image_bytes=image_bytes,
                timeout_seconds=timeout_ocr_space,
            )
            if raw_text:
                engine_used = "ocr_space"
                logger.info("OCR.space successfully extracted %d characters", len(raw_text))
            else:
                logger.warning("OCR.space returned no text; falling back to local Tesseract.")
        except Exception as exc:
            logger.warning("OCR.space extraction failed (%s); falling back to Tesseract.", exc)

    # Step 2: Fall back to local Tesseract reader
    if not raw_text and use_tesseract:
        try:
            logger.info("Attempting OCR extraction via local Tesseract fallback...")
            raw_text = await extract_text_tesseract(
                image_bytes=image_bytes,
                timeout_seconds=timeout_tesseract,
            )
            if raw_text:
                engine_used = "tesseract"
                logger.info("Tesseract successfully extracted %d characters", len(raw_text))
            else:
                logger.warning("Tesseract returned no text.")
        except Exception as exc:
            logger.warning("Tesseract fallback failed (%s).", exc)

    # Step 3: If both are switched off or produced no text, return empty draft
    if not raw_text:
        logger.info(
            "No OCR text extracted (both engines disabled, timed out, or unavailable). "
            "Returning empty draft form with image safely retained."
        )
        return ExtractedReceiptData(
            merchant=None,
            amount_minor=None,
            expense_date=None,
            category=None,
            notes="Unparsed bill image (manual entry required)",
            raw_text="",
            total_amount=None,
            subtotal=None,
            tax=None,
            payment_mode=None,
            items=[],
            confidence={
                "merchant": 0.0,
                "date": 0.0,
                "total": 0.0,
                "items": 0.0,
                "overall": 0.0,
            },
            confidence_merchant=0.0,
            confidence_amount=0.0,
            confidence_date=0.0,
            is_draft=True,
            ocr_engine_used="none",
        )

    # Step 4: Parse extracted raw text with rule parser
    parsed = RuleParser.parse_text(raw_text, ocr_engine=engine_used)

    return ExtractedReceiptData(
        merchant=parsed.merchant,
        amount_minor=parsed.amount_minor,
        expense_date=parsed.expense_date,
        category=parsed.category,
        notes=parsed.notes,
        raw_text=parsed.raw_text,
        total_amount=parsed.total_amount,
        subtotal=parsed.subtotal,
        tax=parsed.tax,
        payment_mode=parsed.payment_mode,
        items=parsed.items,
        confidence=parsed.confidence,
        confidence_merchant=parsed.confidence.get("merchant"),
        confidence_amount=parsed.confidence.get("total"),
        confidence_date=parsed.confidence.get("date"),
        is_draft=True,
        ocr_engine_used=engine_used,
    )
