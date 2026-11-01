"""Comprehensive unit, integration, and concurrency tests for S2-AI-01.

Covers:
- Configuration defaults and environment overrides
- Quota tracking, user isolation, and feature isolation
- UTC midnight daily reset
- Atomic in-flight concurrency reservations
- Usage logging persistence and error handling
- Category suggestion integration (Groq gating, quota exhaustion fallback, AI_ENABLED toggle)
- Database model schema, indices, and Alembic migration structure
"""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from ml.classifier import CategoryClassifier
from ml.history import UserHistoryLayer

from app.ai.quota import (
    AIQuotaService,
    get_daily_limit_for_feature,
    log_ai_usage,
)
from app.core.config import settings
from app.models.ai_usage_log import AIUsageLog
from app.models.category import Category
from app.models.user import User
from app.schemas.category_suggestion import CategorySuggestionRequest
from app.services.category_suggestion_service import suggest_category
from app.services.groq_client import CANONICAL_CATEGORIES, GroqClient

# =====================================================================
# In-Memory Fake DB for Fast, Deterministic Unit/Integration Testing
# =====================================================================


class QuotaFakeDB:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}
        self.categories: dict[uuid.UUID, Category] = {}
        self.ai_logs: list[AIUsageLog] = []


class FakeScalars:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any | None:
        return self._items[0] if self._items else None


class FakeResult:
    def __init__(self, items: list[Any] | None = None, scalar_val: Any = None) -> None:
        self._items = items or []
        self._scalar_val = scalar_val

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._items)

    def scalar_one_or_none(self) -> Any | None:
        if self._scalar_val is not None:
            return self._scalar_val
        return self._items[0] if self._items else None


class QuotaFakeAsyncSession:
    """Mock AsyncSession simulating PostgreSQL queries on AIUsageLog and Categories."""

    def __init__(self, db: QuotaFakeDB, fail_commits: bool = False) -> None:
        self.db = db
        self.fail_commits = fail_commits
        self.pending: list[Any] = []

    def add(self, obj: Any) -> None:
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        if hasattr(obj, "created_at") and obj.created_at is None:
            obj.created_at = datetime.now(UTC)
        self.pending.append(obj)

    async def commit(self) -> None:
        if self.fail_commits:
            from sqlalchemy.exc import OperationalError

            raise OperationalError("Simulated DB connection failure", {}, None)
        for obj in self.pending:
            if isinstance(obj, AIUsageLog):
                self.db.ai_logs.append(obj)
        self.pending.clear()

    async def refresh(self, obj: Any) -> None:
        pass

    async def rollback(self) -> None:
        self.pending.clear()

    async def execute(self, stmt: Any) -> FakeResult:
        sql_str = str(stmt).lower()
        params = stmt.compile().params

        # 1. AIUsageLog count query (used in quota checking)
        if "from ai_usage_log" in sql_str and "count" in sql_str:
            uid = params.get("user_id_1") or params.get("user_id")
            feat = params.get("feature_1") or params.get("feature")
            cutoff = params.get("created_at_1") or params.get("created_at")

            # Match active usage (success or active pending)
            matching = [
                log
                for log in self.db.ai_logs
                if (uid is None or log.user_id == uid)
                and (feat is None or log.feature == feat)
                and (cutoff is None or log.created_at >= cutoff)
                and (log.status in ("success", "pending"))
            ]
            return FakeResult(scalar_val=len(matching))

        # 2. UPDATE ai_usage_log (finalize reservation)
        if "update ai_usage_log" in sql_str:
            target_id = params.get("id_1") or params.get("id") or params.get("ai_usage_log_id")
            for log in self.db.ai_logs:
                if target_id is None or log.id == target_id:
                    for k, v in params.items():
                        if hasattr(log, k):
                            setattr(log, k, v)
                    return FakeResult([log])
            return FakeResult([])

        # 3. SELECT Category
        if "from categories" in sql_str:
            target_id = params.get("id_1") or params.get("id")
            if target_id is not None:
                matched = [c for c in self.db.categories.values() if c.id == target_id]
                return FakeResult(matched)

            matched = [c for c in self.db.categories.values() if c.is_default]
            return FakeResult(matched)

        # 4. PostgreSQL Advisory lock
        if "pg_advisory_xact_lock" in sql_str:
            return FakeResult([1])

        return FakeResult([])


@pytest.fixture
def fake_db() -> QuotaFakeDB:
    db = QuotaFakeDB()
    for idx, name in enumerate(CANONICAL_CATEGORIES, start=1):
        cat_id = uuid.UUID(f"00000000-0000-4000-8000-{idx:012d}")
        db.categories[cat_id] = Category(
            id=cat_id,
            name=name,
            is_default=True,
            owner_id=None,
            created_at=datetime.now(UTC),
        )
    return db


@pytest.fixture
def test_user(fake_db: QuotaFakeDB) -> User:
    u = User(
        id=uuid.uuid4(),
        email="quota_tester@example.com",
        name="Quota Tester",
        hashed_password="hashed_pass_sample",
        is_active=True,
    )
    fake_db.users[u.id] = u
    return u


# =====================================================================
# 1. Configuration Tests
# =====================================================================


def test_default_quota_settings() -> None:
    """AC: System provides configurable daily quotas with documented defaults."""
    assert settings.AI_ENABLED is True
    assert settings.AI_QUOTA_CATEGORIZE_DAILY == 50
    assert settings.AI_QUOTA_RECEIPT_DAILY == 10
    assert settings.AI_QUOTA_BUDGET_GOALS_DAILY == 5
    assert settings.AI_QUOTA_ASK_DAILY == 20

    assert get_daily_limit_for_feature("categorize") == 50
    assert get_daily_limit_for_feature("receipt") == 10
    assert get_daily_limit_for_feature("budget_goals") == 5
    assert get_daily_limit_for_feature("ask") == 20


def test_custom_env_quota_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC: Quota limits can be configured without modifying code."""
    monkeypatch.setattr(settings, "AI_QUOTA_CATEGORIZE_DAILY", 100)
    monkeypatch.setattr(settings, "AI_QUOTA_RECEIPT_DAILY", 25)
    monkeypatch.setattr(settings, "AI_ENABLED", False)

    assert get_daily_limit_for_feature("categorize") == 100
    assert get_daily_limit_for_feature("receipt") == 25
    assert settings.AI_ENABLED is False


def test_unknown_feature_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown AI feature"):
        get_daily_limit_for_feature("unsupported_telepathy")


# =====================================================================
# 2. Quota Service & Enforcement Tests
# =====================================================================


@pytest.mark.anyio
async def test_check_quota_within_limit(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    session = QuotaFakeAsyncSession(fake_db)
    service = AIQuotaService()

    status_obj = await service.check_quota(
        user_id=test_user.id,
        feature="categorize",
        db=session,  # type: ignore[arg-type]
    )

    assert status_obj.allowed is True
    assert status_obj.used_today == 0
    assert status_obj.daily_limit == 50
    assert status_obj.remaining == 50
    assert status_obj.is_ai_enabled is True
    assert status_obj.reason is None


@pytest.mark.anyio
async def test_check_quota_exhausted_raises_429(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    """AC: When exhausted, returns HTTP 429 with AI_QUOTA_EXCEEDED."""
    service = AIQuotaService()
    session = QuotaFakeAsyncSession(fake_db)

    # Seed 50 usage records for today
    for _ in range(50):
        fake_db.ai_logs.append(
            AIUsageLog(
                user_id=test_user.id,
                feature="categorize",
                provider="groq",
                model="llama-3.1-8b-instant",
                status="success",
                created_at=datetime.now(UTC),
            )
        )

    with pytest.raises(HTTPException) as exc_info:
        await service.check_quota(
            user_id=test_user.id,
            feature="categorize",
            db=session,  # type: ignore[arg-type]
            raise_on_exceeded=True,
        )

    assert exc_info.value.status_code == 429
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "AI_QUOTA_EXCEEDED"
    assert "Daily AI quota exceeded for categorize" in detail["message"]
    assert "midnight UTC" in detail["message"]


@pytest.mark.anyio
async def test_check_quota_exhausted_no_raise(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    service = AIQuotaService()
    session = QuotaFakeAsyncSession(fake_db)

    for _ in range(50):
        fake_db.ai_logs.append(
            AIUsageLog(
                user_id=test_user.id,
                feature="categorize",
                provider="groq",
                model="llama-3.1-8b-instant",
                status="success",
                created_at=datetime.now(UTC),
            )
        )

    status_obj = await service.check_quota(
        user_id=test_user.id,
        feature="categorize",
        db=session,  # type: ignore[arg-type]
        raise_on_exceeded=False,
    )

    assert status_obj.allowed is False
    assert status_obj.used_today == 50
    assert status_obj.remaining == 0
    assert status_obj.reason == "QUOTA_EXCEEDED"


@pytest.mark.anyio
async def test_user_quota_isolation(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    """AC: Quota consumption by User A must not impact User B."""
    other_user_id = uuid.uuid4()
    service = AIQuotaService()
    session = QuotaFakeAsyncSession(fake_db)

    # Exhaust user A's limit
    for _ in range(50):
        fake_db.ai_logs.append(
            AIUsageLog(
                user_id=test_user.id,
                feature="categorize",
                provider="groq",
                model="llama-3.1-8b-instant",
                status="success",
                created_at=datetime.now(UTC),
            )
        )

    status_a = await service.check_quota(
        test_user.id, "categorize", db=session, raise_on_exceeded=False  # type: ignore[arg-type]
    )
    status_b = await service.check_quota(
        other_user_id, "categorize", db=session, raise_on_exceeded=False  # type: ignore[arg-type]
    )

    assert status_a.allowed is False
    assert status_b.allowed is True
    assert status_b.remaining == 50


@pytest.mark.anyio
async def test_feature_quota_isolation(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    """AC: Exhausting categorize quota must not block receipt scanning."""
    service = AIQuotaService()
    session = QuotaFakeAsyncSession(fake_db)

    for _ in range(50):
        fake_db.ai_logs.append(
            AIUsageLog(
                user_id=test_user.id,
                feature="categorize",
                provider="groq",
                model="llama-3.1-8b-instant",
                status="success",
                created_at=datetime.now(UTC),
            )
        )

    cat_status = await service.check_quota(
        test_user.id, "categorize", db=session, raise_on_exceeded=False  # type: ignore[arg-type]
    )
    receipt_status = await service.check_quota(
        test_user.id, "receipt", db=session, raise_on_exceeded=False  # type: ignore[arg-type]
    )

    assert cat_status.allowed is False
    assert receipt_status.allowed is True
    assert receipt_status.remaining == 10


@pytest.mark.anyio
async def test_utc_midnight_reset(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    """AC: Quotas reset at UTC midnight (00:00:00). Yesterday's calls are ignored."""
    service = AIQuotaService()
    session = QuotaFakeAsyncSession(fake_db)

    yesterday_utc = datetime.now(UTC) - timedelta(days=1)

    for _ in range(50):
        fake_db.ai_logs.append(
            AIUsageLog(
                user_id=test_user.id,
                feature="categorize",
                provider="groq",
                model="llama-3.1-8b-instant",
                status="success",
                created_at=yesterday_utc,
            )
        )

    status_obj = await service.check_quota(
        test_user.id, "categorize", db=session, raise_on_exceeded=False  # type: ignore[arg-type]
    )

    assert status_obj.allowed is True
    assert status_obj.used_today == 0
    assert status_obj.remaining == 50


@pytest.mark.anyio
async def test_ai_disabled_behavior(
    monkeypatch: pytest.MonkeyPatch, fake_db: QuotaFakeDB, test_user: User
) -> None:
    """AC: When AI_ENABLED=False, calls do not proceed and consume 0 quota."""
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    service = AIQuotaService()
    session = QuotaFakeAsyncSession(fake_db)

    status_obj = await service.check_quota(
        test_user.id, "categorize", db=session, raise_on_exceeded=False  # type: ignore[arg-type]
    )

    assert status_obj.allowed is False
    assert status_obj.is_ai_enabled is False
    assert status_obj.reason == "AI_DISABLED"
    assert status_obj.remaining == 0


@pytest.mark.anyio
async def test_atomic_concurrent_reservation_safety(
    monkeypatch: pytest.MonkeyPatch, fake_db: QuotaFakeDB, test_user: User
) -> None:
    """AC: Atomic reservation prevents race condition from exceeding limit."""
    monkeypatch.setattr(settings, "AI_QUOTA_BUDGET_GOALS_DAILY", 2)
    service = AIQuotaService()
    session = QuotaFakeAsyncSession(fake_db)

    granted_reservations = 0
    rejected_reservations = 0

    async def worker() -> None:
        nonlocal granted_reservations, rejected_reservations
        async with service.reserve(
            user_id=test_user.id,
            feature="budget_goals",
            db=session,  # type: ignore[arg-type]
            raise_on_exceeded=False,
        ) as res:
            if res.allowed:
                granted_reservations += 1
                # Simulate work inside reservation
                await asyncio.sleep(0.01)
            else:
                rejected_reservations += 1

    # Launch 5 concurrent workers when daily limit is 2
    tasks = [asyncio.create_task(worker()) for _ in range(5)]
    await asyncio.gather(*tasks)

    assert granted_reservations == 2
    assert rejected_reservations == 3


# =====================================================================
# 3. Usage Logging Tests
# =====================================================================


@pytest.mark.anyio
async def test_log_ai_usage_success_persists(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    session = QuotaFakeAsyncSession(fake_db)

    log_entry = await log_ai_usage(
        user_id=test_user.id,
        feature="categorize",
        provider="groq",
        model="llama-3.1-8b-instant",
        status="success",
        prompt_tokens=20,
        completion_tokens=10,
        latency_ms=124.5,
        db=session,  # type: ignore[arg-type]
    )

    assert log_entry is not None
    assert len(fake_db.ai_logs) == 1
    persisted = fake_db.ai_logs[0]

    assert persisted.user_id == test_user.id
    assert persisted.feature == "categorize"
    assert persisted.provider == "groq"
    assert persisted.model == "llama-3.1-8b-instant"
    assert persisted.status == "success"
    assert persisted.prompt_tokens == 20
    assert persisted.completion_tokens == 10
    assert persisted.total_tokens == 30  # Auto-computed
    assert persisted.latency_ms == 124.5
    assert persisted.error_message is None


@pytest.mark.anyio
async def test_log_ai_usage_error_status(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    session = QuotaFakeAsyncSession(fake_db)

    log_entry = await log_ai_usage(
        user_id=test_user.id,
        feature="receipt",
        provider="groq",
        model="llama-3.1-8b-instant",
        status="error",
        error_message="HTTP 503 Provider unavailable",
        db=session,  # type: ignore[arg-type]
    )

    assert log_entry is not None
    assert len(fake_db.ai_logs) == 1
    assert fake_db.ai_logs[0].status == "error"
    assert fake_db.ai_logs[0].error_message == "HTTP 503 Provider unavailable"


@pytest.mark.anyio
async def test_log_ai_usage_nullable_tokens(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    session = QuotaFakeAsyncSession(fake_db)

    log_entry = await log_ai_usage(
        user_id=test_user.id,
        feature="ask",
        provider="groq",
        model="llama-3.1-8b-instant",
        status="success",
        prompt_tokens=None,
        completion_tokens=None,
        db=session,  # type: ignore[arg-type]
    )

    assert log_entry is not None
    assert fake_db.ai_logs[0].prompt_tokens is None
    assert fake_db.ai_logs[0].total_tokens is None


@pytest.mark.anyio
async def test_log_ai_usage_invalid_inputs_raise(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    session = QuotaFakeAsyncSession(fake_db)

    with pytest.raises(ValueError, match="Unknown AI feature"):
        await log_ai_usage(
            user_id=test_user.id,
            feature="quantum_forecast",
            provider="groq",
            model="llama-3.1-8b-instant",
            db=session,  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="Invalid status"):
        await log_ai_usage(
            user_id=test_user.id,
            feature="categorize",
            provider="groq",
            model="llama-3.1-8b-instant",
            status="random_bad_status",
            db=session,  # type: ignore[arg-type]
        )


@pytest.mark.anyio
async def test_log_ai_usage_db_failure_does_not_raise(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    """Preserve primary workflow resilience if database audit logging fails."""
    failing_session = QuotaFakeAsyncSession(fake_db, fail_commits=True)

    result = await log_ai_usage(
        user_id=test_user.id,
        feature="categorize",
        provider="groq",
        model="llama-3.1-8b-instant",
        status="success",
        db=failing_session,  # type: ignore[arg-type]
    )
    assert result is None  # Handled safely without bubbling uncaught DB exception


# =====================================================================
# 4. Integration Tests with Category Suggestion Pipeline (T-22/T-23)
# =====================================================================


class MockGroqClient(GroqClient):
    def __init__(self, return_val: str | None = "Shopping") -> None:
        super().__init__(api_key="mock_key", model="mock_model")
        self.return_val = return_val
        self.call_count = 0

    def is_configured(self) -> bool:
        return True

    async def classify_category(
        self, description: str, merchant: str | None = None
    ) -> str | None:
        self.call_count += 1
        return self.return_val


class MockClassifier(CategoryClassifier):
    def __init__(self, confidence: float = 0.40, category: str = "Other") -> None:
        self.forced_confidence = confidence
        self.forced_category = category

    def predict_single(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "category": self.forced_category,
            "confidence": self.forced_confidence,
            "probabilities": {self.forced_category: self.forced_confidence},
        }


@pytest.mark.anyio
async def test_category_suggestion_invokes_groq_and_logs_usage(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    """When confidence < 0.60 and quota is available, Groq is invoked and logged."""
    session = QuotaFakeAsyncSession(fake_db)
    mock_llm = MockGroqClient(return_val="Shopping")
    mock_clf = MockClassifier(confidence=0.45)
    hist = UserHistoryLayer()
    quota_svc = AIQuotaService()

    req = CategorySuggestionRequest(description="ambiguous unknown purchase")
    result = await suggest_category(
        db=session,  # type: ignore[arg-type]
        user_id=test_user.id,
        req=req,
        classifier=mock_clf,
        history_layer=hist,
        groq_client=mock_llm,
        quota_service=quota_svc,
    )

    assert result.source == "llm"
    assert result.category_name == "Shopping"
    assert mock_llm.call_count == 1

    # Verify AIUsageLog persisted
    assert len(fake_db.ai_logs) == 1
    log = fake_db.ai_logs[0]
    assert log.feature == "categorize"
    assert log.status == "success"
    assert log.latency_ms is not None


@pytest.mark.anyio
async def test_category_suggestion_quota_exhausted_falls_back_to_rule_baseline(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    """AC: When categorize quota is exhausted, falls back to deterministic rule baseline."""
    session = QuotaFakeAsyncSession(fake_db)
    mock_llm = MockGroqClient(return_val="Shopping")
    mock_clf = MockClassifier(confidence=0.45)
    hist = UserHistoryLayer()
    quota_svc = AIQuotaService()

    # Pre-exhaust user's daily quota
    for _ in range(50):
        fake_db.ai_logs.append(
            AIUsageLog(
                user_id=test_user.id,
                feature="categorize",
                provider="groq",
                model="llama-3.1-8b-instant",
                status="success",
                created_at=datetime.now(UTC),
            )
        )

    req = CategorySuggestionRequest(description="starbucks mocha coffee")
    result = await suggest_category(
        db=session,  # type: ignore[arg-type]
        user_id=test_user.id,
        req=req,
        classifier=mock_clf,
        history_layer=hist,
        groq_client=mock_llm,
        quota_service=quota_svc,
    )

    # Groq was NOT called due to quota exhaustion
    assert mock_llm.call_count == 0
    # Deterministic rule fallback handled it
    assert result.source == "rule_fallback"
    assert result.category_name == "Food & Dining"

    # Verify quota_exceeded audit logged
    quota_exceeded_logs = [l for l in fake_db.ai_logs if l.status == "quota_exceeded"]
    assert len(quota_exceeded_logs) == 1


@pytest.mark.anyio
async def test_category_suggestion_ai_disabled_falls_back_to_rule_baseline(
    monkeypatch: pytest.MonkeyPatch, fake_db: QuotaFakeDB, test_user: User
) -> None:
    """AC: When AI_ENABLED=False, Groq is bypassed without consuming quota."""
    monkeypatch.setattr(settings, "AI_ENABLED", False)

    session = QuotaFakeAsyncSession(fake_db)
    mock_llm = MockGroqClient(return_val="Shopping")
    mock_clf = MockClassifier(confidence=0.45)
    hist = UserHistoryLayer()
    quota_svc = AIQuotaService()

    req = CategorySuggestionRequest(description="uber cab ride")
    result = await suggest_category(
        db=session,  # type: ignore[arg-type]
        user_id=test_user.id,
        req=req,
        classifier=mock_clf,
        history_layer=hist,
        groq_client=mock_llm,
        quota_service=quota_svc,
    )

    assert mock_llm.call_count == 0
    assert result.source == "rule_fallback"
    assert result.category_name == "Travel & Transport"
    # Zero usage logged since AI was completely disabled
    assert len(fake_db.ai_logs) == 0


@pytest.mark.anyio
async def test_category_suggestion_high_confidence_never_checks_quota(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    """When local ML confidence >= 0.60, Groq and quota are bypassed entirely."""
    session = QuotaFakeAsyncSession(fake_db)
    mock_llm = MockGroqClient()
    mock_clf = MockClassifier(confidence=0.92, category="Groceries")
    hist = UserHistoryLayer()
    quota_svc = AIQuotaService()

    req = CategorySuggestionRequest(description="supermarket fruits")
    result = await suggest_category(
        db=session,  # type: ignore[arg-type]
        user_id=test_user.id,
        req=req,
        classifier=mock_clf,
        history_layer=hist,
        groq_client=mock_llm,
        quota_service=quota_svc,
    )

    assert result.source == "classifier"
    assert result.category_name == "Groceries"
    assert mock_llm.call_count == 0
    assert len(fake_db.ai_logs) == 0


# =====================================================================
# 5. Database Schema & Migration Verification
# =====================================================================


def test_ai_usage_log_model_schema() -> None:
    """Verify table definition, column types, foreign keys, and indexes."""
    table = AIUsageLog.__table__
    assert table.name == "ai_usage_log"

    col_names = {c.name for c in table.columns}
    expected_cols = {
        "id",
        "user_id",
        "feature",
        "provider",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
        "status",
        "error_message",
        "created_at",
    }
    assert expected_cols.issubset(col_names)

    # Check foreign key
    fk = next(iter(table.foreign_keys))
    assert fk.column.table.name == "users"
    assert fk.column.name == "id"
    assert fk.ondelete == "CASCADE"

    # Check compound index
    index_names = {idx.name for idx in table.indexes}
    assert "ix_ai_usage_log_user_feature_created" in index_names


def test_alembic_migration_006_metadata() -> None:
    """Verify Alembic migration 006 links cleanly to head 005."""
    migration_path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "006_create_ai_usage_log.py"
    )
    assert migration_path.exists()

    spec = importlib.util.spec_from_file_location("migration_006", migration_path)
    assert spec is not None and spec.loader is not None
    migration_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration_mod)

    assert migration_mod.revision == "006_create_ai_usage_log"
    assert migration_mod.down_revision == "005_create_category_suggestion_feedback"
    assert callable(migration_mod.upgrade)
    assert callable(migration_mod.downgrade)


# =====================================================================
# 6. Multi-Worker Distributed Concurrency & DDL Execution Tests
# =====================================================================


@pytest.mark.anyio
async def test_distributed_multi_worker_reservation_concurrency(
    monkeypatch: pytest.MonkeyPatch, fake_db: QuotaFakeDB, test_user: User
) -> None:
    """AC: When FastAPI runs with multiple workers, database-backed pending

    reservations block worker 2 even with zero shared in-memory state.
    """
    monkeypatch.setattr(settings, "AI_QUOTA_CATEGORIZE_DAILY", 1)

    # Two distinct service instances simulating separate worker processes
    worker1_service = AIQuotaService()
    worker2_service = AIQuotaService()

    worker1_session = QuotaFakeAsyncSession(fake_db)
    worker2_session = QuotaFakeAsyncSession(fake_db)

    # Worker 1 acquires reservation (writes pending row to DB)
    async with worker1_service.reserve(
        user_id=test_user.id,
        feature="categorize",
        db=worker1_session,  # type: ignore[arg-type]
        raise_on_exceeded=True,
    ) as w1_res:
        assert w1_res.allowed is True
        assert len(fake_db.ai_logs) == 1
        assert fake_db.ai_logs[0].status == "pending"

        # Worker 2 in a completely separate process tries to reserve for the same user
        with pytest.raises(HTTPException) as exc_info:
            await worker2_service.check_quota(
                user_id=test_user.id,
                feature="categorize",
                db=worker2_session,  # type: ignore[arg-type]
                raise_on_exceeded=True,
            )
        assert exc_info.value.status_code == 429
        assert exc_info.value.detail["code"] == "AI_QUOTA_EXCEEDED"

        # Worker 1 finalizes call
        await w1_res.finalize(status="success", latency_ms=105.0, db=worker1_session)  # type: ignore[arg-type]

    # After Worker 1 exits, DB has 1 success row
    assert len(fake_db.ai_logs) == 1
    assert fake_db.ai_logs[0].status == "success"

    # Worker 2 remains blocked because quota of 1 is fully consumed
    with pytest.raises(HTTPException) as exc_info:
        await worker2_service.check_quota(
            user_id=test_user.id,
            feature="categorize",
            db=worker2_session,  # type: ignore[arg-type]
            raise_on_exceeded=True,
        )
    assert exc_info.value.status_code == 429


@pytest.mark.anyio
async def test_unfinalized_reservation_rolls_back_to_error(
    fake_db: QuotaFakeDB, test_user: User
) -> None:
    """If a worker crashes or raises an exception during provider call,

    the pending reservation is marked as error so the slot is released.
    """
    service = AIQuotaService()
    session = QuotaFakeAsyncSession(fake_db)

    try:
        async with service.reserve(
            user_id=test_user.id,
            feature="categorize",
            db=session,  # type: ignore[arg-type]
            raise_on_exceeded=True,
        ):
            # Simulate unexpected crash before finalizing
            raise RuntimeError("Worker process network crash")
    except RuntimeError:
        pass

    assert len(fake_db.ai_logs) == 1
    # Pending row rolled back to error, freeing the user's quota slot
    assert fake_db.ai_logs[0].status == "error"
    assert "cancelled" in fake_db.ai_logs[0].error_message.lower()

    # Quota remains available for retry
    status_obj = await service.check_quota(
        user_id=test_user.id,
        feature="categorize",
        db=session,  # type: ignore[arg-type]
    )
    assert status_obj.allowed is True
    assert status_obj.remaining == 50


def test_genuine_database_engine_table_creation_and_ddl() -> None:
    """Verify genuine database engine execution of AIUsageLog table and indexes."""
    from sqlalchemy import create_engine, inspect

    engine = create_engine("sqlite:///:memory:")
    # Execute actual DDL create_all on tables
    User.__table__.create(engine)
    AIUsageLog.__table__.create(engine)

    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    assert "ai_usage_log" in table_names
    assert "users" in table_names

    col_info = {c["name"]: c for c in inspector.get_columns("ai_usage_log")}
    assert "id" in col_info
    assert "user_id" in col_info
    assert "feature" in col_info
    assert "provider" in col_info
    assert "model" in col_info
    assert "status" in col_info
    assert "prompt_tokens" in col_info
    assert "completion_tokens" in col_info
    assert "total_tokens" in col_info
    assert "latency_ms" in col_info
    assert "created_at" in col_info
