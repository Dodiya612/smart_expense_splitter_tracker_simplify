"""Performance and Latency benchmark for local Category Suggestion pipeline.

Verifies Non-Functional Requirement (NFR):
- Local inference pipeline p95 latency < 300 ms.
- Excludes external Groq LLM network latency.
- Tests 100+ requests across diverse realistic Indian expense descriptions.
"""

from __future__ import annotations

import statistics
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from app.models.category import Category
from app.schemas.category_suggestion import CategorySuggestionRequest
from app.services.category_suggestion_service import (
    get_category_classifier,
    get_user_history_layer,
    suggest_category,
)
from app.services.groq_client import CANONICAL_CATEGORIES, GroqClient


class BenchmarkDB:
    def __init__(self) -> None:
        self.categories: list[Category] = [
            Category(
                id=uuid.UUID(f"00000000-0000-4000-8000-{idx:012d}"),
                name=name,
                is_default=True,
                owner_id=None,
                created_at=datetime.now(UTC),
            )
            for idx, name in enumerate(CANONICAL_CATEGORIES, start=1)
        ]

    async def execute(self, stmt: Any) -> Any:
        class FakeScalars:
            def __init__(self, items: list[Any]) -> None:
                self._items = items

            def all(self) -> list[Any]:
                return list(self._items)

        class FakeResult:
            def __init__(self, items: list[Any]) -> None:
                self._items = items

            def scalars(self) -> FakeScalars:
                return FakeScalars(self._items)

        return FakeResult(self.categories)


BENCHMARK_TRANSACTIONS = [
    ("Starbucks iced latte", "Starbucks"),
    ("Uber ride to office", "Uber"),
    ("Swiggy food delivery lunch", "Swiggy"),
    ("Zomato dinner with friends", "Zomato"),
    ("Blinkit vegetables milk bread", "Blinkit"),
    ("Netflix monthly subscription", "Netflix"),
    ("Electricity bill payment BESCOM", "BESCOM"),
    ("Amazon purchase bluetooth speaker", "Amazon"),
    ("Apollo pharmacy medicine syrup", "Apollo"),
    ("Room rent monthly PG transfer", "Owner"),
    ("Flight ticket booking Indigo", "Indigo"),
    ("Haircut and beard trim salon", "Enrich"),
    ("Coursera annual subscription", "Coursera"),
    ("Birthday gift watch for brother", "Titan"),
    ("Petrol fuel shell station", "Shell"),
    ("Grocery staples dmart", "DMart"),
    ("Movie tickets PVR IMAX", "BookMyShow"),
    ("Gym membership Gold's Gym", "Gold's Gym"),
    ("Metro card smart recharge", "DMRC"),
    ("Broadband internet bill Airtel", "Airtel"),
]


@pytest.mark.anyio
async def test_local_path_latency_p95_under_300ms() -> None:
    """Benchmark local ML + history path over 100 requests to measure p50, p95, p99."""
    db = BenchmarkDB()
    user_id = uuid.uuid4()
    classifier = get_category_classifier()
    history_layer = get_user_history_layer()

    # Pre-populate some user history
    for _ in range(3):
        history_layer.record_transaction(str(user_id), "Food & Dining", "Starbucks")
        history_layer.record_transaction(str(user_id), "Travel & Transport", "Uber")

    # Groq client with no API key ensuring strictly local path
    groq_offline = GroqClient(api_key=None)

    # 1. Warm-up (5 requests)
    for desc, merch in BENCHMARK_TRANSACTIONS[:5]:
        req = CategorySuggestionRequest(description=desc, merchant=merch)
        await suggest_category(
            db=db,  # type: ignore[arg-type]
            user_id=user_id,
            req=req,
            classifier=classifier,
            history_layer=history_layer,
            groq_client=groq_offline,
        )

    # 2. Benchmark execution (100 requests)
    latencies_ms: list[float] = []
    total_runs = 100

    for i in range(total_runs):
        desc, merch = BENCHMARK_TRANSACTIONS[i % len(BENCHMARK_TRANSACTIONS)]
        req = CategorySuggestionRequest(description=desc, merchant=merch)

        start_time = time.perf_counter()
        res = await suggest_category(
            db=db,  # type: ignore[arg-type]
            user_id=user_id,
            req=req,
            classifier=classifier,
            history_layer=history_layer,
            groq_client=groq_offline,
        )
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        latencies_ms.append(elapsed_ms)
        assert res.suggested_category_id is not None

    latencies_ms.sort()
    p50 = latencies_ms[int(total_runs * 0.50)]
    p95 = latencies_ms[int(total_runs * 0.95)]
    p99 = latencies_ms[int(total_runs * 0.99)]
    mean_val = statistics.mean(latencies_ms)
    min_val = min(latencies_ms)
    max_val = max(latencies_ms)

    print(
        f"\n--- LATENCY BENCHMARK RESULTS (N={total_runs}) ---\n"
        f"  Min:  {min_val:.3f} ms\n"
        f"  p50:  {p50:.3f} ms\n"
        f"  Mean: {mean_val:.3f} ms\n"
        f"  p95:  {p95:.3f} ms\n"
        f"  p99:  {p99:.3f} ms\n"
        f"  Max:  {max_val:.3f} ms\n"
        f"------------------------------------------------"
    )

    # NFR verification
    assert p95 < 300.0, f"Expected p95 < 300 ms, got {p95:.2f} ms"
    assert p50 < 50.0, f"Expected p50 < 50 ms, got {p50:.2f} ms"
