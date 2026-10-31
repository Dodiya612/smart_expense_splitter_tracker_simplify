"""Integration tests for AI Category Suggestion and Feedback API endpoints.

Tests:
- Unauthenticated requests return 401 Unauthorized
- Valid suggestion returns established response structure and HTTP 200
- Validation errors on empty/whitespace description return 422
- Suggestion returns expected category matching model prediction
- Unauthenticated feedback returns 401 Unauthorized
- Valid feedback persists with authenticated user ID
- Manual override (accepted=false) is accepted and recorded properly
- Invalid/non-existent chosen category returns 404
- Feedback is strictly isolated to current_user (cannot spoof another user)
- Alias endpoints /api/v1/ai/suggestions work
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.category import Category
from app.models.category_feedback import CategorySuggestionFeedback
from app.models.user import User
from app.services.groq_client import CANONICAL_CATEGORIES
from httpx import ASGITransport, AsyncClient


class ApiFakeDB:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}
        self.categories: dict[uuid.UUID, Category] = {}
        self.feedback: list[CategorySuggestionFeedback] = []


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


class ApiFakeAsyncSession:
    def __init__(self, db: ApiFakeDB) -> None:
        self.db = db
        self.pending: list[Any] = []

    def add(self, obj: Any) -> None:
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        self.pending.append(obj)

    async def commit(self) -> None:
        for obj in self.pending:
            if isinstance(obj, CategorySuggestionFeedback):
                self.db.feedback.append(obj)
        self.pending.clear()

    async def refresh(self, obj: Any) -> None:
        pass

    async def rollback(self) -> None:
        self.pending.clear()

    async def execute(self, stmt: Any) -> FakeResult:
        sql_str = str(stmt).lower()
        params = stmt.compile().params

        # 1. SELECT User
        if "from users" in sql_str:
            id_val = next((v for k, v in params.items() if "id" in k), None)
            if id_val is not None:
                matched_users = [u for u in self.db.users.values() if u.id == id_val]
                return FakeResult(matched_users)
            return FakeResult(list(self.db.users.values()))

        # 2. SELECT Category
        if "from categories" in sql_str:
            if "categories.id =" in sql_str:
                target_id = params.get("id_1") or params.get("id")
                matched = [c for c in self.db.categories.values() if c.id == target_id]
                return FakeResult(matched)

            user_id = params.get("owner_id_1") or params.get("owner_id")
            matched = [
                c
                for c in self.db.categories.values()
                if c.is_default or (user_id is not None and c.owner_id == user_id)
            ]
            return FakeResult(matched)

        return FakeResult([])


@pytest.fixture
def fake_db() -> ApiFakeDB:
    db = ApiFakeDB()
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
def test_user(fake_db: ApiFakeDB) -> User:
    user = User(
        id=uuid.uuid4(),
        email="ai_test@example.com",
        name="AI Tester",
        hashed_password="hashed_password",
        is_active=True,
    )
    fake_db.users[user.id] = user
    return user


@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    token = create_access_token(user_id=test_user.id, email=test_user.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def client(fake_db: ApiFakeDB) -> AsyncClient:
    async def override_get_db():
        yield ApiFakeAsyncSession(fake_db)

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_suggest_category_unauthenticated_returns_401(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/ai/category-suggestion",
        json={"description": "Coffee at Starbucks"},
    )
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


@pytest.mark.anyio
async def test_suggest_category_empty_description_returns_422(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # Empty string
    res = await client.post(
        "/api/v1/ai/category-suggestion",
        json={"description": ""},
        headers=auth_headers,
    )
    assert res.status_code == 422
    assert res.json()["code"] == "VALIDATION_ERROR"

    # Whitespace only
    res_ws = await client.post(
        "/api/v1/ai/category-suggestion",
        json={"description": "    "},
        headers=auth_headers,
    )
    assert res_ws.status_code == 422
    assert res_ws.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.anyio
async def test_suggest_category_valid_response_structure(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    res = await client.post(
        "/api/v1/ai/category-suggestion",
        json={"description": "Starbucks cold brew coffee", "merchant": "Starbucks"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()["data"]

    # Verify both suggestedCategoryId and categoryId are present in camelCase wire format
    assert "suggestedCategoryId" in data
    assert "categoryId" in data
    assert data["suggestedCategoryId"] == data["categoryId"]
    assert data["categoryName"] == "Food & Dining"
    assert isinstance(data["confidence"], float)
    assert 0.0 <= data["confidence"] <= 1.0
    assert "requiresConfirmation" in data
    assert isinstance(data["requiresConfirmation"], bool)
    assert data["source"] in ("history", "classifier", "llm", "rule_fallback")


@pytest.mark.anyio
async def test_suggest_category_alias_route(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    res = await client.post(
        "/api/v1/ai/suggestions",
        json={"description": "Uber ride to airport"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["data"]["categoryName"] == "Travel & Transport"


@pytest.mark.anyio
async def test_feedback_unauthenticated_returns_401(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/ai/category-suggestion/feedback",
        json={
            "description": "Starbucks",
            "suggestedCategoryId": "00000000-0000-4000-8000-000000000001",
            "chosenCategoryId": "00000000-0000-4000-8000-000000000001",
            "accepted": True,
        },
    )
    assert res.status_code == 401


@pytest.mark.anyio
async def test_feedback_persists_accepted_suggestion(
    client: AsyncClient,
    fake_db: ApiFakeDB,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    food_cat = next(c for c in fake_db.categories.values() if c.name == "Food & Dining")

    payload = {
        "description": "Swiggy order biryani",
        "merchant": "Swiggy",
        "suggestedCategoryId": str(food_cat.id),
        "chosenCategoryId": str(food_cat.id),
        "confidence": 0.94,
        "source": "classifier",
        "accepted": True,
    }

    res = await client.post(
        "/api/v1/ai/category-suggestion/feedback",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["data"]["success"] is True

    # Verify persisted in database
    assert len(fake_db.feedback) == 1
    fb = fake_db.feedback[0]
    assert fb.user_id == test_user.id
    assert fb.accepted is True
    assert fb.suggested_category_id == food_cat.id
    assert fb.chosen_category_id == food_cat.id


@pytest.mark.anyio
async def test_feedback_persists_manual_override(
    client: AsyncClient,
    fake_db: ApiFakeDB,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    food_cat = next(c for c in fake_db.categories.values() if c.name == "Food & Dining")
    ent_cat = next(c for c in fake_db.categories.values() if c.name == "Entertainment")

    payload = {
        "description": "Prime subscription",
        "merchant": "Amazon Prime",
        "suggestedCategoryId": str(food_cat.id),
        "chosenCategoryId": str(ent_cat.id),  # User explicitly overrode
        "confidence": 0.65,
        "source": "classifier",
        "accepted": False,
    }

    res = await client.post(
        "/api/v1/ai/category-suggestion/feedback",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["data"]["success"] is True

    assert len(fake_db.feedback) == 1
    fb = fake_db.feedback[0]
    assert fb.user_id == test_user.id
    assert fb.accepted is False
    assert fb.suggested_category_id == food_cat.id
    assert fb.chosen_category_id == ent_cat.id


@pytest.mark.anyio
async def test_feedback_rejects_nonexistent_category(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    non_existent = str(uuid.uuid4())
    payload = {
        "description": "Payment",
        "suggestedCategoryId": non_existent,
        "chosenCategoryId": non_existent,
        "accepted": True,
    }
    res = await client.post(
        "/api/v1/ai/category-suggestion/feedback",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 404
    assert res.json()["code"] == "CATEGORY_NOT_FOUND"


@pytest.mark.anyio
async def test_feedback_user_id_strictly_from_jwt(
    client: AsyncClient,
    fake_db: ApiFakeDB,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Ensure client cannot tamper with or supply another user's ID."""
    spoofed_user_id = str(uuid.uuid4())
    food_cat = next(c for c in fake_db.categories.values() if c.name == "Food & Dining")

    payload = {
        "description": "Dinner",
        "suggestedCategoryId": str(food_cat.id),
        "chosenCategoryId": str(food_cat.id),
        "accepted": True,
        "userId": spoofed_user_id,
        "user_id": spoofed_user_id,
    }

    res = await client.post(
        "/api/v1/ai/category-suggestion/feedback",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 200
    # Authenticated user ID was used, not spoofed_user_id
    assert fake_db.feedback[0].user_id == test_user.id
    assert fake_db.feedback[0].user_id != uuid.UUID(spoofed_user_id)
