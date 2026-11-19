"""Receipt Information Extraction Service Stub (US-16).

Owned by Parthiv Panchal (S2-AI-03).
Provides an interface and stub for extracting fields from processed receipt images.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ExtractedReceiptData:
    """Fields extracted from bill image by LLM/OCR."""

    merchant: str | None = None
    amount_minor: int | None = None
    expense_date: date | None = None
    category: str | None = None
    notes: str | None = None
    raw_text: str | None = None


async def extract_receipt_data(image_bytes: bytes) -> ExtractedReceiptData:
    """Extraction stub receiving normalized image bytes and returning initial empty result.

    Parthiv will replace this with full LLM/OCR extraction in S2-AI-03.
    """
    return ExtractedReceiptData()
