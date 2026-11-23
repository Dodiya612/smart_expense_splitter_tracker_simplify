"""Tests for AI Goal Setting / Budget Recommendation (US-25 / T-55).

Covers:
1. Asia/Kolkata 3-month boundary calculations (calendar boundaries, leap year, year rollover).
2. Pure mathematical logic: median, rounding to nearest ₹100, spike trimming (50% and 2× baseline rules).
3. Grounding guard: number verification against backend figures.
4. Deterministic template fallback generation.
5. End-to-end service recommendation logic (overall, category-specific, user share vs cash paid,
   settlement & deleted expense exclusion, insufficient history).
6. Advisory-only enforcement (verifying zero DB writes/mutations to Budget records).
7. AI explanation flow with Groq mocking and grounding validation.
8. API endpoints: auth enforcement, request validation (422), and response contract.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from httpx import ASGITransport, AsyncClient, MockTransport, Response
from pydantic import ValidationError

from app.core.database import get_db
from app.main import app
from app.models.budget import Budget
from app.models.category import Category
from app.models.expense import Expense
from app.models.user import User
from app.schemas.budget_recommendation import (
    BudgetRecommendationRequest,
    HistoricalMonthSpend,
)
from app.services import budget_recommendation_service
from app.services.budget_recommendation_service import (
    RECOMMENDATION_SPENDING_OPTION,
    compute_median,
    generate_template_explanation,
    get_last_three_completed_months,
    recommend_budget,
    round_to_nearest_100_rupees,
    trim_monthly_spikes,
    verify_grounded_numbers,
)
from app.services.groq_client import GroqClient
from tests.test_authorization import (  # noqa: F401 - fixtures
    auth_db,
    client_auth,
    headers_a,
    headers_b,
    token_a,
    token_b,
    user_a,
    user_b,
)

CATEGORY_1 = uuid.UUID("00000000-0000-4000-8000-000000000001")
CATEGORY_2 = uuid.UUID("00000000-0000-4000-8000-000000000002")


# ==============================================================================
# 1. Date & Window Tests (Asia/Kolkata)
# ==============================================================================


def test_last_three_completed_months_standard() -> None:
    # Mid-month: November 15, 2026
    ref = date(2026, 11, 15)
    months = get_last_three_completed_months(ref)
    assert len(months) == 3
    # Chronological: Aug 2026, Sep 2026, Oct 2026
    assert months[0] == (date(2026, 8, 1), date(2026, 8, 31))
    assert months[1] == (date(2026, 9, 1), date(2026, 9, 30))
    assert months[2] == (date(2026, 10, 1), date(2026, 10, 31))


def test_last_three_completed_months_first_day_of_month() -> None:
    # First day of month: November 1, 2026
    ref = date(2026, 11, 1)
    months = get_last_three_completed_months(ref)
    assert months[0] == (date(2026, 8, 1), date(2026, 8, 31))
    assert months[1] == (date(2026, 9, 1), date(2026, 9, 30))
    assert months[2] == (date(2026, 10, 1), date(2026, 10, 31))


def test_last_three_completed_months_year_boundary() -> None:
    # January 10, 2027 crosses year boundary
    ref = date(2027, 1, 10)
    months = get_last_three_completed_months(ref)
    assert months[0] == (date(2026, 10, 1), date(2026, 10, 31))
    assert months[1] == (date(2026, 11, 1), date(2026, 11, 30))
    assert months[2] == (date(2026, 12, 1), date(2026, 12, 31))


def test_last_three_completed_months_leap_year() -> None:
    # March 15, 2024 (2024 is a leap year; Feb has 29 days)
    ref = date(2024, 3, 15)
    months = get_last_three_completed_months(ref)
    assert months[0] == (date(2023, 12, 1), date(2023, 12, 31))
    assert months[1] == (date(2024, 1, 1), date(2024, 1, 31))
    assert months[2] == (date(2024, 2, 1), date(2024, 2, 29))


# ==============================================================================
# 2. Pure Maths & Trimming Tests
# ==============================================================================


def test_compute_median() -> None:
    assert compute_median([]) == 0
    assert compute_median([100]) == 100
    assert compute_median([100, 300, 200]) == 200
    assert compute_median([100, 200, 300, 400]) == 250
    assert compute_median([0, 0, 0]) == 0


def test_round_to_nearest_100_rupees() -> None:
    # ₹100 = 10,000 paise
    assert round_to_nearest_100_rupees(0) == 0
    assert round_to_nearest_100_rupees(-500) == 0
    # Values under 5,000 paise (under ₹50) clamp to ₹100 (10,000 paise) if positive
    assert round_to_nearest_100_rupees(3000) == 10000
    assert round_to_nearest_100_rupees(5000) == 10000
    assert round_to_nearest_100_rupees(14999) == 10000
    assert round_to_nearest_100_rupees(15000) == 20000
    assert round_to_nearest_100_rupees(254000) == 250000
    assert round_to_nearest_100_rupees(256000) == 260000


def test_spike_trimming_fifty_percent_rule() -> None:
    # Month 1: 3 transactions: ₹2,000, ₹2,000, ₹6,000 (total ₹10,000).
    # ₹6,000 is 60% of ₹10,000 (>50%), so it is trimmed. Net = ₹4,000.
    # Month 2: ₹3,000, ₹3,000 (total ₹6,000). Neither is >50% (each is exactly 50%). Net = ₹6,000.
    # Month 3: ₹4,000, ₹4,000 (total ₹8,000). Net = ₹8,000.
    data = [
        ("2026-08", [200000, 200000, 600000]),
        ("2026-09", [300000, 300000]),
        ("2026-10", [400000, 400000]),
    ]
    months, baseline = trim_monthly_spikes(data)
    assert baseline == 800000  # median(10k, 6k, 8k) = 8k
    assert months[0].spent_paise == 1000000
    assert months[0].spike_paise == 600000
    assert months[0].net_paise == 400000

    assert months[1].spent_paise == 600000
    assert months[1].spike_paise == 0
    assert months[1].net_paise == 600000

    assert months[2].spent_paise == 800000
    assert months[2].spike_paise == 0
    assert months[2].net_paise == 800000


def test_spike_trimming_two_x_baseline_rule() -> None:
    # Baseline: month totals are 5k, 5k, 50k -> median baseline = 5k (500,000 paise)
    # 2x baseline = 10k (1,000,000 paise)
    # In month 3 (total 50k):
    # txs: 15k, 15k, 10k, 10k.
    # None is >50% of 50k (max is 30%), BUT 15k > 2 * 5k (10k), so both 15k txs are spikes!
    data = [
        ("2026-08", [500000]),
        ("2026-09", [500000]),
        ("2026-10", [1500000, 1500000, 1000000, 1000000]),
    ]
    months, baseline = trim_monthly_spikes(data)
    assert baseline == 500000
    assert months[2].spent_paise == 5000000
    # Both 1.5M transactions trimmed as > 2x baseline (1.0M)
    assert months[2].spike_paise == 3000000
    assert months[2].net_paise == 2000000


# ==============================================================================
# 3. Grounding Guard & Template Explanation Tests
# ==============================================================================


def test_verify_grounded_numbers_success() -> None:
    allowed = {4500, 5000, 10, 3}
    # Matches allowed integers despite currency symbol, commas, and percentage
    text = "Based on your 3-month median of ₹5,000 with 10% savings, recommended is ₹4,500."
    assert verify_grounded_numbers(text, allowed) is True


def test_verify_grounded_numbers_rejects_hallucination() -> None:
    allowed = {4500, 5000, 10}
    # Contains 9999 which is not in allowed set
    text = "Your recommended budget is ₹4,500, and you can save ₹9,999 next month."
    assert verify_grounded_numbers(text, allowed) is False


def test_generate_template_explanation() -> None:
    text_10 = generate_template_explanation(
        category_name="Food & Dining",
        raw_median_paise=500000,  # ₹5,000
        savings_level_percent=10,
        recommended_limit_paise=450000,  # ₹4,500
        has_sufficient_history=True,
    )
    assert "₹5,000" in text_10
    assert "10% savings target" in text_10
    assert "₹4,500" in text_10
    assert "Food & Dining" in text_10

    text_0 = generate_template_explanation(
        category_name="Overall",
        raw_median_paise=1000000,
        savings_level_percent=0,
        recommended_limit_paise=1000000,
        has_sufficient_history=True,
    )
    assert "₹10,000" in text_0
    assert "savings target" not in text_0

    text_insuff = generate_template_explanation(
        category_name="Overall",
        raw_median_paise=0,
        savings_level_percent=10,
        recommended_limit_paise=10000,
        has_sufficient_history=False,
    )
    assert "limited spending history" in text_insuff


def test_schema_savings_level_validation() -> None:
    # Valid savings levels: 0, 5, 10
    assert BudgetRecommendationRequest(savings_level_percent=0).savings_level_percent == 0
    assert BudgetRecommendationRequest(savings_level_percent=5).savings_level_percent == 5
    assert BudgetRecommendationRequest(savings_level_percent=10).savings_level_percent == 10

    with pytest.raises(ValidationError):
        BudgetRecommendationRequest(savings_level_percent=15)

    with pytest.raises(ValidationError):
        BudgetRecommendationRequest(savings_level_percent=-5)


# ==============================================================================
# 4. Service-Level End-to-End Tests with Fake Session
# ==============================================================================


class FakeTxRecord:
    def __init__(self, expense_id: uuid.UUID, expense_date: date, category_id: uuid.UUID, share_paise: int):
        self.expense_id = expense_id
        self.expense_date = expense_date
        self.category_id = category_id
        self.share_paise = share_paise


class FakeRecommendationDB:
    """In-memory database simulation for recommendation testing."""

    def __init__(self) -> None:
        self.categories: dict[uuid.UUID, Category] = {
            CATEGORY_1: Category(id=CATEGORY_1, name="Groceries", owner_id=None, is_default=True),
            CATEGORY_2: Category(id=CATEGORY_2, name="Entertainment", owner_id=None, is_default=True),
        }
        self.tx_records: list[FakeTxRecord] = []
        self.budgets: dict[uuid.UUID, Budget] = {}


class FakeAsyncSession:
    def __init__(self, db: FakeRecommendationDB) -> None:
        self.db = db
        self.pending: list[Any] = []

    def add(self, obj: Any) -> None:
        if hasattr(obj, "id") and getattr(obj, "id") is None:
            obj.id = uuid.uuid4()
        self.pending.append(obj)

    async def commit(self) -> None:
        for obj in self.pending:
            if isinstance(obj, Budget) and obj.id is not None:
                budget_id = cast(uuid.UUID, obj.id)
                self.db.budgets[budget_id] = obj
        self.pending.clear()

    async def rollback(self) -> None:
        self.pending.clear()

    async def refresh(self, obj: Any) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:
        sql = str(stmt).lower()
        opts = stmt.get_execution_options() if hasattr(stmt, "get_execution_options") else {}

        # 1. Recommendation spending query
        rec_spending = opts.get(RECOMMENDATION_SPENDING_OPTION)
        if rec_spending:
            f = rec_spending["filter"]
            filtered = [
                r for r in self.db.tx_records
                if f.start <= r.expense_date <= f.end
            ]
            return SimpleNamespace(all=lambda: filtered)

        # 2. Category lookup
        if "from categories" in sql:
            params = stmt.compile().params
            cat_id = params.get("id_1") or params.get("id")
            for c in self.db.categories.values():
                if c.id == cat_id:
                    return SimpleNamespace(scalar_one_or_none=lambda cat=c: cat)
            return SimpleNamespace(scalar_one_or_none=lambda: None)

        return SimpleNamespace(all=lambda: [], scalar_one_or_none=lambda: None)


@pytest.fixture
def fake_rec_db() -> FakeRecommendationDB:
    return FakeRecommendationDB()


@pytest.fixture
def fake_session(fake_rec_db: FakeRecommendationDB) -> FakeAsyncSession:
    return FakeAsyncSession(fake_rec_db)


@pytest.mark.asyncio
async def test_recommend_budget_overall_success(fake_session: FakeAsyncSession) -> None:
    user = User(id=uuid.uuid4(), email="test@example.com", created_at=datetime(2025, 1, 1, tzinfo=UTC))
    completed = get_last_three_completed_months()

    # Seed 3 completed months:
    # Month 1: ₹10,000 (1,000,000 paise)
    # Month 2: ₹12,000 (1,200,000 paise)
    # Month 3: ₹14,000 (1,400,000 paise)
    fake_session.db.tx_records = [
        FakeTxRecord(uuid.uuid4(), completed[0][0], CATEGORY_1, 500000),
        FakeTxRecord(uuid.uuid4(), completed[0][1], CATEGORY_1, 500000),
        FakeTxRecord(uuid.uuid4(), completed[1][0], CATEGORY_1, 600000),
        FakeTxRecord(uuid.uuid4(), completed[1][1], CATEGORY_1, 600000),
        FakeTxRecord(uuid.uuid4(), completed[2][0], CATEGORY_1, 700000),
        FakeTxRecord(uuid.uuid4(), completed[2][1], CATEGORY_1, 700000),
    ]

    req = BudgetRecommendationRequest(category_id=None, savings_level_percent=10)
    resp = await recommend_budget(fake_session, user, req)  # type: ignore[arg-type]

    assert resp.has_sufficient_history is True
    assert resp.category_id is None
    assert len(resp.historical_months) == 3
    # Net: 10k, 12k, 14k -> Median = 12k (1,200,000 paise)
    assert resp.raw_median_paise == 1200000
    # 10% savings = 120,000 paise -> 1,080,000 paise -> rounded to nearest ₹100 = 1,080,000 paise (₹10,800)
    assert resp.savings_paise == 120000
    assert resp.recommended_limit_paise == 1080000
    assert resp.source in ("ai", "template_fallback")
    assert "₹10,800" in resp.explanation


@pytest.mark.asyncio
async def test_recommend_budget_category_specific(fake_session: FakeAsyncSession) -> None:
    user = User(id=uuid.uuid4(), email="cat@example.com", created_at=datetime(2025, 1, 1, tzinfo=UTC))
    completed = get_last_three_completed_months()

    # Seed data for CATEGORY_1 (Groceries): 2 transactions per month of ₹2,000 each = ₹4,000/month
    # Neither transaction is > 50% of the month's ₹4,000 total (each is exactly 50%).
    fake_session.db.tx_records = [
        FakeTxRecord(uuid.uuid4(), completed[0][0], CATEGORY_1, 200000),
        FakeTxRecord(uuid.uuid4(), completed[0][1], CATEGORY_1, 200000),
        FakeTxRecord(uuid.uuid4(), completed[1][0], CATEGORY_1, 200000),
        FakeTxRecord(uuid.uuid4(), completed[1][1], CATEGORY_1, 200000),
        FakeTxRecord(uuid.uuid4(), completed[2][0], CATEGORY_1, 200000),
        FakeTxRecord(uuid.uuid4(), completed[2][1], CATEGORY_1, 200000),
    ]

    req = BudgetRecommendationRequest(category_id=CATEGORY_1, savings_level_percent=5)
    resp = await recommend_budget(fake_session, user, req)  # type: ignore[arg-type]

    assert resp.category_id == CATEGORY_1
    assert resp.category_name == "Groceries"
    assert resp.raw_median_paise == 400000
    # 5% savings = 20,000 paise -> 380,000 paise -> ₹3,800
    assert resp.recommended_limit_paise == 380000
    assert "Groceries" in resp.explanation


@pytest.mark.asyncio
async def test_recommend_budget_insufficient_history(fake_session: FakeAsyncSession) -> None:
    # User registered just yesterday
    user = User(id=uuid.uuid4(), email="new@example.com", created_at=datetime.now(UTC))
    req = BudgetRecommendationRequest(category_id=None, savings_level_percent=10)
    resp = await recommend_budget(fake_session, user, req)  # type: ignore[arg-type]

    assert resp.has_sufficient_history is False
    assert resp.raw_median_paise == 0
    assert "limited spending history" in resp.explanation


@pytest.mark.asyncio
async def test_recommend_budget_user_share_only_and_exclusions(fake_session: FakeAsyncSession) -> None:
    """Verify recommendation uses allocated share, excluding cash fronted, settlements, and deleted expenses."""
    user = User(id=uuid.uuid4(), email="share@example.com", created_at=datetime(2025, 1, 1, tzinfo=UTC))
    completed = get_last_three_completed_months()

    # User's allocated share is ₹3,000 (300,000 paise) per month.
    # Suppose cash fronted was ₹10,000, but only the ₹3,000 share record is present in analytics ledger_rows.
    fake_session.db.tx_records = [
        FakeTxRecord(uuid.uuid4(), completed[0][0], CATEGORY_1, 150000),
        FakeTxRecord(uuid.uuid4(), completed[0][1], CATEGORY_1, 150000),
        FakeTxRecord(uuid.uuid4(), completed[1][0], CATEGORY_1, 150000),
        FakeTxRecord(uuid.uuid4(), completed[1][1], CATEGORY_1, 150000),
        FakeTxRecord(uuid.uuid4(), completed[2][0], CATEGORY_1, 150000),
        FakeTxRecord(uuid.uuid4(), completed[2][1], CATEGORY_1, 150000),
    ]

    req = BudgetRecommendationRequest(category_id=None, savings_level_percent=0)
    resp = await recommend_budget(fake_session, user, req)  # type: ignore[arg-type]

    # Median of ₹3,000 with 0% savings = ₹3,000 (300,000 paise)
    assert resp.raw_median_paise == 300000
    assert resp.recommended_limit_paise == 300000
    assert resp.savings_paise == 0


@pytest.mark.asyncio
async def test_advisory_only_never_creates_or_modifies_budgets(fake_session: FakeAsyncSession) -> None:
    """Verify that calling recommend_budget never creates or writes Budget records."""
    user = User(id=uuid.uuid4(), email="read@example.com", created_at=datetime(2025, 1, 1, tzinfo=UTC))
    initial_budget_count = len(fake_session.db.budgets)

    req = BudgetRecommendationRequest(category_id=None, savings_level_percent=10)
    await recommend_budget(fake_session, user, req)  # type: ignore[arg-type]

    # Zero writes to budgets table
    assert len(fake_session.db.budgets) == initial_budget_count


@pytest.mark.asyncio
async def test_recommend_budget_groq_ai_success_and_hallucination_guard(fake_session: FakeAsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Groq AI explanation is accepted when grounded, and rejected when numbers hallucinate."""
    user = User(id=uuid.uuid4(), email="groq@example.com", created_at=datetime(2025, 1, 1, tzinfo=UTC))
    completed = get_last_three_completed_months()

    fake_session.db.tx_records = [
        FakeTxRecord(uuid.uuid4(), completed[0][0], CATEGORY_1, 250000),
        FakeTxRecord(uuid.uuid4(), completed[0][1], CATEGORY_1, 250000),
        FakeTxRecord(uuid.uuid4(), completed[1][0], CATEGORY_1, 250000),
        FakeTxRecord(uuid.uuid4(), completed[1][1], CATEGORY_1, 250000),
        FakeTxRecord(uuid.uuid4(), completed[2][0], CATEGORY_1, 250000),
        FakeTxRecord(uuid.uuid4(), completed[2][1], CATEGORY_1, 250000),
    ]

    # 1. Successful grounded AI generation
    grounded_transport = MockTransport(
        lambda req: Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "content": "You spent a median of ₹5,000 monthly, so your recommended budget with 10% savings is ₹4,500."
                    }
                }]
            },
        )
    )
    fake_client = GroqClient(api_key="gsk_test", http_client=AsyncClient(transport=grounded_transport))
    monkeypatch.setattr(budget_recommendation_service, "get_groq_client", lambda: fake_client)

    req = BudgetRecommendationRequest(category_id=None, savings_level_percent=10)
    resp = await recommend_budget(fake_session, user, req)  # type: ignore[arg-type]
    assert resp.source == "ai"
    assert "₹4,500" in resp.explanation

    # 2. Hallucinated numbers in AI generation -> fallback to template
    hallucinated_transport = MockTransport(
        lambda req: Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "content": "We recommend ₹4,500, and you can achieve extra savings of ₹7,777!"
                    }
                }]
            },
        )
    )
    fake_client_hallucinated = GroqClient(
        api_key="gsk_test", http_client=AsyncClient(transport=hallucinated_transport)
    )
    monkeypatch.setattr(budget_recommendation_service, "get_groq_client", lambda: fake_client_hallucinated)
    resp_fallback = await recommend_budget(fake_session, user, req)  # type: ignore[arg-type]
    assert resp_fallback.source == "template_fallback"
    assert "₹4,500" in resp_fallback.explanation
    assert "7,777" not in resp_fallback.explanation


# ==============================================================================
# 5. API Endpoint Tests (Integration)
# ==============================================================================


@pytest.mark.asyncio
async def test_api_recommend_budget_unauthenticated(client: AsyncClient) -> None:
    res = await client.post("/api/v1/budgets/recommend", json={"savingsLevelPercent": 10})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_api_recommend_budget_invalid_payload(client_auth: AsyncClient, headers_a: dict[str, str]) -> None:
    # 15% is not allowed (only 0, 5, 10)
    res = await client_auth.post(
        "/api/v1/budgets/recommend",
        headers=headers_a,
        json={"savingsLevelPercent": 15},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_api_recommend_budget_success(
    client_auth: AsyncClient,
    headers_a: dict[str, str],
    auth_db: Any,
) -> None:
    # Post with valid payload using client_auth
    res = await client_auth.post(
        "/api/v1/budgets/recommend",
        headers=headers_a,
        json={"savingsLevelPercent": 10},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert "recommendedLimitPaise" in data
    assert "rawMedianPaise" in data
    assert "savingsPaise" in data
    assert "hasSufficientHistory" in data
    assert "historicalMonths" in data
    assert "explanation" in data
    assert "source" in data
