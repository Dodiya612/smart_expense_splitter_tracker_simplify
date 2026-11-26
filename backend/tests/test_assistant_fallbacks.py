"""Every suggested question in app/ai/fallbacks.py is answerable without a model.

This runs each suggestion on fixed service figures; tests/test_assistant_eval_pg.py
asks every suggestion through the API on real PostgreSQL.
"""

import uuid
from datetime import date

import pytest

from app.ai import fallbacks, tools
from app.ai.assistant_service import ask_assistant
from app.ai.question_parser import parse_question
from app.models.user import User
from tests.assistant_fakes import FakeServices, StubLLM, budget, rule

USER = User(id=uuid.uuid4(), email="alex@example.com", name="Alex", hashed_password="x", is_active=True)


@pytest.mark.anyio
@pytest.mark.parametrize("question", fallbacks.SUGGESTIONS)
async def test_every_suggestion_is_answered(monkeypatch, question):
    FakeServices(
        owed_to_you_paise=5000,
        budgets=[budget("monthly", 500000, 100000, date(2026, 11, 1), date(2026, 11, 30))],
        rules=[rule("Netflix", 64900, date(2026, 1, 28))],
    ).install(monkeypatch)
    response = await ask_assistant(None, USER, question, llm=StubLLM(configured=False), today=date(2026, 11, 24))
    assert response.source == "template", question
    assert response.tool is not None and response.suggestions == []
    assert response.figures or response.counts


def test_the_suggestions_cover_all_eight_tools():
    chosen = {parse_question(q, date(2026, 11, 24)).tool for q in fallbacks.SUGGESTIONS}
    assert chosen == set(tools.TOOLS)


def test_fallback_answers_contain_no_figures():
    for build in (fallbacks.ai_disabled, fallbacks.quota_used_up, fallbacks.unsupported,
                  fallbacks.unsupported_scope, fallbacks.not_understood):
        response = build()
        assert response.source == "fallback" and response.suggestions == list(fallbacks.SUGGESTIONS)
        assert not any(ch.isdigit() for ch in response.answer)
