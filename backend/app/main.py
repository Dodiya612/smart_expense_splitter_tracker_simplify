import logging
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.api import api_router
from app.core.config import settings
from app.schemas.common import ApiErrorDetail, ApiErrorResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
)

# CORS Middleware with explicitly configured development origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


# Exception Handlers ensuring standardized camelCase error envelope
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Standardize 422 Unprocessable Entity validation errors to:
    { "code": "VALIDATION_ERROR", "message": "...", "detail": [...], "isRetryable": false }
    """
    details = [
        ApiErrorDetail(
            loc=list(err.get("loc", [])),
            msg=str(err.get("msg", "")),
            type=str(err.get("type", "")),
        )
        for err in exc.errors()
    ]
    error_response = ApiErrorResponse(
        code="VALIDATION_ERROR",
        message="Invalid request parameters.",
        detail=details,
        is_retryable=False,
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=error_response.model_dump(by_alias=True),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Standardize HTTPExceptions (including Starlette 404/405) to the common error envelope.
    """
    code = "NOT_FOUND" if exc.status_code == 404 else ("METHOD_NOT_ALLOWED" if exc.status_code == 405 else "HTTP_ERROR")
    message = "A request error occurred."
    detail = None

    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", code)
        message = exc.detail.get("message", message)
        detail = exc.detail.get("detail", None)
    elif isinstance(exc.detail, str) and exc.detail not in ("Not Found", "Method Not Allowed"):
        code = exc.detail
        message = exc.detail
    elif isinstance(exc.detail, str):
        message = exc.detail

    error_response = ApiErrorResponse(
        code=code,
        message=message,
        detail=detail,
        is_retryable=exc.status_code >= 500,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(by_alias=True),
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Catch-all exception handler to avoid leaking tracebacks or internal details.
    """
    logger.exception(f"Unhandled error processing request {request.method} {request.url.path}: {exc}")
    error_response = ApiErrorResponse(
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected server error occurred. Please try again later.",
        detail=None,
        is_retryable=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response.model_dump(by_alias=True),
    )


# Register API v1 routes
app.include_router(api_router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
async def root():
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docsUrl": "/api/v1/docs",
        "healthUrl": "/api/v1/health",
    }
