from pathlib import Path
from pydantic_settings import SettingsConfigDict
from app.core.config import BACKEND_DIR, ENV_FILE_PATH, Settings, get_env_file_path


def test_settings_defaults():
    settings = Settings(
        PROJECT_NAME="Test Project",
        ENVIRONMENT="development",
        DEBUG=False,
    )
    assert settings.PROJECT_NAME == "Test Project"
    assert settings.ENVIRONMENT == "development"
    assert settings.DEBUG is False
    assert "http://localhost:8081" in settings.CORS_ORIGINS


def test_cors_origins_parsing():
    settings = Settings(
        CORS_ORIGINS='["http://example.com", "http://app.local:8081"]'
    )
    assert "http://example.com" in settings.CORS_ORIGINS
    assert "http://app.local:8081" in settings.CORS_ORIGINS

    # Comma-separated fallback
    settings_csv = Settings(
        CORS_ORIGINS="http://alpha.com, http://beta.com"
    )
    assert "http://alpha.com" in settings_csv.CORS_ORIGINS
    assert "http://beta.com" in settings_csv.CORS_ORIGINS


def test_database_url_normalization():
    # Test standard postgresql:// converts to asyncpg
    s1 = Settings(DATABASE_URL="postgresql://user:pass@host:5432/db")
    assert s1.DATABASE_URL == "postgresql+asyncpg://user:pass@host:5432/db"

    # Test sslmode=require converts to ssl=require
    s2 = Settings(DATABASE_URL="postgresql://user:pass@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require")
    assert s2.DATABASE_URL == "postgresql+asyncpg://user:pass@aws-0-us-east-1.pooler.supabase.com:5432/postgres?ssl=require"


def test_backend_dir_and_env_file_path_are_stable(monkeypatch):
    """Verify that BACKEND_DIR and ENV_FILE_PATH resolve to absolute stable paths anchored to backend/."""
    monkeypatch.delenv("ENV_FILE", raising=False)
    assert BACKEND_DIR.is_absolute()
    assert (BACKEND_DIR / "pyproject.toml").is_file()
    assert (BACKEND_DIR / "app" / "core" / "config.py").is_file()
    assert ENV_FILE_PATH.is_absolute()
    assert ENV_FILE_PATH == BACKEND_DIR / ".env"
    assert Settings.model_config.get("env_file") == ENV_FILE_PATH
    assert get_env_file_path() == BACKEND_DIR / ".env"


def test_get_env_file_path_resolution(tmp_path, monkeypatch):
    """
    Verify get_env_file_path produces stable absolute paths independent of CWD:
    - When unset: returns BACKEND_DIR / ".env" across any working directory.
    - When set to absolute path: returns that absolute path across any working directory.
    - When set to relative path: anchors to BACKEND_DIR (never to CWD!).
    - When set to empty/whitespace: falls back to BACKEND_DIR / ".env".
    """
    repo_root = BACKEND_DIR.parent

    # 1. Unset: always BACKEND_DIR / ".env"
    monkeypatch.delenv("ENV_FILE", raising=False)
    for cwd in (repo_root, BACKEND_DIR, tmp_path):
        monkeypatch.chdir(cwd)
        assert get_env_file_path() == BACKEND_DIR / ".env"

    # 2. Absolute: always exact path
    dummy_abs = tmp_path / "custom_abs.env"
    monkeypatch.setenv("ENV_FILE", str(dummy_abs))
    for cwd in (repo_root, BACKEND_DIR, tmp_path):
        monkeypatch.chdir(cwd)
        assert get_env_file_path() == dummy_abs

    # 3. Relative: always anchored to BACKEND_DIR, not to CWD!
    monkeypatch.setenv("ENV_FILE", "custom_rel.env")
    expected_rel = (BACKEND_DIR / "custom_rel.env").resolve()
    for cwd in (repo_root, BACKEND_DIR, tmp_path):
        monkeypatch.chdir(cwd)
        resolved = get_env_file_path()
        assert resolved == expected_rel
        assert resolved.is_absolute()
        if cwd != BACKEND_DIR:
            assert resolved != (cwd / "custom_rel.env").resolve()

    # 4. Whitespace / empty string: falls back to default
    monkeypatch.setenv("ENV_FILE", "   ")
    for cwd in (repo_root, BACKEND_DIR, tmp_path):
        monkeypatch.chdir(cwd)
        assert get_env_file_path() == BACKEND_DIR / ".env"


def test_isolated_config_resolution_from_root_and_backend(tmp_path, monkeypatch):
    """
    Verify configuration resolution when invoked from both the repository root
    and the backend directory using isolated test configuration.
    Ensures tests do not depend on or reveal real Supabase credentials.
    """
    dummy_env = tmp_path / "dummy_isolated.env"
    dummy_env.write_text(
        "PROJECT_NAME=Isolated App Name\n"
        "ENVIRONMENT=testing-isolated\n"
        "DEBUG=False\n"
        "DATABASE_URL=postgresql://dummy_user:dummy_password@test.dummy.supabase.co:5432/dummy_db\n"
        "CORS_ORIGINS=[\"http://isolated.local:8081\"]\n"
        "JWT_SECRET_KEY=isolated-dummy-secret-key-at-least-32-chars-long\n",
        encoding="utf-8",
    )

    # Point ENV_FILE to isolated dummy configuration to test Settings() directly
    monkeypatch.setenv("ENV_FILE", str(dummy_env))

    # Clean out any ambient environment variables to test pure file resolution
    for var in ("PROJECT_NAME", "ENVIRONMENT", "DEBUG", "DATABASE_URL", "CORS_ORIGINS"):
        monkeypatch.delenv(var, raising=False)

    repo_root = BACKEND_DIR.parent

    # 1. Test when invoked from repository root
    monkeypatch.chdir(repo_root)
    settings_root = Settings()
    assert settings_root.PROJECT_NAME == "Isolated App Name"
    assert settings_root.ENVIRONMENT == "testing-isolated"
    assert settings_root.DEBUG is False
    assert settings_root.DATABASE_URL == "postgresql+asyncpg://dummy_user:dummy_password@test.dummy.supabase.co:5432/dummy_db"
    assert "http://isolated.local:8081" in settings_root.CORS_ORIGINS

    # 2. Test when invoked from backend directory
    monkeypatch.chdir(BACKEND_DIR)
    settings_backend = Settings()
    assert settings_backend.PROJECT_NAME == "Isolated App Name"
    assert settings_backend.ENVIRONMENT == "testing-isolated"
    assert settings_backend.DEBUG is False
    assert settings_backend.DATABASE_URL == "postgresql+asyncpg://dummy_user:dummy_password@test.dummy.supabase.co:5432/dummy_db"
    assert "http://isolated.local:8081" in settings_backend.CORS_ORIGINS

    # 3. Test when invoked from unrelated arbitrary working directory
    monkeypatch.chdir(tmp_path)
    settings_tmp = Settings()
    assert settings_tmp.PROJECT_NAME == "Isolated App Name"
    assert settings_tmp.DATABASE_URL == settings_root.DATABASE_URL == settings_backend.DATABASE_URL


def test_env_file_direct_parameter_from_different_cwds(tmp_path, monkeypatch):
    """Verify that Settings(_env_file=...) works consistently across working directories."""
    dummy_env = tmp_path / "direct.env"
    dummy_env.write_text(
        "PROJECT_NAME=Direct Parameter App\n"
        "DATABASE_URL=postgresql://direct_user:direct_pass@dummyhost:5432/direct_db\n",
        encoding="utf-8",
    )

    for var in ("PROJECT_NAME", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)

    repo_root = BACKEND_DIR.parent

    monkeypatch.chdir(repo_root)
    s_root = Settings(_env_file=dummy_env)
    assert s_root.PROJECT_NAME == "Direct Parameter App"
    assert s_root.DATABASE_URL == "postgresql+asyncpg://direct_user:direct_pass@dummyhost:5432/direct_db"

    monkeypatch.chdir(BACKEND_DIR)
    s_backend = Settings(_env_file=dummy_env)
    assert s_backend.PROJECT_NAME == "Direct Parameter App"
    assert s_backend.DATABASE_URL == "postgresql+asyncpg://direct_user:direct_pass@dummyhost:5432/direct_db"


def test_env_var_overrides_env_file_precedence(tmp_path, monkeypatch):
    """Verify that environment variables in os.environ override values defined in .env."""
    dummy_env = tmp_path / "override.env"
    dummy_env.write_text(
        "PROJECT_NAME=From Dotenv File\n"
        "DATABASE_URL=postgresql://file_user:file_pass@file-host:5432/file_db\n",
        encoding="utf-8",
    )

    # Set overriding environment variables
    monkeypatch.setenv("PROJECT_NAME", "Overridden by OS Env")
    monkeypatch.setenv("DATABASE_URL", "postgresql://env_user:env_pass@env-host:5432/env_db")

    s = Settings(_env_file=dummy_env)
    assert s.PROJECT_NAME == "Overridden by OS Env"
    assert s.DATABASE_URL == "postgresql+asyncpg://env_user:env_pass@env-host:5432/env_db"


def test_isolated_clean_defaults_without_env_file(monkeypatch):
    """Verify that Settings can instantiate cleanly with defaults when _env_file=None and env is clean."""
    for var in ("PROJECT_NAME", "ENVIRONMENT", "DEBUG", "DATABASE_URL", "CORS_ORIGINS"):
        monkeypatch.delenv(var, raising=False)

    s = Settings(_env_file=None)
    assert s.PROJECT_NAME == "Smart Expense Splitter Backend"
    assert s.ENVIRONMENT == "development"
    assert s.DEBUG is True
    assert s.DATABASE_URL == "postgresql+asyncpg://postgres:postgres@localhost:5432/expense_tracker"


def test_jwt_secret_key_validation():
    # 1. In development: default key is allowed
    dev_settings = Settings(
        ENVIRONMENT="development",
        JWT_SECRET_KEY="dev-secret-key-change-in-production-at-least-32-bytes-long",
    )
    assert dev_settings.JWT_SECRET_KEY == "dev-secret-key-change-in-production-at-least-32-bytes-long"

    # 2. In non-development (production): default key must be rejected
    import pytest
    with pytest.raises(ValueError, match="must not be the default value"):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="dev-secret-key-change-in-production-at-least-32-bytes-long",
        )

    # 3. In non-development (production): key shorter than 32 chars must be rejected
    with pytest.raises(ValueError, match="at least 32 characters long"):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="too-short-secret-key",
        )

    # 4. In non-development (production): valid key >= 32 chars is accepted
    prod_settings = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="production-secret-key-that-is-at-least-32-bytes-long",
    )
    assert prod_settings.JWT_SECRET_KEY == "production-secret-key-that-is-at-least-32-bytes-long"

    # 5. In staging: default key must be rejected
    with pytest.raises(ValueError, match="must not be the default value"):
        Settings(
            ENVIRONMENT="staging",
            JWT_SECRET_KEY="dev-secret-key-change-in-production-at-least-32-bytes-long",
        )

    # 6. In test: default key must be rejected when ENVIRONMENT != 'development'
    with pytest.raises(ValueError, match="must not be the default value"):
        Settings(
            ENVIRONMENT="test",
            JWT_SECRET_KEY="dev-secret-key-change-in-production-at-least-32-bytes-long",
        )


    # 7. JWT_SECRET alias is accepted (preserves existing Render / .env compatibility without rotation)
    alias_settings = Settings(
        ENVIRONMENT="production",
        JWT_SECRET="alias-secret-key-that-is-at-least-32-bytes-long",
    )
    assert alias_settings.JWT_SECRET_KEY == "alias-secret-key-that-is-at-least-32-bytes-long"
