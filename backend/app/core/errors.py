"""Standardized error helpers and HTTP exceptions.

Integrates with app.main.http_exception_handler to produce the established
API error envelope: { "code": "...", "message": "...", "detail": ..., "isRetryable": bool }
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status


def http_error(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> HTTPException:
    """Create a standardized HTTPException matching the API error envelope."""
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "detail": details,
        },
    )


def unsupported_media_type_error(
    message: str = "Unsupported media type. Only JPEG and PNG are allowed.",
) -> HTTPException:
    return http_error(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        code="UNSUPPORTED_MEDIA_TYPE",
        message=message,
    )


def invalid_image_error(
    message: str = "Invalid or corrupted image data.",
) -> HTTPException:
    return http_error(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="INVALID_IMAGE",
        message=message,
    )


def image_too_large_error(
    message: str = "Image exceeds maximum allowed size.",
) -> HTTPException:
    return http_error(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        code="IMAGE_TOO_LARGE",
        message=message,
    )


def not_found_error(
    message: str = "Resource not found.",
) -> HTTPException:
    return http_error(
        status_code=status.HTTP_404_NOT_FOUND,
        code="NOT_FOUND",
        message=message,
    )
