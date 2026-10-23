"""Standard consistent error schemas matching Coinscious API Contract."""

from typing import Dict, Optional

from pydantic import BaseModel, Field


class ErrorDetails(BaseModel):
    """Detailed error payload."""

    code: str = Field(
        ...,
        description="Machine-readable error code (e.g. VALIDATION_ERROR, NOT_FOUND).",
        examples=["VALIDATION_ERROR"],
    )
    message: str = Field(
        ...,
        description="Human-readable explanation of the error.",
        examples=["Please check the submitted fields."],
    )
    field_errors: Optional[Dict[str, str]] = Field(
        default=None,
        description="Map of field names to specific validation error messages.",
        examples=[{"amount_paise": "Must be greater than zero."}],
    )


class ErrorMeta(BaseModel):
    """Metadata envelope for error tracing."""

    request_id: str = Field(
        ...,
        description="Unique request tracing identifier.",
        examples=["req_4f9a2b8e"],
    )


class ErrorResponse(BaseModel):
    """Top-level standard error response envelope."""

    error: ErrorDetails
    meta: ErrorMeta
