import json
import os
from pathlib import Path
from typing import Any, List
from pydantic import field_validator, model_validator
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
    ]

    # JWT Authentication Configuration
    JWT_SECRET_KEY: str = "dev-secret-key-change-in-production-at-least-32-bytes-long"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    REFRESH_TOKEN_EXPIRE_HOURS_WITHOUT_REMEMBER: int = 24
    JWT_ISSUER: str = "smart-expense-splitter"
    JWT_AUDIENCE: str = "smart-expense-splitter-app"

    # Login Rate Limiting Configuration
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 900

    # Groq LLM Configuration (US-26 / T-23)
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "llama-3.1-8b-instant"


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
