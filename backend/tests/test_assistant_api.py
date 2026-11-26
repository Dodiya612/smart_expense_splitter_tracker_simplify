"""POST /api/v1/ai/ask (T-57 / US-24): auth, limits, quota, model handling and response shape.

No database: the signed-in user is loaded from a tiny fake session and the tools
read fixed service figures (tests/assistant_fakes.py). The real Groq API is
never called; tests/test_assistant_eval_pg.py covers real PostgreSQL.
"""

import json
import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai import assistant_service, tools
from app.ai.fallbacks import SUGGESTIONS
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from tests import rate_limit_fakes
from tests.assistant_fakes import FakeQuota, FakeServices, StubLLM, UserOnlySession

ASK = "/api/v1/ai/ask"
LAST_WEEK = {"tool": "spend_total", "slots": {"period": {"date_range": "last_week"}}}
ALEX = User(id=uuid.uuid4(), email="alex@example.com", name="Alex Smith", hashed_password="x", is_active=True)
AUTH = {"Authorization": f"Bearer {create_access_token(user_id=ALEX.id, email=ALEX.email)}"}


@pytest.fixture
async def client():
    async def override_get_db():
        yield UserOnlySession([ALEX])

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    """Never reach Groq, even with a GROQ_API_KEY in the environment: offline unless a test says otherwise."""
    monkeypatch.setattr(assistant_service, "get_llm_client", lambda: StubLLM(configured=False))


@pytest.fixture
def analytics(monkeypatch):
    return FakeServices(share_paise=70000, expense_count=3).install(monkeypatch)


@pytest.fixture
def quota(monkeypatch):
    q = FakeQuota()
    monkeypatch.setattr(assistant_service, "get_quota_service", lambda: q)
    return q


def use_llm(monkeypatch, llm: StubLLM) -> StubLLM:
    monkeypatch.setattr(assistant_service, "get_llm_client", lambda: llm)
    return llm


async def ask(client, question: str):
    resp = await client.post(ASK, json={"question": question}, headers=AUTH)
    return resp.status_code, resp.json()


# ---- authentication, limits, validation ---------------------------------------------------


@pytest.mark.anyio
async def test_unauthenticated_requests_get_401_and_spend_no_budget(client):
    resp = await client.post(ASK, json={"question": "How much did I spend this week?"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"
    assert rate_limit_fakes.scopes() == set()


@pytest.mark.anyio
async def test_ask_has_the_per_user_ai_burst_limit(client, analytics, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_AI_BURST_USER_MAX", 2)
    for _ in range(2):
        assert (await ask(client, "How much did I spend this week?"))[0] == 200
    blocked = await client.post(ASK, json={"question": "How much did I spend this week?"}, headers=AUTH)
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert 0 < int(blocked.headers["retry-after"]) <= 60
    rate_limit_fakes.advance(60)
    assert (await ask(client, "How much did I spend this week?"))[0] == 200


def test_openapi_documents_the_rate_limit_responses():
    responses = app.openapi()["paths"][ASK]["post"]["responses"]
    assert {"200", "422", "429", "503"} <= set(responses)
    assert "Retry-After" in responses["429"]["headers"]


@pytest.mark.anyio
@pytest.mark.parametrize("question", ["", "   ", "x" * 501])
async def test_blank_or_too_long_questions_get_the_validation_envelope(client, question):
    resp = await client.post(ASK, json={"question": question}, headers=AUTH)
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


# ---- response shape -----------------------------------------------------------------------


@pytest.mark.anyio
async def test_answer_shape_for_the_chat_screen(client, analytics, monkeypatch):
    use_llm(monkeypatch, StubLLM(configured=False))
    status, body = await ask(client, "How much did I spend last week?")
    assert status == 200
    data = body["data"]
    assert set(data) == {"answer", "source", "tool", "period", "figures", "counts", "suggestions"}
    assert data["source"] == "template"
    assert data["tool"] == "spend_total"
    assert data["period"] == {"from": data["period"]["from"], "to": data["period"]["to"], "label": "last week"}
    assert data["figures"] == [{"label": "Total spending", "amountPaise": 70000}]
    assert data["counts"] == [{"label": "Expenses", "value": 3}]
    assert data["suggestions"] == []
    assert "₹700.00" in data["answer"]


# ---- AI off, no model, quota --------------------------------------------------------------


@pytest.mark.anyio
async def test_ai_switched_off_returns_the_fallback_with_suggestions(client, analytics, quota, monkeypatch):
    llm = use_llm(monkeypatch, StubLLM(selection={"tool": "spend_total", "slots": {}}))
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    status, body = await ask(client, "What was my total spending?")
    assert status == 200
    data = body["data"]
    assert data["source"] == "fallback" and data["tool"] is None and data["figures"] == []
    assert data["suggestions"] == list(SUGGESTIONS)
    assert llm.selection_calls == [] and quota.reserve_calls == [] and analytics.calls == []


@pytest.mark.anyio
async def test_no_model_configured_answers_offline_and_uses_no_quota(client, analytics, quota, monkeypatch):
    llm = use_llm(monkeypatch, StubLLM(configured=False))
    status, body = await ask(client, "How much did I spend on food this month?")
    assert status == 200 and body["data"]["source"] == "template"
    assert body["data"]["tool"] == "spend_total"
    assert quota.reserve_calls == [] and llm.selection_calls == []


@pytest.mark.anyio
async def test_over_quota_returns_the_fallback_with_200_not_429(client, analytics, monkeypatch):
    q = FakeQuota(allowed=False)
    monkeypatch.setattr(assistant_service, "get_quota_service", lambda: q)
    llm = use_llm(monkeypatch, StubLLM(selection={"tool": "spend_total", "slots": {}}))
    status, body = await ask(client, "How much did I spend this week?")
    assert status == 200
    assert body["data"]["source"] == "fallback" and body["data"]["suggestions"]
    assert q.reserve_calls[0]["raise_on_exceeded"] is False and q.reserve_calls[0]["feature"] == "ask"
    assert llm.selection_calls == [] and analytics.calls == []


@pytest.mark.anyio
async def test_a_model_answer_reserves_and_finalizes_exactly_once(client, analytics, quota, monkeypatch):
    use_llm(monkeypatch, StubLLM(selection=LAST_WEEK))
    status, body = await ask(client, "How much did I spend last week?")
    assert status == 200 and body["data"]["source"] == "llm"
    assert len(quota.reserve_calls) == 1 and quota.finalized == ["success"]


# ---- what the model sees ------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_model_sees_only_the_question_tools_totals_and_labels(client, monkeypatch, quota):
    secret_description = "Dinner with Priya at 22 Baker Street"
    FakeServices(categories=[(secret_description, 50000, 1), ("Groceries", 20000, 1)]).install(monkeypatch)
    llm = use_llm(monkeypatch, StubLLM(selection={"tool": "spend_by_category", "slots": {}}))
    status, body = await ask(client, "Show my category breakdown.")
    assert status == 200 and body["data"]["source"] == "llm"
    (question, definitions), = llm.selection_calls
    assert question == "Show my category breakdown."
    assert {d["name"] for d in definitions} == set(tools.TOOLS)
    sent = json.dumps([definitions, llm.wording_calls])
    assert str(ALEX.id) not in sent and ALEX.email not in sent and ALEX.name not in sent
    assert secret_description not in sent  # stored text never reaches the model
    (_, tool, facts), = llm.wording_calls
    assert tool == "spend_by_category"
    assert set(facts) == {"total", "categories", "breakdown", "period"}
    assert facts["breakdown"] == tools.FILLED_IN_BY_THE_APP
    assert secret_description in body["data"]["answer"]  # filled in by code after the model wrote its sentence


@pytest.mark.anyio
async def test_expense_rows_never_reach_the_model(client, monkeypatch, quota):
    secret = "Dinner with Priya at 22 Baker Street"
    FakeServices(rows=[(date(2026, 11, 20), secret, "Swiggy", "Food & Dining", 40000)]).install(monkeypatch)
    llm = use_llm(monkeypatch, StubLLM(selection={"tool": "list_expenses", "slots": {"limit": 3}}))
    status, body = await ask(client, "Show my last 3 expenses.")
    assert status == 200
    data = body["data"]
    assert data["tool"] == "list_expenses" and data["source"] == "template"
    assert secret in data["answer"]
    assert llm.wording_calls == []  # the model is never asked to word a list of expenses
    assert secret not in json.dumps(llm.selection_calls)
    assert quota.finalized == ["success"]


# ---- strict handling of the model's choice ------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "selection",
    [
        {"tool": "drop_tables", "slots": {}},
        {"tool": "get_total_spending", "slots": {}},  # not one of the eight tools
        {"tool": "spend_total", "slots": {"user_id": str(uuid.uuid4())}},
        {"tool": "spend_total", "slots": {"period": {"date_range": "last_week"}, "group_id": "x"}},
        {"tool": "spend_total", "slots": {"period": {"date_range": "fortnight"}}},
        {"tool": "spend_total", "slots": {"date_range": "last_week"}},  # period not nested
        {"tool": "spend_total", "slots": "SELECT * FROM expenses"},
        {"tool": "spend_total", "slots": {}, "sql": "SELECT 1"},
        {"tool": ["spend_total"], "slots": {}},
        {"tool": "owed_summary", "slots": {"group": 42}},
    ],
)
async def test_an_invalid_tool_choice_gives_a_fallback_never_an_error_or_another_tool(
    client, analytics, quota, monkeypatch, selection
):
    use_llm(monkeypatch, StubLLM(selection=selection))
    status, body = await ask(client, "How much did I spend last week?")
    assert status == 200
    assert body["data"]["source"] == "fallback" and body["data"]["tool"] is None
    assert analytics.calls == []  # no tool ran, not even the offline parser's choice
    assert quota.finalized == ["success"]


@pytest.mark.anyio
async def test_the_model_saying_no_tool_fits_gives_the_unsupported_fallback(client, analytics, quota, monkeypatch):
    use_llm(monkeypatch, StubLLM(selection={"tool": None, "slots": {}}))
    status, body = await ask(client, "What is the weather?")
    assert status == 200 and body["data"]["source"] == "fallback" and analytics.calls == []


@pytest.mark.anyio
async def test_a_model_outage_falls_back_to_the_offline_parser(client, analytics, quota, monkeypatch):
    use_llm(monkeypatch, StubLLM(selection=None))
    status, body = await ask(client, "How much did I spend last week?")
    assert status == 200
    assert body["data"]["source"] == "template" and body["data"]["tool"] == "spend_total"
    assert quota.finalized == ["error"]


@pytest.mark.anyio
async def test_a_period_the_tool_cannot_resolve_is_reported_not_answered(client, analytics, quota, monkeypatch):
    use_llm(monkeypatch, StubLLM(selection={
        "tool": "spend_total", "slots": {"period": {"start_date": "2026-11-20", "end_date": "2026-11-10"}},
    }))
    status, body = await ask(client, "How much did I spend from 20 Nov to 10 Nov?")
    assert status == 200
    data = body["data"]
    assert data["source"] == "fallback" and data["tool"] is None and data["figures"] == []
    assert data["answer"].startswith("The start date of that range is after its end date.")
    assert analytics.calls == [] and quota.finalized == ["success"]


@pytest.mark.anyio
async def test_a_wording_with_an_invented_number_is_replaced_by_the_template(client, analytics, quota, monkeypatch):
    use_llm(monkeypatch, StubLLM(
        selection=LAST_WEEK,
        wording="You spent ₹7.00 {period}, about 30% more than usual.",
    ))
    status, body = await ask(client, "How much did I spend last week?")
    assert status == 200
    data = body["data"]
    assert data["source"] == "template"
    assert data["answer"].startswith("You spent ₹700.00 across 3 expenses last week")
