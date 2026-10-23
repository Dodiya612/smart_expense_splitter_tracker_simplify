"""Custom middlewares for request tracing and headers."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware attaching a unique request ID to state and response headers."""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming_id = request.headers.get("X-Request-ID")
        if incoming_id and len(incoming_id) <= 64:
            request_id = incoming_id
        else:
            request_id = f"req_{uuid.uuid4().hex[:12]}"

        request.state.request_id = request_id

        try:
            response = await call_next(request)
        except Exception as exc:
            from app.core.errors import unhandled_exception_handler

            response = await unhandled_exception_handler(request, exc)

        response.headers["X-Request-ID"] = request_id
        return response
