"""AI package for Coinscious backend.

Contains quota enforcement, usage logging, receipt OCR extraction, and provider orchestrations.
"""

from __future__ import annotations

try:
    from app.ai.quota import (
        AIQuotaService,
        QuotaStatus,
        check_quota,
        get_quota_service,
        log_ai_usage,
    )
except ImportError:
    pass

from app.ai.receipt import ExtractedReceiptData, extract_receipt_data

__all__ = [
    "AIQuotaService",
    "QuotaStatus",
    "check_quota",
    "get_quota_service",
    "log_ai_usage",
    "ExtractedReceiptData",
    "extract_receipt_data",
]
