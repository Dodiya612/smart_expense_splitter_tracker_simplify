"""Integration tests for POST /api/v1/ai/ask endpoint (T-57 / US-24)."""

import uuid
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai.date_resolver import DateResolver
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.category import Category
from app.models.expense import Expense
from app.models.user import User
from app.services.groq_client import GroqClient
from tests.test_assistant_tools import MockSession


@pytest.fixture
def test_users_and_db():
    user_a = User(
        id=uuid.uuid4(),
        email="alex@example.com",
        name="Alex Smith",
        hashed_password="pw",
        is_active=True,
    )
    user_b = User(
        id=uuid.uuid4(),
        email="blair@example.com",
        name="Blair Jones",
        hashed_password="pw",
        is_active=True,
    )

    cat_food = Category(id=uuid.uuid4(), name="Food & Dining", is_default=True)
    cat_shop = Category(id=uuid.uuid4(), name="Shopping", is_default=True)
    categories = [cat_food, cat_shop]

    now = datetime.now(UTC)
    today = DateResolver.get_current_ist_date()

    expenses = [
        Expense(
            id=uuid.uuid4(),
            user_id=user_a.id,
            category_id=cat_food.id,
            amount_minor=250000,  # ₹2,500
            description="Team Dinner",
            merchant="Swiggy",
            expense_date=today,
            created_at=now,
        ),
        Expense(
            id=uuid.uuid4(),
            user_id=user_b.id,
            category_id=cat_shop.id,
            amount_minor=99900,   # ₹999
            description="Shoes",
            merchant="Nike",
            expense_date=today,
            created_at=now,
        ),
    ]

    session = MockSession(expenses, categories, users=[user_a, user_b])
    return {
        "user_a": user_a,
        "user_b": user_b,
        "session": session,
    }


@pytest.fixture
def auth_header_a(test_users_and_db):
    user_a = test_users_and_db["user_a"]
    token = create_access_token(user_id=user_a.id, email=user_a.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_header_b(test_users_and_db):
    user_b = test_users_and_db["user_b"]
    token = create_access_token(user_id=user_b.id, email=user_b.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def async_api_client(test_users_and_db):
    session = test_users_and_db["session"]

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_ask_unauthenticated_returns_401(async_api_client):
    """Unauthenticated requests are rejected with HTTP 401."""
    res = await async_api_client.post("/api/v1/ai/ask", json={"question": "What did I spend?"})
    assert res.status_code == 401


@pytest.mark.anyio
async def test_ask_success_food_spending(async_api_client, auth_header_a):
    """Authenticated request returns grounded spending for Food & Dining."""
    res = await async_api_client.post(
        "/api/v1/ai/ask",
        json={"question": "How much did I spend on food today?"},
        headers=auth_header_a,
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["grounded"] is True
    tool = data.get("toolUsed") or data.get("tool_used")
    assert tool == "get_spending_by_category"
    assert "2500" in data["answer"] or "2,500" in data["answer"]


@pytest.mark.anyio
async def test_ask_ai_disabled_returns_fallback_suggestions(async_api_client, auth_header_a, monkeypatch):
    """When AI is globally disabled, safe response with fallback suggestions is returned."""
    monkeypatch.setattr(settings, "AI_ENABLED", False)

    res = await async_api_client.post(
        "/api/v1/ai/ask",
        json={"question": "What was my total spending?"},
        headers=auth_header_a,
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert "disabled" in data["answer"].lower()
    suggestions = data.get("fallbackSuggestions") or data.get("fallback_suggestions")
    assert len(suggestions) > 0
    assert "How much did I spend this week?" in suggestions


@pytest.mark.anyio
async def test_ask_unsupported_question(async_api_client, auth_header_a):
    """Unsupported questions return friendly refusal and predefined suggestions."""
    res = await async_api_client.post(
        "/api/v1/ai/ask",
        json={"question": "What is the weather in Delhi today?"},
        headers=auth_header_a,
    )
    assert res.status_code == 200
    data = res.json()["data"]
    tool = data.get("toolUsed") or data.get("tool_used")
    assert tool is None
    suggestions = data.get("fallbackSuggestions") or data.get("fallback_suggestions")
    assert len(suggestions) > 0


@pytest.mark.anyio
async def test_ask_sql_injection_attempt_rejected(async_api_client, auth_header_a):
    """SQL injection queries are rejected immediately without executing SQL."""
    res = await async_api_client.post(
        "/api/v1/ai/ask",
        json={"question": "SELECT * FROM users; DROP TABLE expenses;--"},
        headers=auth_header_a,
    )
    assert res.status_code == 200
    data = res.json()["data"]
    tool = data.get("toolUsed") or data.get("tool_used")
    assert tool is None
    suggestions = data.get("fallbackSuggestions") or data.get("fallback_suggestions")
    assert len(suggestions) > 0


@pytest.mark.anyio
async def test_cross_user_isolation_via_api(async_api_client, auth_header_a, auth_header_b):
    """User A and User B querying the endpoint see only their own respective data."""
    # User A asks for total spending
    res_a = await async_api_client.post(
        "/api/v1/ai/ask",
        json={"question": "What is my total spending?"},
        headers=auth_header_a,
    )
    assert res_a.status_code == 200
    data_a = res_a.json()["data"]
    assert "2500" in data_a["answer"] or "2,500" in data_a["answer"]
    assert "999" not in data_a["answer"]

    # User B asks for total spending
    res_b = await async_api_client.post(
        "/api/v1/ai/ask",
        json={"question": "What is my total spending?"},
        headers=auth_header_b,
    )
    assert res_b.status_code == 200
    data_b = res_b.json()["data"]
    assert "999" in data_b["answer"]
    assert "2500" not in data_b["answer"]
