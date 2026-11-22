"""T-54 / US-16: bill review - LLM line items with a number check, warnings, image clean-up."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.ai import line_items as line_items_module
from app.ai.bill_review import build_review, format_inr
from app.ai.line_items import (
    LineItem,
    LineItemsResult,
    check_items,
    groq_line_items,
    numbers_in_text,
    rule_items,
    structure_line_items,
    to_paise,
)
from app.ai.receipt import ExtractedReceiptData
from app.core.config import settings
from app.main import app
from app.models.expense import Expense
from app.models.receipt import Receipt
from app.services import receipt_cleanup
from app.services import receipt_service as receipt_service_module
from app.services.receipt_storage import InMemoryReceiptStorage, generate_key
from tests.api.test_receipts_images import (  # noqa: F401 - pytest fixtures reused from T-46
    client,
    fake_db,
    in_memory_storage,
    make_test_jpeg,
    owner_headers,
    owner_user,
)

BILL = """CAFE MOCHA
Date: 20/11/2026
Item            Qty   Rate     Amount
Cappuccino       2   120.00   240.00
Veg Sandwich     1   150.00   150.00
Subtotal                       390.00
GST 5%                          19.50
Total                          409.50
"""

RULE_ITEMS = [
    {"item_name": "Cappuccino", "quantity": 2.0, "unit_price": 120.0, "total_price": 240.0},
    {"item_name": "Veg Sandwich", "quantity": 1.0, "unit_price": 150.0, "total_price": 150.0},
]


def llm_reply(items: list[dict[str, Any]]) -> Any:
    async def call(_text: str) -> str:
        return json.dumps({"items": items})

    return call


@pytest.fixture
def llm_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    monkeypatch.setattr(settings, "BILL_LINE_ITEMS_LLM_ENABLED", True)


def extracted(**over: Any) -> ExtractedReceiptData:
    base: dict[str, Any] = {
        "merchant": "CAFE MOCHA",
        "amount_minor": 40950,
        "expense_date": date(2026, 11, 20),
        "raw_text": BILL,
        "subtotal": 390.0,
        "items": RULE_ITEMS,
        "confidence": {"merchant": 0.9, "date": 0.9, "total": 0.95, "items": 0.92, "overall": 0.9},
        "ocr_engine_used": "ocr_space",
    }
    base.update(over)
    return ExtractedReceiptData(**base)


# ==============================================================================
# Numbers: paise, no floats
# ==============================================================================


def test_numbers_are_read_from_the_bill_as_paise():
    printed = numbers_in_text(BILL)
    assert Decimal("409.50") in printed
    assert Decimal("2.00") in printed
    assert Decimal("999.00") not in printed
    assert numbers_in_text("Grand total 1,23,456.50") >= {Decimal("123456.50")}
    assert to_paise("1,234.50") == 123450
    assert to_paise("120") == 12000
    assert to_paise("₹99.999") == 10000  # rounded half-up to the paisa
    assert to_paise("abc") is None
    assert to_paise(True) is None
    assert format_inr(12345650) == "₹1,23,456.50"


# ==============================================================================
# LLM line items: every number must be printed on the bill
# ==============================================================================


async def test_llm_items_keep_only_numbers_printed_on_the_bill(llm_on):
    call = llm_reply(
        [
            {"name": "Cappuccino", "quantity": "2", "unit_price": "120.00", "amount": "240.00"},
            {"name": "Veg Sandwich", "quantity": "3", "unit_price": "150", "amount": "150.00"},  # qty 3 not printed
            {"name": "Brownie", "amount": "95.00"},  # amount invented by the LLM -> dropped
            {"name": "", "amount": "240.00"},  # no name -> dropped
            "not an object",  # -> dropped
        ]
    )
    result = await structure_line_items(BILL, RULE_ITEMS, llm_call=call)
    assert result.source == "llm"
    assert result.dropped == 3
    assert result.items == [
        LineItem(name="Cappuccino", amount_paise=24000, quantity="2", unit_price_paise=12000),
        LineItem(name="Veg Sandwich", amount_paise=15000, quantity=None, unit_price_paise=15000),
    ]
    assert all(isinstance(i.amount_paise, int) for i in result.items)


async def test_fault_llm_timeout_falls_back_to_rule_parser_items(llm_on):
    async def times_out(_text: str) -> str:
        raise TimeoutError

    result = await structure_line_items(BILL, RULE_ITEMS, llm_call=times_out)
    assert result.source == "rules"
    assert [i.amount_paise for i in result.items] == [24000, 15000]
    assert result.items[0].quantity == "2"


async def test_fault_llm_bad_json_or_nothing_valid_falls_back(llm_on):
    async def garbage(_text: str) -> str:
        return "sure! here are the items"

    assert (await structure_line_items(BILL, RULE_ITEMS, llm_call=garbage)).source == "rules"
    only_invented = llm_reply([{"name": "Ghost", "amount": "777.00"}])
    result = await structure_line_items(BILL, RULE_ITEMS, llm_call=only_invented)
    assert result.source == "rules"
    assert result.dropped == 1


async def test_llm_switched_off_or_ai_off_uses_rules_and_never_calls_it(monkeypatch):
    async def must_not_run(_text: str) -> str:
        raise AssertionError("LLM called although switched off")

    monkeypatch.setattr(settings, "BILL_LINE_ITEMS_LLM_ENABLED", False)
    assert (await structure_line_items(BILL, RULE_ITEMS, llm_call=must_not_run)).source == "rules"
    monkeypatch.setattr(settings, "BILL_LINE_ITEMS_LLM_ENABLED", True)
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    assert (await structure_line_items(BILL, RULE_ITEMS, llm_call=must_not_run)).source == "rules"


async def test_no_text_means_no_items(llm_on):
    assert await structure_line_items("", RULE_ITEMS) == LineItemsResult()
    assert await structure_line_items(None, None) == LineItemsResult()


def test_rule_items_are_checked_too():
    assert rule_items([{"item_name": "Fake", "total_price": 55.5}], BILL) == []
    kept, dropped = check_items("nope", BILL)
    assert (kept, dropped) == ([], 0)


async def test_fault_groq_call_has_a_timeout_and_returns_none(monkeypatch):
    def slow(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key-placeholder")
    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as http:
        assert await groq_line_items(BILL, http_client=http) is None

    def ok(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"items": []}'}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(ok)) as http:
        assert await groq_line_items(BILL, http_client=http) == '{"items": []}'

    monkeypatch.setattr(settings, "GROQ_API_KEY", None)
    assert await groq_line_items(BILL) is None  # no key: no outside call at all


# ==============================================================================
# Review warnings and highlighted fields
# ==============================================================================

TODAY = date(2026, 11, 22)


def test_clean_bill_has_no_warnings():
    review = build_review(extracted(), LineItemsResult(items=rule_items(RULE_ITEMS, BILL), source="rules"), today=TODAY)
    assert review.warnings == []
    assert review.low_confidence_fields == []
    assert review.amount_paise == 40950  # items match the subtotal, so no "doesn't add up"


def test_unreadable_bill_asks_for_manual_entry():
    review = build_review(extracted(raw_text="", ocr_engine_used="none"), LineItemsResult(), today=TODAY)
    assert [w.code for w in review.warnings] == ["NO_TEXT"]
    assert review.low_confidence_fields == ["amount", "date", "merchant"]
    assert review.amount_paise is None


def test_missing_and_doubtful_fields_are_highlighted():
    review = build_review(
        extracted(amount_minor=None, expense_date=None, merchant="  ", items=[]),
        LineItemsResult(),
        today=TODAY,
    )
    assert {w.code for w in review.warnings} == {"TOTAL_NOT_FOUND", "DATE_NOT_FOUND", "MERCHANT_NOT_FOUND"}
    assert set(review.low_confidence_fields) == {"amount", "date", "merchant"}

    doubtful = build_review(
        extracted(confidence={"merchant": 0.3, "date": 0.5, "total": 0.4}), LineItemsResult(), today=TODAY
    )
    assert [w.code for w in doubtful.warnings] == ["LOW_CONFIDENCE"] * 3
    assert doubtful.low_confidence_fields == ["amount", "date", "merchant"]


def test_unusual_dates_are_flagged():
    future = build_review(extracted(expense_date=date(2026, 12, 1)), LineItemsResult(), today=TODAY)
    assert [w.code for w in future.warnings] == ["DATE_IN_FUTURE"]
    old = build_review(extracted(expense_date=date(2025, 1, 1)), LineItemsResult(), today=TODAY)
    assert [w.code for w in old.warnings] == ["DATE_OLD"]


def test_items_that_do_not_add_up_and_dropped_items_are_flagged():
    items = [LineItem(name="Cappuccino", amount_paise=24000)]
    review = build_review(
        extracted(subtotal=None), LineItemsResult(items=items, source="llm", dropped=2), today=TODAY
    )
    codes = [w.code for w in review.warnings]
    assert codes == ["ITEMS_DROPPED", "ITEMS_DONT_ADD_UP"]
    assert "₹240.00" in review.warnings[1].message and "₹409.50" in review.warnings[1].message
    assert review.low_confidence_fields == ["items", "amount"]


# ==============================================================================
# Scan endpoint returns the review draft
# ==============================================================================


async def test_scan_returns_paise_items_warnings_and_is_a_draft(
    client, owner_headers, fake_db, in_memory_storage, monkeypatch  # noqa: F811
):
    async def fake_extract(_bytes: bytes, **_: Any) -> ExtractedReceiptData:
        return extracted(confidence={"merchant": 0.9, "date": 0.4, "total": 0.95})

    monkeypatch.setattr(receipt_service_module, "extract_receipt_data", fake_extract)
    monkeypatch.setattr(settings, "BILL_LINE_ITEMS_LLM_ENABLED", True)
    monkeypatch.setattr(
        line_items_module,
        "groq_line_items",
        llm_reply([{"name": "Cappuccino", "quantity": "2", "unit_price": "120.00", "amount": "240.00"},
                   {"name": "Mystery", "amount": "12.34"}]),
    )
    files = {"file": ("bill.jpg", make_test_jpeg(300, 250), "image/jpeg")}
    res = await client.post("/api/v1/receipts/scan", headers=owner_headers, files=files)
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["isDraft"] is True
    assert data["amountPaise"] == 40950 and data["amountMinor"] == 40950
    assert data["itemsSource"] == "llm"
    assert data["items"] == [{"name": "Cappuccino", "amountPaise": 24000, "quantity": "2", "unitPricePaise": 12000}]
    codes = [w["code"] for w in data["warnings"]]
    assert "ITEMS_DROPPED" in codes and "LOW_CONFIDENCE" in codes
    assert "date" in data["lowConfidenceFields"]
    # Scanning never creates an expense: only the receipt row exists, unlinked.
    assert fake_db.expenses == {}
    assert all(r.expense_id is None for r in fake_db.receipts.values())


# ==============================================================================
# Clean-up: bill image deleted along with the expense
# ==============================================================================


class _Rows:
    def __init__(self, rows: list[tuple[Receipt, Expense]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Receipt, Expense]]:
        return self._rows


class CleanupSession:
    """Answers the clean-up query with preset rows and records the order of events."""

    def __init__(self, rows: list[tuple[Receipt, Expense]], events: list[str]) -> None:
        self.rows = rows
        self.events = events
        self.deleted: list[Any] = []
        self.statement = ""

    async def execute(self, stmt: Any) -> _Rows:
        self.statement = str(stmt).lower()
        return _Rows(self.rows)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def commit(self) -> None:
        self.events.append("commit")


class RecordingStorage(InMemoryReceiptStorage):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    async def delete(self, key: str) -> None:
        self.events.append(f"delete:{key}")
        await super().delete(key)


def _expense_with_receipt(deleted_hours_ago: float | None) -> tuple[Receipt, Expense]:
    now = datetime.now(UTC)
    receipt_id, expense_id = uuid.uuid4(), uuid.uuid4()
    receipt = Receipt(
        id=receipt_id, user_id=uuid.uuid4(), expense_id=expense_id, storage_key=generate_key(),
        content_type="image/jpeg", file_size=10, created_at=now - timedelta(days=3),
    )
    expense = Expense(
        id=expense_id, user_id=receipt.user_id, category_id=uuid.uuid4(), amount_minor=100,
        description="Lunch", receipt_id=receipt_id, version=2,
        deleted_at=None if deleted_hours_ago is None else now - timedelta(hours=deleted_hours_ago),
    )
    return receipt, expense


async def test_deleted_expense_loses_its_bill_image_after_the_db_commit():
    events: list[str] = []
    storage = RecordingStorage(events)
    receipt, expense = _expense_with_receipt(deleted_hours_ago=30)
    await storage.put(receipt.storage_key, b"jpeg", "image/jpeg")
    session = CleanupSession([(receipt, expense)], events)

    count = await receipt_cleanup.purge_deleted_expense_receipts(session, storage=storage, older_than_hours=24)

    assert count == 1
    assert session.deleted == [receipt]
    assert expense.receipt_id is None  # the soft-deleted expense no longer points at it
    assert events == ["commit", f"delete:{receipt.storage_key}"]  # files only after the commit
    assert await storage.get(receipt.storage_key) is None
    assert "deleted_at is not null" in session.statement and "deleted_at <=" in session.statement


async def test_nothing_to_clean_means_no_commit():
    events: list[str] = []
    session = CleanupSession([], events)
    assert await receipt_cleanup.purge_deleted_expense_receipts(session, storage=RecordingStorage(events)) == 0
    assert events == []


async def test_a_failing_file_delete_does_not_break_the_run():
    events: list[str] = []

    class BrokenStorage(RecordingStorage):
        async def delete(self, key: str) -> None:
            raise RuntimeError("bucket down")

    receipt, expense = _expense_with_receipt(deleted_hours_ago=48)
    session = CleanupSession([(receipt, expense)], events)
    assert await receipt_cleanup.purge_deleted_expense_receipts(session, storage=BrokenStorage(events)) == 1
    assert events == ["commit"]


async def test_cleanup_loop_survives_errors_and_lifespan_starts_and_stops_it(monkeypatch):
    runs = 0

    async def flaky(now: datetime | None = None) -> receipt_cleanup.CleanupStats:
        nonlocal runs
        runs += 1
        if runs == 1:
            raise RuntimeError("database down")
        return receipt_cleanup.CleanupStats()

    monkeypatch.setattr(receipt_cleanup, "run_cleanup", flaky)
    task = receipt_cleanup.start_cleanup(interval_seconds=0.01)
    async with asyncio.timeout(2):
        while runs < 3:
            await asyncio.sleep(0.01)
    await receipt_cleanup.stop_cleanup(task)
    assert task.done()

    started = asyncio.Event()

    async def first_run(now: datetime | None = None) -> receipt_cleanup.CleanupStats:
        started.set()
        return receipt_cleanup.CleanupStats()

    async def no_history() -> int:
        return 0

    import app.main as main_module

    monkeypatch.setattr(main_module, "restore_user_history", no_history)
    monkeypatch.setattr(receipt_cleanup, "run_cleanup", first_run)
    monkeypatch.setattr(settings, "RECEIPT_CLEANUP_ENABLED", True)
    async with asyncio.timeout(5), app.router.lifespan_context(app):
        await asyncio.wait_for(started.wait(), 2)


async def test_cleanup_disabled_starts_nothing(monkeypatch):
    def must_not_start(*_a: Any, **_k: Any) -> None:
        raise AssertionError("clean-up started although disabled")

    async def no_history() -> int:
        return 0

    import app.main as main_module

    monkeypatch.setattr(main_module, "restore_user_history", no_history)
    monkeypatch.setattr(receipt_cleanup, "start_cleanup", must_not_start)
    async with app.router.lifespan_context(app):
        pass
