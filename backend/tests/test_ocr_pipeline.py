"""Unit and Integration Tests for Bill OCR Pipeline (US-16 / T-47).

Covers:
1. OCR.space client (success, timeout, API error recovery)
2. Tesseract local reader fallback (success, timeout, missing binary recovery)
3. Live drill: OCR.space disabled -> Tesseract fallback; both disabled -> safe empty draft
4. Rule parser field extraction: date, merchant, total, line items, and confidence per field
5. Draft expense guarantees: pre-filled form with is_draft=True (nothing saved without Confirm)
"""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.ocr_space import extract_text_ocr_space
from app.ai.receipt import ExtractedReceiptData, extract_receipt_data
from app.ai.rule_parser import RuleParser
from app.ai.tesseract import extract_text_tesseract


# =====================================================================
# 1. OCR.space Client Tests
# =====================================================================


@pytest.mark.anyio
async def test_ocr_space_success() -> None:
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "ParsedResults": [{"ParsedText": "HALDIRAM EXPRESS\nTotal: 546.00"}],
        "IsErroredOnProcessing": False,
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = fake_response

    text = await extract_text_ocr_space(
        b"fake_image_bytes",
        api_key="test_key",
        timeout_seconds=2.0,
        client=mock_client,
    )
    assert text == "HALDIRAM EXPRESS\nTotal: 546.00"


@pytest.mark.anyio
async def test_ocr_space_timeout_returns_none() -> None:
    import httpx

    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.TimeoutException("Connection timed out")

    text = await extract_text_ocr_space(
        b"fake_image_bytes",
        api_key="test_key",
        timeout_seconds=0.1,
        client=mock_client,
    )
    assert text is None


@pytest.mark.anyio
async def test_ocr_space_api_error_returns_none() -> None:
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "IsErroredOnProcessing": True,
        "ErrorMessage": "Invalid file format",
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = fake_response

    text = await extract_text_ocr_space(
        b"fake_image_bytes",
        client=mock_client,
    )
    assert text is None


# =====================================================================
# 2. Tesseract Fallback Engine Tests
# =====================================================================


@pytest.mark.anyio
async def test_tesseract_success() -> None:
    with patch("app.ai.tesseract._run_tesseract_sync", return_value="APOLLO PHARMACY\nTotal: 504.00"):
        text = await extract_text_tesseract(b"fake_image_bytes", timeout_seconds=1.0)
        assert text == "APOLLO PHARMACY\nTotal: 504.00"


@pytest.mark.anyio
async def test_tesseract_timeout_returns_none() -> None:
    def slow_tesseract(*args, **kwargs):
        import time
        time.sleep(1.0)
        return "too late"

    with patch("app.ai.tesseract._run_tesseract_sync", side_effect=slow_tesseract):
        text = await extract_text_tesseract(b"fake_image_bytes", timeout_seconds=0.1)
        assert text is None


@pytest.mark.anyio
async def test_tesseract_missing_binary_returns_none() -> None:
    with patch("shutil.which", return_value=None), patch.dict("sys.modules", {"pytesseract": None}):
        text = await extract_text_tesseract(b"fake_image_bytes", timeout_seconds=0.5)
        assert text is None


# =====================================================================
# 3. Live Drill: Fallback Architecture & Switch Off Tests
# =====================================================================


@pytest.mark.anyio
async def test_live_drill_ocr_space_primary() -> None:
    """When OCR.space succeeds, primary cloud reader is used."""
    with patch("app.ai.receipt.extract_text_ocr_space", return_value="DOMINOS PIZZA\nDate: 18/09/2026\nTotal: 837.90"), \
         patch("app.ai.receipt.extract_text_tesseract") as mock_tess:
        data = await extract_receipt_data(b"fake_bytes", ocr_space_enabled=True)
        assert data.ocr_engine_used == "ocr_space"
        assert data.merchant == "Dominos Pizza"
        assert data.total_amount == 837.90
        assert data.amount_minor == 83790
        assert data.is_draft is True
        mock_tess.assert_not_called()


@pytest.mark.anyio
async def test_live_drill_ocr_space_fails_falls_back_to_tesseract() -> None:
    """When OCR.space fails or times out, local Tesseract takes over."""
    with patch("app.ai.receipt.extract_text_ocr_space", return_value=None), \
         patch("app.ai.receipt.extract_text_tesseract", return_value="CHAI POINT\nDate: 29/09/2026\nTOTAL DUE: 267.75"):
        data = await extract_receipt_data(b"fake_bytes", ocr_space_enabled=True, tesseract_enabled=True)
        assert data.ocr_engine_used == "tesseract"
        assert data.merchant == "Chai Point"
        assert data.total_amount == 267.75
        assert data.expense_date == date(2026, 9, 29)
        assert data.is_draft is True


@pytest.mark.anyio
async def test_live_drill_both_switched_off_returns_empty_draft() -> None:
    """Switch both off: form opens empty with draft=True and image safely kept."""
    data = await extract_receipt_data(
        b"fake_bytes",
        ocr_space_enabled=False,
        tesseract_enabled=False,
    )
    assert data.ocr_engine_used == "none"
    assert data.is_draft is True
    assert data.merchant is None
    assert data.amount_minor is None
    assert data.expense_date is None
    assert data.confidence["overall"] == 0.0
    assert "Unparsed bill image" in data.notes


# =====================================================================
# 4. Rule Parser Tests: Total, Date, Merchant, Items, Confidences
# =====================================================================


def test_rule_parser_dates() -> None:
    # DD/MM/YYYY
    p1 = RuleParser.parse_text("Starbucks\nDate: 21/09/2026\nTOTAL: INR 724.50")
    assert p1.expense_date == date(2026, 9, 21)
    assert p1.confidence["date"] >= 0.90

    # YYYY-MM-DD
    p2 = RuleParser.parse_text("Store\nBill Date: 2026-10-02\nGrand Total: 1869.00")
    assert p2.expense_date == date(2026, 10, 2)

    # Textual month
    p3 = RuleParser.parse_text("Store\nDate: 15 Sep 2026\nTOTAL AMOUNT: 2000.00")
    assert p3.expense_date == date(2026, 9, 15)


def test_rule_parser_totals_and_paise_conversion() -> None:
    # Check that Subtotal is not confused with Grand Total
    text = (
        "HALDIRAM EXPRESS\n"
        "Date: 15/09/2026\n"
        "Subtotal: 520.00\n"
        "CGST: 13.00\n"
        "SGST: 13.00\n"
        "TOTAL AMOUNT PAYABLE: INR 546.00\n"
    )
    parsed = RuleParser.parse_text(text)
    assert parsed.subtotal == 520.00
    assert parsed.tax == 13.00
    assert parsed.total_amount == 546.00
    assert parsed.amount_minor == 54600  # 546 * 100 paise
    assert parsed.confidence["total"] >= 0.95


def test_rule_parser_items_extraction() -> None:
    text = (
        "DMART SUPERMARKET\n"
        "Date: 14/09/2026\n"
        "--------------------------------------------------\n"
        "Item Description              Qty   Rate    Amount\n"
        "--------------------------------------------------\n"
        "Aashirvaad Atta 5kg            1   245.00   245.00\n"
        "Fortune Sunflower Oil 1L       2   140.00   280.00\n"
        "--------------------------------------------------\n"
        "NET AMOUNT DUE: INR 525.00\n"
    )
    parsed = RuleParser.parse_text(text)
    assert len(parsed.items) == 2
    assert parsed.items[0]["item_name"] == "Aashirvaad Atta 5kg"
    assert parsed.items[0]["quantity"] == 1.0
    assert parsed.items[0]["unit_price"] == 245.00
    assert parsed.items[0]["total_price"] == 245.00
    assert parsed.confidence["items"] >= 0.90


def test_rule_parser_field_confidences() -> None:
    text = "APOLLO PHARMACY\nDate: 16/09/2026\nNET AMOUNT PAYABLE: INR 504.00"
    parsed = RuleParser.parse_text(text)
    assert "merchant" in parsed.confidence
    assert "date" in parsed.confidence
    assert "total" in parsed.confidence
    assert "overall" in parsed.confidence
    for k, score in parsed.confidence.items():
        assert 0.0 <= score <= 1.0
    assert parsed.is_draft is True
