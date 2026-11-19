import json
import os
from pathlib import Path
from typing import Any, List
from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Stable paths relative to backend root directory independent of CWD
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def get_env_file_path() -> Path:
    """
    Returns an absolute path to the .env file, independent of current working directory.
    If the ENV_FILE environment variable is set:
      - If absolute, it is returned as-is.
      - If relative, it is resolved relative to BACKEND_DIR.
    Otherwise, defaults to BACKEND_DIR / ".env".
    """
    env_override = os.getenv("ENV_FILE")
    if env_override and env_override.strip():
        candidate = Path(env_override.strip())
        return candidate if candidate.is_absolute() else (BACKEND_DIR / candidate).resolve()
    return BACKEND_DIR / ".env"


ENV_FILE_PATH = get_env_file_path()


class Settings(BaseSettings):
    PROJECT_NAME: str = "Smart Expense Splitter Backend"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    VERSION: str = "0.1.0"

    # Database Configuration
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/expense_tracker"

    # CORS Configuration
    CORS_ORIGINS: List[str] = [
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "http://10.0.2.2:8081",
        "http://localhost:3000",
        "http://localhost:19006",
    ]

    # API Documentation Configuration (T-25)
    # None = enabled in development, disabled in production unless explicitly overridden
    ENABLE_DOCS: bool | None = None

    @property
    def docs_enabled(self) -> bool:
        """Determines whether OpenAPI/Swagger/ReDoc documentation endpoints should be mounted."""
        if self.ENABLE_DOCS is not None:
            return self.ENABLE_DOCS
        return self.ENVIRONMENT == "development"

    # JWT Authentication Configuration
    JWT_SECRET_KEY: str = Field(
        default="dev-secret-key-change-in-production-at-least-32-bytes-long",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "JWT_SECRET"),
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    REFRESH_TOKEN_EXPIRE_HOURS_WITHOUT_REMEMBER: int = 24
    JWT_ISSUER: str = "smart-expense-splitter"
    JWT_AUDIENCE: str = "smart-expense-splitter-app"

    # Login Rate Limiting Configuration
    # Rate limiting (T-39). Counters live in PostgreSQL (rate_limit_buckets), so limits hold
    # across workers and instances. Every limit is "<max> requests per <window> seconds".
    # Defaults to ON. Switching it off is only accepted when ENVIRONMENT=development.
    RATE_LIMIT_ENABLED: bool = True
    # Login: attempts per (account, address) window; plus an address-wide and an account-wide
    # ceiling. Successful logins are refunded from the ceilings and clear the pair counter.
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 900
    RATE_LIMIT_LOGIN_IP_MAX: int = 20
    RATE_LIMIT_LOGIN_ACCOUNT_MAX: int = 30
    RATE_LIMIT_SIGNUP_IP_MAX: int = 5
    RATE_LIMIT_SIGNUP_WINDOW_SECONDS: int = 3600
    RATE_LIMIT_REFRESH_IP_MAX: int = 120
    RATE_LIMIT_REFRESH_WINDOW_SECONDS: int = 900
    RATE_LIMIT_INVITE_USER_MAX: int = 20
    RATE_LIMIT_INVITE_WINDOW_SECONDS: int = 3600
    RATE_LIMIT_JOIN_USER_MAX: int = 10
    RATE_LIMIT_JOIN_WINDOW_SECONDS: int = 900
    RATE_LIMIT_JOIN_CODE_USER_MAX: int = 10
    RATE_LIMIT_JOIN_CODE_WINDOW_SECONDS: int = 3600
    RATE_LIMIT_INVITE_RESPOND_USER_MAX: int = 30
    RATE_LIMIT_INVITE_RESPOND_WINDOW_SECONDS: int = 900
    RATE_LIMIT_AI_BURST_USER_MAX: int = 20
    RATE_LIMIT_AI_FEEDBACK_USER_MAX: int = 60
    RATE_LIMIT_AI_WINDOW_SECONDS: int = 60
    # Probability that a counter write also deletes a small batch of expired rows.
    RATE_LIMIT_PURGE_PROBABILITY: float = 0.01
    RATE_LIMIT_PURGE_BATCH: int = 500
    # Name of a request header that a PROXY YOU CONTROL sets to the real client address and
    # overwrites on every request (for example "CF-Connecting-IP" behind Cloudflare). Unset by
    # default: the app never trusts X-Forwarded-For or the socket peer for rate limiting, and
    # address-scoped limits are skipped (with a warning) until this is configured and verified.
    TRUSTED_CLIENT_IP_HEADER: str | None = None

    # Groq LLM Configuration (US-26 / T-23)
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    # AI Feature Flags and Daily Quotas (S2-AI-01)
    AI_ENABLED: bool = True
    AI_QUOTA_CATEGORIZE_DAILY: int = 50
    AI_QUOTA_RECEIPT_DAILY: int = 10
    AI_QUOTA_BUDGET_GOALS_DAILY: int = 5
    AI_QUOTA_ASK_DAILY: int = 20

    # Receipt Storage Configuration (US-16)
    RECEIPT_STORAGE: str = "db"
    SUPABASE_URL: str | None = None
    SUPABASE_SERVICE_KEY: str | None = None
    RECEIPTS_BUCKET: str = "receipts"


    @model_validator(mode="after")
    def validate_jwt_secret_key(self) -> "Settings":
        if self.ENVIRONMENT != "development":
            if (
                self.JWT_SECRET_KEY == "dev-secret-key-change-in-production-at-least-32-bytes-long"
                or len(self.JWT_SECRET_KEY) < 32
            ):
                raise ValueError(
                    "In non-development environments, JWT_SECRET_KEY must not be the default value "
                    "and must be at least 32 characters long."
                )
        return self

    @model_validator(mode="after")
    def validate_rate_limiting_enabled(self) -> "Settings":
        # A mistyped or leftover RATE_LIMIT_ENABLED=false must not silently disable abuse
        # protection in a deployed environment; it is only allowed in development.
        if self.ENVIRONMENT != "development" and not self.RATE_LIMIT_ENABLED:
            raise ValueError(
                "RATE_LIMIT_ENABLED must be true when ENVIRONMENT is not 'development'."
            )
        return self

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, v: Any) -> str:
        if isinstance(v, str):
            url = v.strip()
            # Normalize driver prefix for SQLAlchemy asyncpg
            if url.startswith("postgres://"):
                url = "postgresql+asyncpg://" + url[len("postgres://"):]
            elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
                url = "postgresql+asyncpg://" + url[len("postgresql://"):]
            
            # asyncpg requires ssl= rather than sslmode=
            if "sslmode=" in url:
                url = url.replace("sslmode=", "ssl=")
            return url
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            v_trimmed = v.strip()
            if v_trimmed.startswith("[") and v_trimmed.endswith("]"):
                try:
                    return json.loads(v_trimmed)
                except Exception:
                    pass
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        elif isinstance(v, (list, tuple)):
            return [str(item) for item in v]
        return []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if "_env_file" not in kwargs:
            kwargs["_env_file"] = get_env_file_path()
        super().__init__(*args, **kwargs)

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
