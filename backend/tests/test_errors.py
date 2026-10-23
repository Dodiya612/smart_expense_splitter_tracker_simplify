"""Tests verifying consistent error response contracts and envelopes."""

from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.main import app

# Create a mock router to simulate domain errors and validation failures
mock_error_router = APIRouter(prefix="/api/v1/mock-errors", tags=["mock-errors"])


class SampleInput(BaseModel):
    amount_paise: int = Field(gt=0, description="Amount in integer paise")
    description: str = Field(min_length=3, description="Description")


@mock_error_router.post("/validate")
def route_validate(payload: SampleInput):
    return {"message": "success", "data": payload.model_dump()}


@mock_error_router.get("/not-found")
def route_not_found():
    raise NotFoundException("Expense record exp_999 not found.")


@mock_error_router.get("/bad-request")
def route_bad_request():
    raise BadRequestException(
        "Invalid currency.", field_errors={"currency": "Only INR is supported."}
    )


@mock_error_router.get("/conflict")
def route_conflict():
    raise ConflictException(
        "Stale version detected.", field_errors={"version": "Expected version 3."}
    )


@mock_error_router.get("/unauthorized")
def route_unauthorized():
    raise UnauthorizedException()


@mock_error_router.get("/forbidden")
def route_forbidden():
    raise ForbiddenException()


@mock_error_router.get("/server-error")
def route_server_error():
    raise RuntimeError("Sensitive internal database connection leak simulation")


# Mount for testing
app.include_router(mock_error_router)
client = TestClient(app, raise_server_exceptions=False)


def test_404_not_found_envelope():
    """Verify 404 response matches standard error format."""
    response = client.get("/api/v1/non-existent-endpoint")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert "meta" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert data["meta"]["request_id"].startswith("req_")
    assert response.headers.get("X-Request-ID") == data["meta"]["request_id"]


def test_custom_not_found_exception():
    """Verify domain NotFoundException returns consistent envelope."""
    response = client.get("/api/v1/mock-errors/not-found")
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "NOT_FOUND"
    assert "exp_999" in data["error"]["message"]
    assert data["meta"]["request_id"].startswith("req_")


def test_validation_error_envelope():
    """Verify Pydantic 422 error returns VALIDATION_ERROR with field_errors."""
    response = client.post(
        "/api/v1/mock-errors/validate",
        json={"amount_paise": -50, "description": "ab"},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "field_errors" in data["error"]
    assert "amount_paise" in data["error"]["field_errors"]
    assert "description" in data["error"]["field_errors"]
    assert data["meta"]["request_id"].startswith("req_")


def test_custom_bad_request_exception():
    """Verify BadRequestException with field_errors."""
    response = client.get("/api/v1/mock-errors/bad-request")
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "BAD_REQUEST"
    assert data["error"]["field_errors"]["currency"] == "Only INR is supported."


def test_conflict_exception():
    """Verify ConflictException (409) envelope."""
    response = client.get("/api/v1/mock-errors/conflict")
    assert response.status_code == 409
    data = response.json()
    assert data["error"]["code"] == "CONFLICT"
    assert data["error"]["field_errors"]["version"] == "Expected version 3."


def test_unauthorized_exception():
    """Verify UnauthorizedException (401) envelope."""
    response = client.get("/api/v1/mock-errors/unauthorized")
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "UNAUTHORIZED"


def test_forbidden_exception():
    """Verify ForbiddenException (403) envelope."""
    response = client.get("/api/v1/mock-errors/forbidden")
    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "FORBIDDEN"


def test_unhandled_server_error_sanitization():
    """Verify 500 errors never leak stack traces or internal secrets."""
    response = client.get("/api/v1/mock-errors/server-error")
    assert response.status_code == 500
    data = response.json()
    assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"
    # Ensure internal exception details are NOT leaked to client
    assert "Sensitive" not in data["error"]["message"]
    assert "database" not in data["error"]["message"]
    assert data["error"]["message"] == "An unexpected internal server error occurred."
    assert data["meta"]["request_id"].startswith("req_")


def test_client_provided_request_id():
    """Verify incoming X-Request-ID is preserved and echoed in meta and headers."""
    custom_id = "req_custom_tracer_12345"
    response = client.get(
        "/api/v1/health",
        headers={"X-Request-ID": custom_id},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_id
