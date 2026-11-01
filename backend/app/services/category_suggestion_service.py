"""Category suggestion service orchestrating user history, local ML, and Groq LLM.

Implements the three-layer category suggestion pipeline:
  Layer 1 - Personalized User History Layer (Bayesian blending)
  Layer 2 - Local ML Classifier (TF-IDF + Logistic Regression, T-22)
  Layer 3 - Groq LLM Fallback (triggered strictly when confidence < 0.60)
            with safe deterministic rule fallback (KeywordRuleBaseline)

Also handles:
  - Model caching (loads once at startup)
  - Category name to UUID resolution via the categories database table
  - Persistent feedback storage and synchronization with the in-memory history layer
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from ml.classifier import CategoryClassifier
from ml.fallback_rules import KeywordRuleBaseline
from ml.history import UserHistoryLayer
from ml.merchant_normalizer import MerchantNormalizer
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.quota import AIQuotaService, get_quota_service, log_ai_usage
from app.core.config import settings
from app.models.category import Category
from app.models.category_feedback import CategorySuggestionFeedback
from app.schemas.category_suggestion import (
    CategoryFeedbackData,
    CategoryFeedbackRequest,
    CategorySuggestionData,
    CategorySuggestionRequest,
)
from app.services.groq_client import GroqClient

logger = logging.getLogger(__name__)

# Singletons for model and history layer
_CLASSIFIER: CategoryClassifier | None = None
_HISTORY_LAYER: UserHistoryLayer = UserHistoryLayer()
_GROQ_CLIENT: GroqClient | None = None
_LOADED_FEEDBACK_IDS: set[uuid.UUID] = set()

# Model path resolution: <repo_root>/ml/models/category_model.joblib
REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_PATH = REPO_ROOT / "ml" / "models" / "category_model.joblib"


def reset_user_history_cache() -> None:
    """Clear in-memory user history and loaded record tracking (for tests and resets)."""
    _LOADED_FEEDBACK_IDS.clear()
    _HISTORY_LAYER.clear_all()


async def _load_history_from_session(
    session: AsyncSession,
    history_layer: UserHistoryLayer,
) -> int:
    """Internal helper to load unindexed feedback from a given active AsyncSession."""
    stmt = (
        select(
            CategorySuggestionFeedback.id,
            CategorySuggestionFeedback.user_id,
            CategorySuggestionFeedback.merchant,
            CategorySuggestionFeedback.description,
            Category.name.label("chosen_category_name"),
        )
        .join(Category, CategorySuggestionFeedback.chosen_category_id == Category.id)
        .order_by(CategorySuggestionFeedback.created_at.asc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    loaded = 0
    for row in rows:
        if row.id in _LOADED_FEEDBACK_IDS:
            continue

        _LOADED_FEEDBACK_IDS.add(row.id)
        history_layer.record_transaction(
            user_id=str(row.user_id),
            category=row.chosen_category_name,
            merchant=row.merchant,
            description=row.description,
        )
        loaded += 1

    return loaded


async def restore_user_history(
    session: AsyncSession | None = None,
    history_layer: UserHistoryLayer | None = None,
) -> int:
    """Asynchronously load previously recorded category feedback from PostgreSQL.

    Preserves user isolation, avoids duplicate counting on multiple invocations,
    and handles startup database errors safely without crashing.
    """
    hist = history_layer if history_layer is not None else get_user_history_layer()

    try:
        if session is not None:
            return await _load_history_from_session(session, hist)

        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db_session:
            return await _load_history_from_session(db_session, hist)
    except (SQLAlchemyError, OSError, RuntimeError) as exc:
        logger.warning(
            "Startup database error during user history restoration: %s. Continuing with clean history.",
            exc,
        )
        return 0


def get_category_classifier(model_path: Path | str | None = None) -> CategoryClassifier:
    """Retrieve or lazily initialize the singleton CategoryClassifier instance."""
    global _CLASSIFIER
    if _CLASSIFIER is None:
        target_path = Path(model_path) if model_path else MODEL_PATH
        if not target_path.exists():
            raise RuntimeError(
                f"T-22 Category model artifact not found at {target_path}. "
                "Ensure category_model.joblib exists."
            )
        logger.info("Loading CategoryClassifier from %s", target_path)
        _CLASSIFIER = CategoryClassifier.load(target_path)
    return _CLASSIFIER


def set_category_classifier(classifier: CategoryClassifier | None) -> None:
    """Set or reset the singleton classifier (useful for tests)."""
    global _CLASSIFIER
    _CLASSIFIER = classifier


def get_user_history_layer() -> UserHistoryLayer:
    """Retrieve the singleton UserHistoryLayer instance."""
    return _HISTORY_LAYER


def get_groq_client() -> GroqClient:
    """Retrieve or lazily initialize the singleton GroqClient."""
    global _GROQ_CLIENT
    if _GROQ_CLIENT is None:
        _GROQ_CLIENT = GroqClient()
    return _GROQ_CLIENT


def set_groq_client(client: GroqClient | None) -> None:
    """Set or reset the singleton GroqClient (useful for tests)."""
    global _GROQ_CLIENT
    _GROQ_CLIENT = client


async def resolve_category_uuid(
    db: AsyncSession,
    user_id: uuid.UUID,
    category_name: str,
) -> tuple[uuid.UUID, str]:
    """Resolve a canonical category name to its database UUID.

    Prefers user-owned custom categories matching the name, then default categories.
    Falls back to the default 'Other' category if no match is found.

    Returns:
        Tuple of (category_id, canonical_db_name).
    """
    stmt = select(Category).where(
        or_(Category.is_default == True, Category.owner_id == user_id)
    )
    result = await db.execute(stmt)
    available_categories = list(result.scalars().all())

    target_clean = category_name.strip().lower()

    # 1. Check user-owned custom categories first
    for cat in available_categories:
        if cat.owner_id == user_id and cat.name.strip().lower() == target_clean:
            return cat.id, cat.name

    # 2. Check default system categories
    for cat in available_categories:
        if cat.is_default and cat.name.strip().lower() == target_clean:
            return cat.id, cat.name

    # 3. Fallback to default 'Other' category
    for cat in available_categories:
        if cat.is_default and cat.name.strip().lower() == "other":
            return cat.id, cat.name

    # 4. If database is completely unseeded (e.g. mock test DB without 'Other'), return fallback UUID
    fallback_id = (
        available_categories[0].id
        if available_categories
        else uuid.UUID("00000000-0000-4000-8000-000000000012")
    )
    return fallback_id, category_name


async def suggest_category(
    db: AsyncSession,
    user_id: uuid.UUID,
    req: CategorySuggestionRequest,
    classifier: CategoryClassifier | None = None,
    history_layer: UserHistoryLayer | None = None,
    groq_client: GroqClient | None = None,
    quota_service: AIQuotaService | None = None,
) -> CategorySuggestionData:
    """Execute the three-layer suggestion pipeline.

    1. Layer 1 (User History) & Layer 2 (Local ML Classifier):
       Computes prediction and Bayesian-blended confidence using T-22 model.
    2. Layer 3 (Groq LLM Fallback):
       Triggered strictly when local confidence < 0.60.
       Checks global AI_ENABLED switch and daily categorize quota.
       Falls back to KeywordRuleBaseline if Groq is unconfigured, disabled, quota-exhausted, or fails.
    3. Category Name to UUID Resolution:
       Maps category name to database category UUID.
    """
    clf = classifier or get_category_classifier()
    hist = history_layer if history_layer is not None else get_user_history_layer()
    llm = groq_client or get_groq_client()
    qs = quota_service or get_quota_service()

    norm_merchant = MerchantNormalizer.normalize_merchant(req.merchant)

    # 1. Run local prediction with history layer
    local_result: dict[str, Any] = clf.predict_single(
        description=req.description,
        merchant=req.merchant,
        user_id=str(user_id),
        history_layer=hist,
    )

    predicted_cat: str = local_result.get("category", "Other")
    confidence: float = float(local_result.get("confidence", 0.0))

    # Determine if user history influenced this prediction
    user_hist_counts = hist.get_merchant_history(
        str(user_id), req.merchant or norm_merchant
    )
    is_history_match = bool(
        user_hist_counts and predicted_cat in user_hist_counts and sum(user_hist_counts.values()) >= 1
    )

    source: str = "history" if is_history_match else "classifier"

    # 2. Check 60% confidence threshold for Groq LLM fallback
    # Confidence >= 0.60: never call Groq
    # Confidence < 0.60: call Groq if configured, enabled, and within daily quota, else safe rule baseline
    if confidence < 0.60:
        llm_cat: str | None = None

        if settings.AI_ENABLED and llm.is_configured():
            async with qs.reserve(
                user_id=user_id,
                feature="categorize",
                db=db,
                provider="groq",
                model=settings.GROQ_MODEL,
                raise_on_exceeded=False,
            ) as reservation:
                if reservation.allowed:
                    start_time = time.perf_counter()
                    try:
                        llm_cat = await llm.classify_category(
                            description=req.description,
                            merchant=req.merchant,
                        )
                        latency_ms = (time.perf_counter() - start_time) * 1000.0

                        await reservation.finalize(
                            status="success" if llm_cat is not None else "error",
                            error_message=None if llm_cat is not None else "Groq returned unparseable or empty response",
                            latency_ms=latency_ms,
                            db=db,
                        )
                    except Exception as exc:  # noqa: BLE001 - Resilient fallback to rules on unexpected provider error
                        latency_ms = (time.perf_counter() - start_time) * 1000.0
                        logger.warning("Groq classification invocation failed: %s", exc)
                        await reservation.finalize(
                            status="error",
                            error_message=str(exc),
                            latency_ms=latency_ms,
                            db=db,
                        )
                else:
                    logger.info(
                        "AI categorization quota exceeded or disabled for user %s (%s/%s used). Falling back to rule baseline.",
                        user_id,
                        reservation.status.used_today,
                        reservation.status.daily_limit,
                    )
                    await log_ai_usage(
                        user_id=user_id,
                        feature="categorize",
                        provider="groq",
                        model=settings.GROQ_MODEL,
                        status="quota_exceeded",
                        error_message="Daily quota exceeded; fallback to rule baseline",
                        db=db,
                    )

        if llm_cat is not None:
            predicted_cat = llm_cat
            confidence = 0.70  # Advisory confidence for LLM prediction
            source = "llm"
        else:
            # Deterministic rule baseline fallback
            rule_cat = KeywordRuleBaseline.predict(
                description=req.description,
                merchant=req.merchant,
            )
            predicted_cat = rule_cat
            confidence = max(confidence, 0.50)
            source = "rule_fallback"

    # 3. Determine confirmation requirement
    # User confirmation is required if confidence < 0.85 or source is LLM / rule fallback
    requires_confirmation = (confidence < 0.85) or (source in ("llm", "rule_fallback"))

    # 4. Resolve category name to database category UUID
    category_id, resolved_name = await resolve_category_uuid(
        db=db,
        user_id=user_id,
        category_name=predicted_cat,
    )

    return CategorySuggestionData(
        suggested_category_id=category_id,
        category_id=category_id,
        category_name=resolved_name,
        confidence=round(confidence, 4),
        requires_confirmation=requires_confirmation,
        source=source,  # type: ignore[arg-type]
    )


async def record_feedback(
    db: AsyncSession,
    user_id: uuid.UUID,
    feedback_req: CategoryFeedbackRequest,
    history_layer: UserHistoryLayer | None = None,
) -> CategoryFeedbackData:
    """Record user feedback and update user history after successful persistence."""
    hist = history_layer if history_layer is not None else get_user_history_layer()

    # 1. Validate chosen_category_id exists and is accessible to user
    stmt = select(Category).where(
        Category.id == feedback_req.chosen_category_id,
        or_(Category.is_default == True, Category.owner_id == user_id),
    )
    result = await db.execute(stmt)
    chosen_cat = result.scalar_one_or_none()

    if chosen_cat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CATEGORY_NOT_FOUND",
                "message": f"Category '{feedback_req.chosen_category_id}' does not exist or is not accessible.",
            },
        )

    # 2. Persist feedback entity
    feedback_entry = CategorySuggestionFeedback(
        user_id=user_id,
        description=feedback_req.description,
        merchant=feedback_req.merchant,
        suggested_category_id=feedback_req.suggested_category_id,
        chosen_category_id=feedback_req.chosen_category_id,
        confidence=feedback_req.confidence,
        source=feedback_req.source,
        accepted=feedback_req.accepted,
    )
    db.add(feedback_entry)
    await db.commit()
    await db.refresh(feedback_entry)

    # 3. Update in-memory user history only after successful DB commit
    _LOADED_FEEDBACK_IDS.add(feedback_entry.id)
    hist.record_transaction(
        user_id=str(user_id),
        category=chosen_cat.name,
        merchant=feedback_req.merchant,
        description=feedback_req.description,
    )

    logger.info(
        "Recorded suggestion feedback for user %s: suggested=%s, chosen=%s (%s), accepted=%s",
        user_id,
        feedback_req.suggested_category_id,
        feedback_req.chosen_category_id,
        chosen_cat.name,
        feedback_req.accepted,
    )

    return CategoryFeedbackData(
        success=True,
        message="Feedback recorded successfully",
    )
