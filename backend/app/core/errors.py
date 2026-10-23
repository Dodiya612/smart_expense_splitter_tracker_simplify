"""Global exception handlers returning standardized error envelopes."""

import logging
from typing import Dict, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import CoinsciousException
from app.schemas.errors import ErrorDetails, ErrorMeta, ErrorResponse

logger = logging.getLogger(__name__)

STATUS_TO_CODE: Dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_SERVER_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}


def get_request_id(request: Request) -> str:
    """Retrieve request_id from request state or fallback to default."""
    return getattr(request.state, "request_id", "req_unknown")


def build_error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    field_errors: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    """Build a typed standard JSONResponse for an error."""
    payload = ErrorResponse(
        error=ErrorDetails(
            code=code,
            message=message,
            field_errors=field_errors,
        ),
        meta=ErrorMeta(request_id=request_id),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(exclude_none=True),
    )


async def coinscious_exception_handler(
    request: Request, exc: CoinsciousException
) -> JSONResponse:
    """Handle custom application-defined exceptions."""
    request_id = get_request_id(request)
    return build_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        request_id=request_id,
        field_errors=exc.field_errors,
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Handle standard Starlette / FastAPI HTTPExceptions."""
    request_id = get_request_id(request)
    code = STATUS_TO_CODE.get(exc.status_code, "HTTP_ERROR")
    message = str(exc.detail) if exc.detail else "An HTTP error occurred."
    return build_error_response(
        status_code=exc.status_code,
        code=code,
        message=message,
        request_id=request_id,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic request validation errors (HTTP 422)."""
    request_id = get_request_id(request)
    field_errors: Dict[str, str] = {}

    for err in exc.errors():
        # Clean path: omit 'body', 'query', or 'path' prefix if present
        loc = err.get("loc", ())
        field_name = ".".join(
            str(part) for part in loc if part not in ("body", "query", "path")
        )
        if not field_name and loc:
            field_name = str(loc[-1])
        field_errors[field_name or "request"] = err.get("msg", "Invalid value.")

    return build_error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message="Please check the submitted fields.",
        request_id=request_id,
        field_errors=field_errors or None,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unexpected server errors (HTTP 500)."""
    request_id = get_request_id(request)
    logger.exception("Unhandled server error [request_id=%s]: %s", request_id, str(exc))
    # Never leak internal stack traces or connection strings to clients
    return build_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected internal server error occurred.",
        request_id=request_id,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register all standard error handlers onto the FastAPI application."""
    app.add_exception_handler(CoinsciousException, coinscious_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]
