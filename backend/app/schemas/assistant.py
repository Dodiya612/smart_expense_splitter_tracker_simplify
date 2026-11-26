from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from app.schemas.common import BaseSchema


class AskRequest(BaseSchema):
    """Payload for natural language expense query assistant."""

    question: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="User question about their expenses",
    )

    @field_validator("question")
    @classmethod
    def validate_question_not_blank(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Question must not be empty or whitespace only")
        return trimmed


class AskResponseData(BaseSchema):
    """Data envelope for assistant response."""

    answer: str = Field(
        ...,
        description="Grounded, natural language answer or safe fallback template",
    )
    tool_used: str | None = Field(
        default=None,
        description="Name of the query tool selected and executed, if any",
    )
    tool_parameters: dict[str, Any] | None = Field(
        default=None,
        description="Resolved parameters passed to the query tool",
    )
    tool_result: dict[str, Any] | None = Field(
        default=None,
        description="Structured data returned by the tool execution",
    )
    grounded: bool = Field(
        default=True,
        description="Whether the answer was strictly grounded in tool data",
    )
    fallback_suggestions: list[str] = Field(
        default_factory=list,
        description="Helpful suggested questions when fallback is triggered or query is unclear",
    )


class AskResponse(BaseSchema):
    """API envelope for assistant response."""

    data: AskResponseData
