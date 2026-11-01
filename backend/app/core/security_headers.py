from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

# Strict CSP for pure JSON API endpoints: no scripts, no styles, no frames
API_CSP = "default-src 'none'; frame-ancestors 'none'"

# Permissive CSP strictly for interactive Swagger UI / ReDoc documentation pages
DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)

DOCS_PATHS = frozenset({"/api/v1/docs", "/api/v1/redoc", "/api/v1/openapi.json"})


def get_csp_for_path(path: str) -> str:
    """Returns Swagger-compatible CSP for documentation endpoints, strict CSP otherwise."""
    if path in DOCS_PATHS and settings.docs_enabled:
        return DOCS_CSP
    return API_CSP


def get_security_headers_dict(path: str = "") -> dict[str, str]:
    """
    Returns standard security headers as a string dictionary.
    Used for direct response injection (e.g., error handlers).
    """
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
        "Content-Security-Policy": get_csp_for_path(path),
    }
    # HSTS is strictly production-only; omitted in development, test, and staging
    if settings.ENVIRONMENT == "production":
        headers["Strict-Transport-Security"] = "max-age=31536000"
    return headers


class SecurityHeadersMiddleware:
    """
    Pure ASGI middleware that injects required security headers on all HTTP responses.

    Applies to:
    - Normal 2xx responses
    - Handled error responses (401, 404, 422)
    - Unhandled server exceptions (500)
    - CORS preflight OPTIONS responses
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers", []))
                existing_lower = {h[0].decode("latin-1").lower() for h in raw_headers}

                # 1. Prevent MIME-type sniffing
                if "x-content-type-options" not in existing_lower:
                    raw_headers.append((b"x-content-type-options", b"nosniff"))

                # 2. Block framing/clickjacking
                if "x-frame-options" not in existing_lower:
                    raw_headers.append((b"x-frame-options", b"DENY"))

                # 3. Referrer Policy
                if "referrer-policy" not in existing_lower:
                    raw_headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))

                # 4. Permissions Policy: disable unused browser capabilities
                if "permissions-policy" not in existing_lower:
                    raw_headers.append(
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()")
                    )

                # 5. Content Security Policy
                if "content-security-policy" not in existing_lower:
                    csp = get_csp_for_path(path)
                    raw_headers.append((b"content-security-policy", csp.encode("latin-1")))

                # 6. Strict-Transport-Security: strictly production-only, no includeSubDomains
                if settings.ENVIRONMENT == "production" and "strict-transport-security" not in existing_lower:
                    raw_headers.append((b"strict-transport-security", b"max-age=31536000"))

                message["headers"] = raw_headers

            await send(message)

        await self.app(scope, receive, send_wrapper)
