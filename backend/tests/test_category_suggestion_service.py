"""Unit tests for category suggestion service and Groq client integration.

Tests cover:
- High confidence prediction (>= 0.60) does not invoke Groq
- Boundary confidence (0.60) does not invoke Groq
- Low confidence (< 0.60) invokes Groq fallback
- Valid Groq response parsing & canonical mapping
- Invalid/non-canonical Groq output safe fallback to KeywordRuleBaseline
- Groq timeout and network error safe fallbacks
- Missing Groq API key handling
- User history isolation across different users
- Feedback persistence and user history update
- Category UUID resolution (custom category precedence & default fallback)
- Model caching (loads once, not per request)
- Database rollback safety (history not updated on DB failure)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from app.models.category import Category
from app.models.category_feedback import CategorySuggestionFeedback
from app.schemas.category_suggestion import (
    CategoryFeedbackRequest,
    CategorySuggestionRequest,
)
from app.services.category_suggestion_service import (
    get_category_classifier,
    record_feedback,
    reset_user_history_cache,
    resolve_category_uuid,
    restore_user_history,
    suggest_category,
)
from app.services.groq_client import CANONICAL_CATEGORIES, GroqClient

from ml.classifier import CategoryClassifier
from ml.history import UserHistoryLayer


class FakeScalars:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any | None:
        return self._items[0] if self._items else None


class FakeResult:
    def __init__(self, items: list[Any] | None = None) -> None:
        self._items = items or []

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._items)

    def scalar_one_or_none(self) -> Any | None:
        return self._items[0] if self._items else None

    def all(self) -> list[Any]:
        return list(self._items)


class FeedbackRow:
    """Mock row representation for joined feedback and category query."""

    def __init__(
        self,
        id: uuid.UUID,
        user_id: uuid.UUID,
        merchant: str | None,
        description: str,
        chosen_category_name: str,
    ) -> None:
        self.id = id
        self.user_id = user_id
        self.merchant = merchant
        self.description = description
        self.chosen_category_name = chosen_category_name


class FakeDBAsyncSession:
    """Minimal fake AsyncSession for service tests."""

    def __init__(self, categories: list[Category] | None = None) -> None:
        self.categories: list[Category] = categories or []
        self.feedback: list[CategorySuggestionFeedback] = []
        self.added: list[Any] = []
        self.committed = False
        self.should_fail_commit = False
        self.should_fail_feedback_query = False

    def add(self, obj: Any) -> None:
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def commit(self) -> None:
        if self.should_fail_commit:
            raise RuntimeError("Simulated Database Commit Error")
        for obj in self.added:
            if isinstance(obj, CategorySuggestionFeedback):
                self.feedback.append(obj)
        self.committed = True

    async def refresh(self, obj: Any) -> None:
        pass

    async def execute(self, stmt: Any) -> FakeResult:
        sql_str = str(stmt).lower()

        # Feedback query for startup restoration
        if "category_suggestion_feedback" in sql_str:
            if self.should_fail_feedback_query:
                raise RuntimeError("Simulated Database Query Error during feedback restoration")
            rows = []
            for fb in self.feedback:
                cat_name = next(
                    (c.name for c in self.categories if c.id == fb.chosen_category_id),
                    "Other",
                )
                rows.append(
                    FeedbackRow(
                        id=fb.id,
                        user_id=fb.user_id,
                        merchant=fb.merchant,
                        description=fb.description,
                        chosen_category_name=cat_name,
                    )
                )
            return FakeResult(rows)

        # Category query
        if "categories" in sql_str:
            params = stmt.compile().params
            # If selecting by specific Category.id == ...
            if "categories.id =" in sql_str:
                target_id = params.get("id_1") or params.get("id")
                matched = [c for c in self.categories if c.id == target_id]
                return FakeResult(matched)

            # Selecting default and/or user-owned categories
            user_id = params.get("owner_id_1") or params.get("owner_id")
            matched = [
                c for c in self.categories
                if c.is_default or (user_id is not None and c.owner_id == user_id)
            ]
            return FakeResult(matched)
        return FakeResult([])


@pytest.fixture
def default_categories() -> list[Category]:
    """Fixture providing all 12 default canonical categories."""
    cats = []
    for idx, name in enumerate(CANONICAL_CATEGORIES, start=1):
        cat_id = uuid.UUID(f"00000000-0000-4000-8000-{idx:012d}")
        cats.append(
            Category(
                id=cat_id,
                name=name,
                is_default=True,
                owner_id=None,
                created_at=datetime.now(UTC),
            )
        )
    return cats


@pytest.fixture
def fake_db(default_categories: list[Category]) -> FakeDBAsyncSession:
    return FakeDBAsyncSession(categories=default_categories)


class TestGroqClient:
    """Unit tests for the GroqClient wrapper."""

    def test_unconfigured_when_no_api_key(self) -> None:
        client = GroqClient(api_key=None)
        assert client.is_configured() is False

    def test_configured_when_key_present(self) -> None:
        client = GroqClient(api_key="gsk_test123456789")
        assert client.is_configured() is True

    @pytest.mark.anyio
    async def test_classify_category_skips_when_not_configured(self) -> None:
        client = GroqClient(api_key="")
        result = await client.classify_category("Starbucks coffee", "Starbucks")
        assert result is None

    @pytest.mark.anyio
    async def test_classify_category_parses_valid_json_canonical(self) -> None:
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"category": "Food & Dining"}'
                    }
                }
            ]
        }
        mock_http.post.return_value = mock_response

        client = GroqClient(api_key="gsk_test", http_client=mock_http)
        cat = await client.classify_category("Dinner with team", "Bawarchi")
        assert cat == "Food & Dining"

    @pytest.mark.anyio
    async def test_classify_category_maps_synonyms(self) -> None:
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"category": "food & drink"}'
                    }
                }
            ]
        }
        mock_http.post.return_value = mock_response

        client = GroqClient(api_key="gsk_test", http_client=mock_http)
        cat = await client.classify_category("Lunch at cafe", "Cafe Coffee Day")
        assert cat == "Food & Dining"

    @pytest.mark.anyio
    async def test_classify_category_returns_none_on_invalid_category(self) -> None:
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"category": "Cryptocurrency Investment"}'
                    }
                }
            ]
        }
        mock_http.post.return_value = mock_response

        client = GroqClient(api_key="gsk_test", http_client=mock_http)
        cat = await client.classify_category("Random crypto transaction")
        assert cat is None

    @pytest.mark.anyio
    async def test_classify_category_handles_timeout(self) -> None:
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.post.side_effect = httpx.TimeoutException("Read timed out")

        client = GroqClient(api_key="gsk_test", http_client=mock_http)
        cat = await client.classify_category("Slow request", "Merchant")
        assert cat is None

    @pytest.mark.anyio
    async def test_classify_category_handles_network_error(self) -> None:
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.post.side_effect = httpx.ConnectError("Connection refused")

        client = GroqClient(api_key="gsk_test", http_client=mock_http)
        cat = await client.classify_category("Network drop", "Merchant")
        assert cat is None

    @pytest.mark.anyio
    async def test_classify_category_handles_bad_status(self) -> None:
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 429
        mock_response.text = "Rate limit reached"
        mock_http.post.return_value = mock_response

        client = GroqClient(api_key="gsk_test", http_client=mock_http)
        cat = await client.classify_category("Exceeded rate limit")
        assert cat is None


class TestCategorySuggestionService:
    """Service layer pipeline and threshold tests."""

    @pytest.mark.anyio
    async def test_high_confidence_never_calls_groq(self, fake_db: FakeDBAsyncSession) -> None:
        user_id = uuid.uuid4()
        req = CategorySuggestionRequest(description="Starbucks coffee latte", merchant="Starbucks")

        mock_groq = MagicMock(spec=GroqClient)
        mock_groq.is_configured.return_value = True
        mock_groq.classify_category = AsyncMock()

        # Mock classifier returning high confidence (0.92)
        mock_clf = MagicMock(spec=CategoryClassifier)
        mock_clf.predict_single.return_value = {
            "category": "Food & Dining",
            "confidence": 0.92,
            "probabilities": {"Food & Dining": 0.92, "Other": 0.08},
            "normalized_merchant": "starbucks",
            "cleaned_text": "starbucks coffee latte",
        }

        res = await suggest_category(
            db=fake_db,
            user_id=user_id,
            req=req,
            classifier=mock_clf,
            groq_client=mock_groq,
        )

        assert res.category_name == "Food & Dining"
        assert res.confidence == 0.92
        assert res.source == "classifier"
        assert res.requires_confirmation is False  # Confidence >= 0.85
        mock_groq.classify_category.assert_not_called()

    @pytest.mark.anyio
    async def test_boundary_confidence_0_60_does_not_call_groq(self, fake_db: FakeDBAsyncSession) -> None:
        user_id = uuid.uuid4()
        req = CategorySuggestionRequest(description="Borderline expense")

        mock_groq = MagicMock(spec=GroqClient)
        mock_groq.is_configured.return_value = True
        mock_groq.classify_category = AsyncMock()

        mock_clf = MagicMock(spec=CategoryClassifier)
        mock_clf.predict_single.return_value = {
            "category": "Shopping",
            "confidence": 0.60,
            "probabilities": {"Shopping": 0.60, "Other": 0.40},
            "normalized_merchant": "",
            "cleaned_text": "borderline expense",
        }

        res = await suggest_category(
            db=fake_db,
            user_id=user_id,
            req=req,
            classifier=mock_clf,
            groq_client=mock_groq,
        )

        assert res.category_name == "Shopping"
        assert res.confidence == 0.60
        assert res.source == "classifier"
        mock_groq.classify_category.assert_not_called()

    @pytest.mark.anyio
    async def test_low_confidence_calls_groq(self, fake_db: FakeDBAsyncSession) -> None:
        user_id = uuid.uuid4()
        req = CategorySuggestionRequest(description="Vague miscellaneous payment", merchant="Paytm")

        mock_groq = MagicMock(spec=GroqClient)
        mock_groq.is_configured.return_value = True
        mock_groq.classify_category = AsyncMock(return_value="Bills & Utilities")

        mock_clf = MagicMock(spec=CategoryClassifier)
        mock_clf.predict_single.return_value = {
            "category": "Other",
            "confidence": 0.38,  # Below 0.60
            "probabilities": {"Other": 0.38, "Bills & Utilities": 0.20},
            "normalized_merchant": "paytm",
            "cleaned_text": "vague miscellaneous payment",
        }

        res = await suggest_category(
            db=fake_db,
            user_id=user_id,
            req=req,
            classifier=mock_clf,
            groq_client=mock_groq,
        )

        mock_groq.classify_category.assert_awaited_once_with(
            description=req.description,
            merchant=req.merchant,
        )
        assert res.category_name == "Bills & Utilities"
        assert res.source == "llm"
        assert res.requires_confirmation is True

    @pytest.mark.anyio
    async def test_low_confidence_groq_failure_falls_back_to_rule_baseline(self, fake_db: FakeDBAsyncSession) -> None:
        user_id = uuid.uuid4()
        # "uber ride" has a deterministic rule in KeywordRuleBaseline -> Travel & Transport
        req = CategorySuggestionRequest(description="Uber ride to station", merchant="Uber")

        mock_groq = MagicMock(spec=GroqClient)
        mock_groq.is_configured.return_value = True
        # Groq fails/times out and returns None
        mock_groq.classify_category = AsyncMock(return_value=None)

        mock_clf = MagicMock(spec=CategoryClassifier)
        mock_clf.predict_single.return_value = {
            "category": "Other",
            "confidence": 0.40,
            "probabilities": {"Other": 0.40},
            "normalized_merchant": "uber",
            "cleaned_text": "uber ride station",
        }

        res = await suggest_category(
            db=fake_db,
            user_id=user_id,
            req=req,
            classifier=mock_clf,
            groq_client=mock_groq,
        )

        assert res.category_name == "Travel & Transport"
        assert res.source == "rule_fallback"
        assert res.requires_confirmation is True

    @pytest.mark.anyio
    async def test_user_history_isolation(self, fake_db: FakeDBAsyncSession) -> None:
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        hist = UserHistoryLayer()
        # User A frequently categorizes "Reliance" as "Groceries"
        for _ in range(5):
            hist.record_transaction(str(user_a), "Groceries", merchant="Reliance Fresh")

        # User B has no history for "Reliance"
        counts_a = hist.get_merchant_history(str(user_a), "Reliance Fresh")
        counts_b = hist.get_merchant_history(str(user_b), "Reliance Fresh")

        assert counts_a == {"Groceries": 5}
        assert counts_b == {}

    @pytest.mark.anyio
    async def test_feedback_persistence_and_history_update(self, fake_db: FakeDBAsyncSession) -> None:
        user_id = uuid.uuid4()
        hist = UserHistoryLayer()

        food_cat = next(c for c in fake_db.categories if c.name == "Food & Dining")
        other_cat = next(c for c in fake_db.categories if c.name == "Other")

        feedback_req = CategoryFeedbackRequest(
            description="Starbucks cold brew",
            merchant="Starbucks",
            suggested_category_id=other_cat.id,
            chosen_category_id=food_cat.id,
            confidence=0.45,
            source="classifier",
            accepted=False,  # Manual override
        )

        res = await record_feedback(
            db=fake_db,
            user_id=user_id,
            feedback_req=feedback_req,
            history_layer=hist,
        )

        assert res.success is True
        assert fake_db.committed is True
        assert len(fake_db.added) == 1
        entry: CategorySuggestionFeedback = fake_db.added[0]
        assert entry.user_id == user_id
        assert entry.chosen_category_id == food_cat.id
        assert entry.accepted is False

        # In-memory history updated
        counts = hist.get_merchant_history(str(user_id), "Starbucks")
        assert counts.get("Food & Dining") == 1

    @pytest.mark.anyio
    async def test_feedback_aborts_history_update_on_db_error(self, fake_db: FakeDBAsyncSession) -> None:
        user_id = uuid.uuid4()
        hist = UserHistoryLayer()
        fake_db.should_fail_commit = True

        food_cat = next(c for c in fake_db.categories if c.name == "Food & Dining")

        feedback_req = CategoryFeedbackRequest(
            description="Chai at tapri",
            merchant="Chai Tapri",
            suggested_category_id=food_cat.id,
            chosen_category_id=food_cat.id,
            confidence=0.88,
            source="classifier",
            accepted=True,
        )

        with pytest.raises(RuntimeError, match="Simulated Database Commit Error"):
            await record_feedback(
                db=fake_db,
                user_id=user_id,
                feedback_req=feedback_req,
                history_layer=hist,
            )

        # Ensure history was NOT updated because DB transaction failed
        counts = hist.get_merchant_history(str(user_id), "Chai Tapri")
        assert counts == {}

    @pytest.mark.anyio
    async def test_category_uuid_resolution(self, fake_db: FakeDBAsyncSession) -> None:
        user_id = uuid.uuid4()

        # Add a custom category owned by user_id
        custom_cat_id = uuid.uuid4()
        custom_cat = Category(
            id=custom_cat_id,
            name="Food & Dining",  # Custom override with same name
            owner_id=user_id,
            is_default=False,
            created_at=datetime.now(UTC),
        )
        fake_db.categories.insert(0, custom_cat)

        cat_id, name = await resolve_category_uuid(fake_db, user_id, "Food & Dining")
        assert cat_id == custom_cat_id
        assert name == "Food & Dining"

    def test_model_caching(self) -> None:
        """Verify get_category_classifier returns the singleton instance without reloading."""
        clf1 = get_category_classifier()
        clf2 = get_category_classifier()
        assert clf1 is clf2


class TestStartupUserHistoryRestoration:
    """Tests verifying startup restoration of user history from PostgreSQL."""

    @pytest.mark.anyio
    async def test_previously_recorded_feedback_is_restored(self, fake_db: FakeDBAsyncSession) -> None:
        reset_user_history_cache()
        hist = UserHistoryLayer()
        user_id = uuid.uuid4()
        food_cat = next(c for c in fake_db.categories if c.name == "Food & Dining")

        for _ in range(3):
            fb = CategorySuggestionFeedback(
                id=uuid.uuid4(),
                user_id=user_id,
                description="Starbucks cold brew",
                merchant="Starbucks",
                suggested_category_id=food_cat.id,
                chosen_category_id=food_cat.id,
                confidence=0.90,
                source="classifier",
                accepted=True,
                created_at=datetime.now(UTC),
            )
            fake_db.feedback.append(fb)

        restored = await restore_user_history(session=fake_db, history_layer=hist)
        assert restored == 3
        counts = hist.get_merchant_history(str(user_id), "Starbucks")
        assert counts == {"Food & Dining": 3}

    @pytest.mark.anyio
    async def test_different_users_remain_isolated_on_restore(self, fake_db: FakeDBAsyncSession) -> None:
        reset_user_history_cache()
        hist = UserHistoryLayer()
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        food_cat = next(c for c in fake_db.categories if c.name == "Food & Dining")
        ent_cat = next(c for c in fake_db.categories if c.name == "Entertainment")

        # User A: Starbucks -> Food & Dining
        fake_db.feedback.append(
            CategorySuggestionFeedback(
                id=uuid.uuid4(),
                user_id=user_a,
                description="Starbucks coffee",
                merchant="Starbucks",
                suggested_category_id=food_cat.id,
                chosen_category_id=food_cat.id,
                confidence=0.85,
                source="classifier",
                accepted=True,
                created_at=datetime.now(UTC),
            )
        )

        # User B: Starbucks -> Entertainment
        fake_db.feedback.append(
            CategorySuggestionFeedback(
                id=uuid.uuid4(),
                user_id=user_b,
                description="Starbucks coffee",
                merchant="Starbucks",
                suggested_category_id=ent_cat.id,
                chosen_category_id=ent_cat.id,
                confidence=0.75,
                source="classifier",
                accepted=True,
                created_at=datetime.now(UTC),
            )
        )

        restored = await restore_user_history(session=fake_db, history_layer=hist)
        assert restored == 2

        counts_a = hist.get_merchant_history(str(user_a), "Starbucks")
        counts_b = hist.get_merchant_history(str(user_b), "Starbucks")
        assert counts_a == {"Food & Dining": 1}
        assert counts_b == {"Entertainment": 1}

    @pytest.mark.anyio
    async def test_empty_feedback_history_handled(self, fake_db: FakeDBAsyncSession) -> None:
        reset_user_history_cache()
        hist = UserHistoryLayer()
        fake_db.feedback.clear()

        restored = await restore_user_history(session=fake_db, history_layer=hist)
        assert restored == 0
        assert hist.get_merchant_history(str(uuid.uuid4()), "Any") == {}

    @pytest.mark.anyio
    async def test_database_errors_handled_safely(self, fake_db: FakeDBAsyncSession) -> None:
        reset_user_history_cache()
        hist = UserHistoryLayer()
        fake_db.should_fail_feedback_query = True

        restored = await restore_user_history(session=fake_db, history_layer=hist)
        assert restored == 0

    @pytest.mark.anyio
    async def test_existing_history_not_duplicated_on_repeated_initialization(self, fake_db: FakeDBAsyncSession) -> None:
        reset_user_history_cache()
        hist = UserHistoryLayer()
        user_id = uuid.uuid4()
        food_cat = next(c for c in fake_db.categories if c.name == "Food & Dining")

        for _ in range(2):
            fake_db.feedback.append(
                CategorySuggestionFeedback(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    description="Biryani order",
                    merchant="Bawarchi",
                    suggested_category_id=food_cat.id,
                    chosen_category_id=food_cat.id,
                    confidence=0.92,
                    source="classifier",
                    accepted=True,
                    created_at=datetime.now(UTC),
                )
            )

        restored_1 = await restore_user_history(session=fake_db, history_layer=hist)
        assert restored_1 == 2
        counts_1 = hist.get_merchant_history(str(user_id), "Bawarchi")
        assert counts_1 == {"Food & Dining": 2}

        # Second restoration call
        restored_2 = await restore_user_history(session=fake_db, history_layer=hist)
        assert restored_2 == 0
        counts_2 = hist.get_merchant_history(str(user_id), "Bawarchi")
        assert counts_2 == {"Food & Dining": 2}
