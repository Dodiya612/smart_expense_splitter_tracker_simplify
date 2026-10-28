from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict


def to_camel(string: str) -> str:
    """Convert snake_case to camelCase for API wire format."""
    components = string.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


class BaseSchema(BaseModel):
    """Base schema that serializes to camelCase on the wire."""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class ApiErrorDetail(BaseSchema):
    """Specific validation error entry."""
    loc: List[str | int]
    msg: str
    type: str


class ApiErrorResponse(BaseSchema):
    """
    Standardized API Error envelope matching mobile ApiError expectations:
    { "code": "...", "message": "...", "detail": [...], "isRetryable": false }
    """
    code: str
    message: str
    detail: Optional[List[ApiErrorDetail]] = None
    is_retryable: bool = False


class HealthResponse(BaseSchema):
    """Health check response schema."""
    status: str
    database: str
    environment: str
    version: str
