"""Expense assistant (T-57 / US-24).

One question goes through these steps:

1. ``AI_ENABLED`` off: fallback with suggestions.
2. Tool choice. With a language model configured, one daily ``ask`` quota slot is
   reserved (never raising; over quota gives the fallback) and the model picks
   one of the eight tools in app/ai/tools.py. Without a model, or if the model
   cannot be reached, the offline parser (app/ai/question_parser.py) picks it and
   no quota is used. A tool name or slots from the model that fail validation
   give a fallback; they never switch to another tool.
3. The tool runs for the signed-in user only, on the existing services.
4. Wording. The model words the answer with placeholders that the backend fills
   in; the grounding guard (app/ai/grounding.py) checks the result. Anything
   that fails, or no model, gives the tool's template sentence. The rows of
   ``list_expenses`` are never sent to the model: that tool always answers with
   its template.

The reservation is finalized once, so an answered question with the model writes
exactly one ai_usage_log row. Logs carry the tool name, question length and
outcome only, never the question or any figure.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import fallbacks
from app.ai.grounding import fill_placeholders, find_violations
from app.ai.question_parser import parse_question
from app.ai.quota import AIQuotaService, get_quota_service
from app.ai.tools import TOOL_INPUT_ERRORS, TOOLS, ToolResult, tool_definitions
from app.core.config import settings
from app.models.user import User
from app.schemas.assistant import AnswerSource, AskResponseData
from app.services.date_ranges import today_in_kolkata
from app.services.groq_client import GroqClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Choice:
    """A tool and validated slots, or the fallback to return instead."""

    tool: str | None = None
    slots: BaseModel | None = None
    fallback: AskResponseData | None = None


def get_llm_client() -> GroqClient:
    return GroqClient()


def _log(outcome: str, question: str, tool: str | None = None) -> None:
    logger.info("assistant ask: outcome=%s tool=%s question_length=%d", outcome, tool or "-", len(question))


def _validate(tool: str, raw_slots: Any) -> _Choice:
    spec = TOOLS.get(tool)
    if spec is None or not isinstance(raw_slots, dict):
        return _Choice(fallback=fallbacks.not_understood())
    try:
        return _Choice(tool=tool, slots=spec.slots.model_validate(raw_slots))
    except ValidationError:
        return _Choice(fallback=fallbacks.not_understood())


def choose_offline(question: str, today: date | None = None) -> _Choice:
    """The offline parser's choice for a question."""
    parsed = parse_question(question, today)
    if parsed.outcome == "tool" and parsed.tool is not None:
        return _validate(parsed.tool, parsed.slots)
    if parsed.outcome == "unsupported_scope":
        return _Choice(fallback=fallbacks.unsupported_scope())
    if parsed.reason:
        return _Choice(fallback=fallbacks.with_reason(parsed.reason))
    return _Choice(fallback=fallbacks.unsupported())


def choose_from_model(selection: dict[str, Any]) -> _Choice:
    """Validate the model's choice strictly: one known tool, slots matching its schema."""
    tool = selection.get("tool")
    if tool is None:
        return _Choice(fallback=fallbacks.unsupported())
    if not isinstance(tool, str) or set(selection) - {"tool", "slots"}:
        return _Choice(fallback=fallbacks.not_understood())
    return _validate(tool, selection.get("slots", {}))


async def _run(db: AsyncSession, user: User, choice: _Choice, today: date) -> ToolResult | AskResponseData:
    if choice.tool is None or choice.slots is None:
        return fallbacks.not_understood()
    try:
        return await TOOLS[choice.tool].run(db, user, choice.slots, today)
    except TOOL_INPUT_ERRORS as exc:
        return fallbacks.with_reason(str(exc))


def _answer(result: ToolResult, text: str, source: AnswerSource) -> AskResponseData:
    return AskResponseData(
        answer=text,
        source=source,
        tool=result.tool,
        period=result.public_period(),
        figures=result.figures,
        counts=result.counts,
    )


async def word_answer(question: str, result: ToolResult, llm: GroqClient | None) -> AskResponseData:
    """The model's wording if it passes the guard, otherwise the template sentence."""
    if llm is not None and result.model_wording:
        text = await llm.write_answer(question, result.tool, result.shared_values())
        filled = fill_placeholders(text, result.values)
        if filled is not None and not find_violations(filled, result.allowed()):
            return _answer(result, filled, "llm")
        logger.info("assistant ask: model wording rejected by the grounding guard tool=%s", result.tool)
    return _answer(result, result.template_answer(), "template")


async def ask_assistant(
    db: AsyncSession,
    user: User,
    question: str,
    llm: GroqClient | None = None,
    quota_service: AIQuotaService | None = None,
    today: date | None = None,
) -> AskResponseData:
    """Answer one question about the signed-in user's own expenses."""
    today = today or today_in_kolkata()
    if not settings.AI_ENABLED:
        _log("ai_disabled", question)
        return fallbacks.ai_disabled()

    llm = llm or get_llm_client()
    if not llm.is_configured():
        return await _answer_offline(db, user, question, today)

    qs = quota_service or get_quota_service()
    async with qs.reserve(
        user_id=user.id,
        feature="ask",
        db=db,
        provider="groq",
        model=settings.GROQ_MODEL,
        raise_on_exceeded=False,
    ) as reservation:
        if not reservation.allowed:
            _log("quota_exceeded", question)
            return fallbacks.quota_used_up()

        started = time.perf_counter()
        selection = await llm.select_tool_call(question, tool_definitions())
        if selection is None:
            # The model could not be reached: answer offline, no model wording.
            await reservation.finalize(
                status="error",
                error_message="Tool selection unavailable; answered offline",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                db=db,
            )
            return await _answer_offline(db, user, question, today)

        choice = choose_from_model(selection)
        if choice.fallback is not None:
            await reservation.finalize(
                status="success", latency_ms=(time.perf_counter() - started) * 1000.0, db=db
            )
            _log("model_fallback", question, choice.tool)
            return choice.fallback

        result = await _run(db, user, choice, today)
        if isinstance(result, AskResponseData):
            response = result
        else:
            response = await word_answer(question, result, llm)
        await reservation.finalize(status="success", latency_ms=(time.perf_counter() - started) * 1000.0, db=db)
        _log(response.source, question, choice.tool)
        return response


async def _answer_offline(db: AsyncSession, user: User, question: str, today: date) -> AskResponseData:
    choice = choose_offline(question, today)
    if choice.fallback is not None:
        _log("offline_fallback", question)
        return choice.fallback
    result = await _run(db, user, choice, today)
    if isinstance(result, AskResponseData):
        _log("offline_fallback", question, choice.tool)
        return result
    response = await word_answer(question, result, None)
    _log(response.source, question, choice.tool)
    return response
