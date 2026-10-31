import uuid
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import BaseSchema


class CategorySuggestionRequest(BaseSchema):
    """Payload for category suggestion."""

    description: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Expense description text",
    )
    merchant: str | None = Field(
        default=None,
        max_length=200,
        description="Optional merchant name",
    )

    @field_validator("description")
    @classmethod
    def validate_description_not_blank(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Description must not be empty or whitespace only")
        return trimmed

    @field_validator("merchant")
    @classmethod
    def validate_merchant_trimmed(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed if trimmed else None


class CategorySuggestionData(BaseSchema):
    """Suggestion response payload."""

    suggested_category_id: uuid.UUID = Field(
        ...,
        description="Primary category UUID matching API Contract",
    )
    category_id: uuid.UUID = Field(
        ...,
        description="Alias category UUID matching mobile client expectation",
    )
    category_name: str = Field(
        ...,
        description="Canonical category display name",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0",
    )
    requires_confirmation: bool = Field(
        ...,
        description="Flag indicating whether user confirmation is required",
    )
    source: Literal["history", "classifier", "llm", "rule_fallback"] = Field(
        ...,
        description="Pipeline layer that produced the suggestion",
    )


class CategorySuggestionResponse(BaseSchema):
    """Enveloped suggestion response."""

    data: CategorySuggestionData


class CategoryFeedbackRequest(BaseSchema):
    """Payload for recording category feedback and manual selection."""

    description: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Expense description that triggered suggestion",
    )
    merchant: str | None = Field(
        default=None,
        max_length=200,
        description="Optional merchant name",
    )
    suggested_category_id: uuid.UUID = Field(
        ...,
        description="Category ID originally suggested by system",
    )
    chosen_category_id: uuid.UUID = Field(
        ...,
        description="Category ID confirmed or chosen by user",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence at suggestion time",
    )
    source: Literal["history", "classifier", "llm", "rule_fallback"] = Field(
        default="classifier",
        description="Source of the original suggestion",
    )
    accepted: bool = Field(
        ...,
        description="True if user accepted suggestion, False if user changed/overrode it",
    )

    @field_validator("description")
    @classmethod
    def validate_feedback_description(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Description must not be empty or whitespace only")
        return trimmed

    @field_validator("merchant")
    @classmethod
    def validate_feedback_merchant(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed if trimmed else None


class CategoryFeedbackData(BaseSchema):
    """Feedback confirmation details."""

    success: bool = True
    message: str = "Feedback recorded successfully"


class CategoryFeedbackResponse(BaseSchema):
    """Enveloped feedback response."""

    data: CategoryFeedbackData

