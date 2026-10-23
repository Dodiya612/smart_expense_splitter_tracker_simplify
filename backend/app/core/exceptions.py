"""Domain and HTTP exception classes for consistent error handling."""

from typing import Dict, Optional


class CoinsciousException(Exception):
    """Base application exception for Coinscious."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        field_errors: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.field_errors = field_errors


class BadRequestException(CoinsciousException):
    """400 Bad Request exception."""

    def __init__(
        self,
        message: str = "Malformed or invalid request.",
        code: str = "BAD_REQUEST",
        field_errors: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=400,
            field_errors=field_errors,
        )


class UnauthorizedException(CoinsciousException):
    """401 Unauthorized exception."""

    def __init__(
        self,
        message: str = "Authentication required or session expired.",
        code: str = "UNAUTHORIZED",
    ) -> None:
        super().__init__(message=message, code=code, status_code=401)


class ForbiddenException(CoinsciousException):
    """403 Forbidden exception."""

    def __init__(
        self,
        message: str = "You do not have permission to perform this action.",
        code: str = "FORBIDDEN",
    ) -> None:
        super().__init__(message=message, code=code, status_code=403)


class NotFoundException(CoinsciousException):
    """404 Not Found exception."""

    def __init__(
        self,
        message: str = "The requested resource was not found.",
        code: str = "NOT_FOUND",
    ) -> None:
        super().__init__(message=message, code=code, status_code=404)


class ConflictException(CoinsciousException):
    """409 Conflict / Idempotency exception."""

    def __init__(
        self,
        message: str = "A conflicting resource or version mismatch occurred.",
        code: str = "CONFLICT",
        field_errors: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=409,
            field_errors=field_errors,
        )


class ValidationException(CoinsciousException):
    """422 Validation Error exception."""

    def __init__(
        self,
        message: str = "Please check the submitted fields.",
        code: str = "VALIDATION_ERROR",
        field_errors: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=422,
            field_errors=field_errors,
        )


class RateLimitException(CoinsciousException):
    """429 Rate Limit Exceeded exception."""

    def __init__(
        self,
        message: str = "Rate limit reached. Please wait before retrying.",
        code: str = "RATE_LIMITED",
    ) -> None:
        super().__init__(message=message, code=code, status_code=429)
