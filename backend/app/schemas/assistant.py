"""Schemas for the expense assistant (US-24 / T-57).

Money is integer paise. Every figure and count in a response was computed by the
backend (analytics, budget, recurring and balance services); the answer text only
repeats them.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import BaseSchema

AnswerSource = Literal["llm", "template", "fallback"]
ToolName = Literal[
    "spend_total",
    "spend_by_category",
    "compare_periods",
    "top_merchants",
    "budget_status",
    "owed_summary",
    "recurring_upcoming",
    "list_expenses",
]


class AskRequest(BaseSchema):
    """A question about the signed-in user's own expenses."""

    question: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="The question, in plain English (at most 500 characters).",
    )

    @field_validator("question")
    @classmethod
    def validate_question_not_blank(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Question must not be empty or whitespace only")
        return trimmed


class AssistantPeriod(BaseSchema):
    """The inclusive date range the answer covers (Asia/Kolkata calendar days)."""

    from_date: date = Field(..., alias="from", description="First day of the range (inclusive).")
    to_date: date = Field(..., alias="to", description="Last day of the range (inclusive).")
    label: str = Field(..., description="How the answer names the range, e.g. 'last week'.")


class AssistantFigure(BaseSchema):
    """A money figure used in the answer."""

    label: str
    amount_paise: int = Field(..., description="Integer paise.")


class AssistantCount(BaseSchema):
    """A count used in the answer (expenses, days, categories)."""

    label: str
    value: int


class AskResponseData(BaseSchema):
    answer: str = Field(..., description="The answer to show in the chat.")
    source: AnswerSource = Field(
        ...,
        description=(
            "'llm': worded by the language model with figures filled in by the backend; "
            "'template': a fixed sentence built from the figures; "
            "'fallback': the question could not be answered (see suggestions)."
        ),
    )
    tool: ToolName | None = Field(default=None, description="The query tool that produced the figures.")
    period: AssistantPeriod | None = Field(default=None, description="The range the figures cover.")
    figures: list[AssistantFigure] = Field(default_factory=list)
    counts: list[AssistantCount] = Field(default_factory=list)
    suggestions: list[str] = Field(
        default_factory=list, description="Questions the assistant can answer, shown when it could not."
    )


class AskResponse(BaseSchema):
    data: AskResponseData
