# ruff: noqa: F811
"""Tests for T-37 / US-15 Search and Filtering functionality."""

import uuid
from datetime import UTC, datetime

import pytest

from app.models.category import Category
from tests.test_expenses import (  # noqa: F401
    async_client,
    auth_headers,
    fake_db,
    other_auth_headers,
    other_user,
    test_user,
)


@pytest.mark.anyio
async def test_search_and_filter_expenses(
    async_client, auth_headers, other_auth_headers, fake_db
):
    cat_food = "00000000-0000-4000-8000-000000000001"
    cat_travel = "00000000-0000-4000-8000-000000000003"

    # Seed Travel category in fake_db
    cat_travel_obj = Category(
        id=uuid.UUID(cat_travel),
        name="Travel",
        is_default=True,
        owner_id=None,
        created_at=datetime.now(UTC),
    )
    fake_db.categories[cat_travel_obj.id] = cat_travel_obj

    # 1. Seed test expenses for authenticated user
    create_res1 = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 25000,
            "description": "Team Swiggy Lunch",
            "merchant": "Swiggy",
            "notes": "Biryani treats",
            "payment_mode": "upi",
            "category_id": cat_food,
            "expense_date": "2026-11-01",
        },
        headers=auth_headers,
    )
    assert create_res1.status_code == 201

    create_res2 = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 85000,
            "description": "Flight Ticket to Delhi",
            "merchant": "IndiGo",
            "notes": "Conference travel",
            "payment_mode": "card",
            "category_id": cat_travel,
            "expense_date": "2026-11-02",
        },
        headers=auth_headers,
    )
    assert create_res2.status_code == 201

    create_res3 = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 15000,
            "description": "Uber Ride to Airport",
            "merchant": "Uber",
            "notes": "Fast cab",
            "payment_mode": "cash",
            "category_id": cat_travel,
            "expense_date": "2026-11-03",
        },
        headers=auth_headers,
    )
    assert create_res3.status_code == 201

    # 2. Search matches notes ("Biryani")
    res_notes = await async_client.get(
        "/api/v1/expenses?q=Biryani", headers=auth_headers
    )
    assert res_notes.status_code == 200
    data_notes = res_notes.json()["data"]
    assert len(data_notes) == 1
    assert data_notes[0]["merchant"] == "Swiggy"

    # 3. Search matches description ("Flight")
    res_desc = await async_client.get("/api/v1/expenses?q=Flight", headers=auth_headers)
    assert res_desc.status_code == 200
    assert len(res_desc.json()["data"]) == 1
    assert res_desc.json()["data"][0]["merchant"] == "IndiGo"

    # 4. Search matches merchant ("Uber")
    res_merch = await async_client.get("/api/v1/expenses?q=Uber", headers=auth_headers)
    assert res_merch.status_code == 200
    assert len(res_merch.json()["data"]) == 1
    assert res_merch.json()["data"][0]["description"] == "Uber Ride to Airport"

    # 5. Filter by payment_mode ("card")
    res_card = await async_client.get(
        "/api/v1/expenses?payment_mode=card", headers=auth_headers
    )
    assert res_card.status_code == 200
    assert len(res_card.json()["data"]) == 1
    assert (
        res_card.json()["data"][0].get("paymentMode") == "card"
        or res_card.json()["data"][0].get("payment_mode") == "card"
    )

    # 6. Filter by amount range (min_amount=20000, max_amount=30000)
    res_range = await async_client.get(
        "/api/v1/expenses?min_amount=20000&max_amount=30000", headers=auth_headers
    )
    assert res_range.status_code == 200
    assert len(res_range.json()["data"]) == 1
    amt = res_range.json()["data"][0].get("amountMinor") or res_range.json()["data"][
        0
    ].get("amount_minor")
    assert amt == 25000

    # 7. Combined filter (category=travel AND payment_mode=card AND min_amount=50000)
    res_combined = await async_client.get(
        f"/api/v1/expenses?category_id={cat_travel}&payment_mode=card&min_amount=50000",
        headers=auth_headers,
    )
    assert res_combined.status_code == 200
    assert len(res_combined.json()["data"]) == 1
    assert res_combined.json()["data"][0]["merchant"] == "IndiGo"

    # 8. Zero-result query returns 200 with empty data array and total=0
    res_zero = await async_client.get(
        "/api/v1/expenses?q=NonExistentKeyword", headers=auth_headers
    )
    assert res_zero.status_code == 200
    assert len(res_zero.json()["data"]) == 0
    assert res_zero.json()["meta"]["total"] == 0

    # 9. Tenant Isolation: Other user querying cannot see test_user's expenses
    res_other = await async_client.get(
        "/api/v1/expenses?q=Biryani", headers=other_auth_headers
    )
    assert res_other.status_code == 200
    assert len(res_other.json()["data"]) == 0
    assert res_other.json()["meta"]["total"] == 0

    # 10. Validation error if min_amount > max_amount
    res_invalid_range = await async_client.get(
        "/api/v1/expenses?min_amount=50000&max_amount=10000", headers=auth_headers
    )
    assert res_invalid_range.status_code == 422
