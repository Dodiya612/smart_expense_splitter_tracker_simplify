"""Burst limits on the AI routes (T-39), on top of the existing daily quotas.

Reuses the in-memory API fixtures from tests/test_category_suggestion_api.py. The limit sits on
the route, so it covers every execution path behind it (history, the local classifier, the LLM
fallback), including the local classifier, which has no daily quota.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from tests import rate_limit_fakes as fakes
from tests import test_category_suggestion_api as ai

fake_db = ai.fake_db
test_user = ai.test_user
auth_headers = ai.auth_headers
client = ai.client

SUGGEST = {"description": "Starbucks cold brew coffee", "merchant": "Starbucks"}


def feedback_body(fake_db) -> dict:
    category = next(c for c in fake_db.categories.values() if c.name == "Food & Dining")
    return {
        "description": "Swiggy order biryani",
        "merchant": "Swiggy",
        "suggestedCategoryId": str(category.id),
        "chosenCategoryId": str(category.id),
        "confidence": 0.94,
        "source": "classifier",
        "accepted": True,
    }


@pytest.mark.anyio
async def test_suggestion_burst_is_limited_per_user_with_a_retry_time(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_AI_BURST_USER_MAX", 2)
    for _ in range(2):
        assert (await client.post("/api/v1/ai/category-suggestion", json=SUGGEST, headers=auth_headers)).status_code == 200
    blocked = await client.post("/api/v1/ai/category-suggestion", json=SUGGEST, headers=auth_headers)
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED" and body["isRetryable"] is True
    assert 0 < int(blocked.headers["retry-after"]) <= 60
    fakes.advance(60)
    assert (await client.post("/api/v1/ai/category-suggestion", json=SUGGEST, headers=auth_headers)).status_code == 200


@pytest.mark.anyio
async def test_the_suggestions_alias_shares_the_same_burst_budget(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_AI_BURST_USER_MAX", 2)
    assert (await client.post("/api/v1/ai/category-suggestion", json=SUGGEST, headers=auth_headers)).status_code == 200
    assert (await client.post("/api/v1/ai/suggestions", json=SUGGEST, headers=auth_headers)).status_code == 200
    # Switching routes cannot dodge the limit.
    assert (await client.post("/api/v1/ai/suggestions", json=SUGGEST, headers=auth_headers)).status_code == 429
    assert (await client.post("/api/v1/ai/category-suggestion", json=SUGGEST, headers=auth_headers)).status_code == 429


@pytest.mark.anyio
async def test_feedback_routes_have_their_own_limit_and_do_not_use_the_suggestion_budget(
    client, fake_db, auth_headers, monkeypatch
):
    monkeypatch.setattr(settings, "RATE_LIMIT_AI_BURST_USER_MAX", 1)
    monkeypatch.setattr(settings, "RATE_LIMIT_AI_FEEDBACK_USER_MAX", 2)
    assert (await client.post("/api/v1/ai/category-suggestion", json=SUGGEST, headers=auth_headers)).status_code == 200
    assert (await client.post("/api/v1/ai/category-suggestion", json=SUGGEST, headers=auth_headers)).status_code == 429
    body = feedback_body(fake_db)
    assert (await client.post("/api/v1/ai/category-suggestion/feedback", json=body, headers=auth_headers)).status_code == 200
    assert (await client.post("/api/v1/ai/suggestions/feedback", json=body, headers=auth_headers)).status_code == 200
    assert (await client.post("/api/v1/ai/category-suggestion/feedback", json=body, headers=auth_headers)).status_code == 429


@pytest.mark.anyio
async def test_unauthenticated_ai_requests_get_401_and_spend_no_budget(client):
    for _ in range(3):
        assert (await client.post("/api/v1/ai/category-suggestion", json=SUGGEST)).status_code in (401, 403)
    assert fakes.scopes() == set()


@pytest.mark.anyio
async def test_the_burst_limit_does_not_replace_the_daily_quota_error(client, auth_headers):
    # With defaults (20/min) a few calls are fine; the daily quota keeps its own 429 code.
    for _ in range(3):
        assert (await client.post("/api/v1/ai/category-suggestion", json=SUGGEST, headers=auth_headers)).status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/api/v1/ai/category-suggestion", "/api/v1/ai/suggestions"])
async def test_suggestions_fail_closed_when_the_limiter_is_unavailable(client, auth_headers, path):
    fakes.set_failing(True)
    r = await client.post(path, json=SUGGEST, headers=auth_headers)
    assert r.status_code == 503
    body = r.json()
    assert body["code"] == "RATE_LIMITER_UNAVAILABLE" and body["isRetryable"] is True
    assert "data" not in body  # the classifier / LLM pipeline never ran
    fakes.set_failing(False)
    assert (await client.post(path, json=SUGGEST, headers=auth_headers)).status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path", ["/api/v1/ai/category-suggestion/feedback", "/api/v1/ai/suggestions/feedback"]
)
async def test_feedback_fails_closed_and_records_nothing_when_the_limiter_is_unavailable(
    client, fake_db, auth_headers, path
):
    fakes.set_failing(True)
    r = await client.post(path, json=feedback_body(fake_db), headers=auth_headers)
    assert r.status_code == 503 and r.json()["code"] == "RATE_LIMITER_UNAVAILABLE"
    assert fake_db.feedback == []
    fakes.set_failing(False)
    assert (await client.post(path, json=feedback_body(fake_db), headers=auth_headers)).status_code == 200
    assert len(fake_db.feedback) == 1
