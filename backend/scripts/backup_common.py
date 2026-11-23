"""Shared helpers for backup_db.py and restore_drill.py (T-51 / US-34).

Standard library only, so the pure parts can be unit tested without a database.
Secrets (database passwords, the backup passphrase) are only ever read from
environment variables, passed to child processes through their environment
(never on a command line), and never printed: URLs are always shown masked.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

# Exit codes shared by both scripts.
EXIT_OK = 0
EXIT_FAILED = 1  # a tool or database step failed (wrong passphrase, pg_dump error, ...)
EXIT_CONFIG = 2  # missing/invalid settings or a safety check refused to run
EXIT_VERIFY = 3  # verification failed (checksum, row counts, alembic version)

# Encryption parameters (openssl enc). Recorded in each manifest.
CIPHER = "aes-256-cbc"
KDF_DIGEST = "sha256"
PBKDF2_ITERATIONS = 600_000
MIN_PASSPHRASE_LENGTH = 12

DEFAULT_RETENTION_DAYS = 14
DEFAULT_BACKUP_DIR = Path.home() / "coinscious-backups"

FILE_PREFIX = "coinscious-"
DUMP_SUFFIX = ".dump.enc"
MANIFEST_SUFFIX = ".manifest.json"
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
#: The ONLY files retention may ever delete.
BACKUP_NAME_RE = re.compile(r"^coinscious-(\d{8}T\d{6}Z)(\.dump\.enc|\.manifest\.json)$")

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
SUPPORTED_SCHEMES = {"postgres", "postgresql", "postgresql+asyncpg", "postgresql+psycopg", "postgresql+psycopg2"}
#: Query parameters libpq understands; driver-only ones (e.g. asyncpg cache sizes) are dropped.
LIBPQ_PARAMS = {"sslmode", "sslrootcert", "connect_timeout", "application_name", "options", "target_session_attrs"}

REPO_ROOT = Path(__file__).resolve().parents[2]


#: Never passed on to child processes (openssl gets the passphrase under its own name).
SECRET_ENV_VARS = frozenset({"BACKUP_PASSPHRASE", "BACKUP_DATABASE_URL", "RESTORE_ADMIN_URL", "DATABASE_URL"})
OPENSSL_PASS_VAR = "COINSCIOUS_BACKUP_PASSPHRASE"


def child_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() not in SECRET_ENV_VARS and k != OPENSSL_PASS_VAR}
    env.update(extra)
    return env


class ScriptError(Exception):
    """A failure with a short, user-facing message and an exit code."""

    def __init__(self, message: str, code: int = EXIT_FAILED) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Environment and URLs
# ---------------------------------------------------------------------------


def require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        raise ScriptError(f"{name} is not set. Set it in your shell; it is never read from the repository.", EXIT_CONFIG)
    return value


def require_passphrase() -> str:
    value = require_env("BACKUP_PASSPHRASE")
    if len(value) < MIN_PASSPHRASE_LENGTH:
        raise ScriptError(f"BACKUP_PASSPHRASE must be at least {MIN_PASSPHRASE_LENGTH} characters.", EXIT_CONFIG)
    return value


@dataclass(frozen=True)
class DbTarget:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    dbname: str
    params: dict[str, str] = field(default_factory=dict)

    def masked(self) -> str:
        """URL for display: never contains the password."""
        user = f"{self.user}:***@" if self.user else ""
        return f"postgresql://{user}{self.host}:{self.port}/{self.dbname}"

    def with_dbname(self, dbname: str) -> DbTarget:
        return DbTarget(self.host, self.port, self.user, self.password, dbname, dict(self.params))

    def libpq_env(self) -> dict[str, str]:
        """Child-process environment: inherited vars without any PG* or backup secrets, plus this target."""
        env = {k: v for k, v in child_env().items() if not k.upper().startswith("PG")}
        env.update(PGHOST=self.host, PGPORT=str(self.port), PGUSER=self.user, PGDATABASE=self.dbname)
        if self.password:
            env["PGPASSWORD"] = self.password
        if "sslmode" in self.params:
            env["PGSSLMODE"] = self.params["sslmode"]
        if "sslrootcert" in self.params:
            env["PGSSLROOTCERT"] = self.params["sslrootcert"]
        if "connect_timeout" in self.params:
            env["PGCONNECT_TIMEOUT"] = self.params["connect_timeout"]
        if "options" in self.params:
            env["PGOPTIONS"] = self.params["options"]
        return env

    def connect_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "dbname": self.dbname,
            "connect_timeout": int(self.params.get("connect_timeout", "15")),
        }
        for key in ("sslmode", "sslrootcert", "application_name", "options", "target_session_attrs"):
            if key in self.params:
                kwargs[key] = self.params[key]
        return kwargs


def parse_db_url(url: str) -> DbTarget:
    """Accepts postgres://, postgresql:// and postgresql+asyncpg:// (and +psycopg) URLs."""
    parts = urlsplit(url.strip())
    if parts.scheme not in SUPPORTED_SCHEMES:
        raise ScriptError("The database URL must start with postgresql:// (or postgres://, postgresql+asyncpg://).", EXIT_CONFIG)
    if not parts.hostname:
        raise ScriptError("The database URL has no host name.", EXIT_CONFIG)
    dbname = unquote(parts.path.lstrip("/")) or "postgres"
    params: dict[str, str] = {}
    for key, values in parse_qs(parts.query).items():
        value = values[-1]
        if key == "ssl":  # asyncpg style: ?ssl=require
            params["sslmode"] = "disable" if value.lower() in {"false", "disable", "0"} else (
                "require" if value.lower() in {"true", "1"} else value
            )
        elif key in LIBPQ_PARAMS:
            params[key] = value
    return DbTarget(
        host=parts.hostname,
        port=parts.port or 5432,
        user=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
        dbname=dbname,
        params=params,
    )


def mask_host(host: str) -> str:
    """'aws-0-ap-south-1.pooler.supabase.com' -> '***.supabase.com'; local names unchanged."""
    if host in LOCAL_HOSTS or "." not in host:
        return host
    labels = host.split(".")
    return host if len(labels) <= 2 else "***." + ".".join(labels[-2:])


def mask_secrets(text: str, *secrets: str) -> str:
    """Remove secrets and URL passwords from tool output before printing it."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return re.sub(r"(postgres(?:ql)?(?:\+\w+)?://[^:/@\s]*):[^@\s]*@", r"\1:***@", text)


def require_local(target: DbTarget) -> None:
    if target.host not in LOCAL_HOSTS:
        raise ScriptError(
            f"Refusing to restore to '{mask_host(target.host)}': the restore drill only runs against "
            "localhost, 127.0.0.1 or ::1.",
            EXIT_CONFIG,
        )


# ---------------------------------------------------------------------------
# Folders and tools
# ---------------------------------------------------------------------------


def is_inside(path: Path, root: Path) -> bool:
    p = os.path.normcase(str(path.resolve()))
    r = os.path.normcase(str(root.resolve()))
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def resolve_backup_dir(value: str | None = None, repo_root: Path = REPO_ROOT) -> Path:
    raw = value if value is not None else os.environ.get("BACKUP_DIR", "")
    path = Path(raw).expanduser() if raw.strip() else DEFAULT_BACKUP_DIR
    if is_inside(path, repo_root):
        raise ScriptError(
            "Refusing to keep backups inside the repository. Set BACKUP_DIR to a folder outside it "
            f"(default: {DEFAULT_BACKUP_DIR}).",
            EXIT_CONFIG,
        )
    return path


def retention_days(value: str | None = None) -> int:
    raw = value if value is not None else os.environ.get("BACKUP_RETENTION_DAYS", "")
    if not str(raw).strip():
        return DEFAULT_RETENTION_DAYS
    try:
        days = int(raw)
    except ValueError:
        raise ScriptError("BACKUP_RETENTION_DAYS must be a whole number of days.", EXIT_CONFIG) from None
    if days < 1:
        raise ScriptError("BACKUP_RETENTION_DAYS must be at least 1.", EXIT_CONFIG)
    return days


def _windows_candidates(tool: str) -> list[Path]:
    if os.name != "nt":
        return []
    found: list[Path] = []
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        if not base:
            continue
        if tool == "openssl":
            for sub in (r"Git\ucrt64\bin", r"Git\mingw64\bin", r"Git\usr\bin"):
                found.append(Path(base) / sub / "openssl.exe")
        else:
            pg_root = Path(base) / "PostgreSQL"
            if pg_root.is_dir():
                versions = sorted(
                    (d for d in pg_root.iterdir() if d.name.isdigit()), key=lambda d: int(d.name), reverse=True
                )
                found.extend(d / "bin" / f"{tool}.exe" for d in versions)
    return found


def find_tool(tool: str) -> str:
    """PATH first, then PG_BIN_DIR / OPENSSL_BIN, then the usual Windows install folders."""
    override = os.environ.get("OPENSSL_BIN") if tool == "openssl" else None
    if override:
        if Path(override).is_file():
            return override
        raise ScriptError(f"OPENSSL_BIN does not point to a file: {override}", EXIT_CONFIG)
    pg_bin = os.environ.get("PG_BIN_DIR")
    if tool != "openssl" and pg_bin:
        candidate = shutil.which(tool, path=pg_bin)
        if candidate:
            return candidate
        raise ScriptError(f"{tool} was not found in PG_BIN_DIR ({pg_bin}).", EXIT_CONFIG)
    on_path = shutil.which(tool)
    if on_path:
        return on_path
    for candidate in _windows_candidates(tool):
        if candidate.is_file():
            return str(candidate)
    hint = "Install Git for Windows / OpenSSL or set OPENSSL_BIN." if tool == "openssl" else (
        "Install the PostgreSQL client tools or set PG_BIN_DIR to their bin folder."
    )
    raise ScriptError(f"{tool} was not found. {hint}", EXIT_CONFIG)


# ---------------------------------------------------------------------------
# Backup files and retention
# ---------------------------------------------------------------------------


def backup_stem(moment: datetime) -> str:
    return FILE_PREFIX + moment.astimezone(UTC).strftime(TIMESTAMP_FORMAT)


def parse_backup_name(name: str) -> datetime | None:
    match = BACKUP_NAME_RE.match(name)
    if not match:
        return None
    return datetime.strptime(match.group(1), TIMESTAMP_FORMAT).replace(tzinfo=UTC)


def select_expired(names: list[str], now: datetime, days: int) -> list[str]:
    """Own backup files older than ``days`` (by the UTC time in their name).

    Never selects a file that does not match this script's exact naming pattern,
    and always keeps the newest backup, even if it is older than the limit.
    """
    stamped = [(n, ts) for n in names if (ts := parse_backup_name(n)) is not None]
    if not stamped:
        return []
    newest = max(ts for _, ts in stamped)
    cutoff = now - timedelta(days=days)
    return sorted(n for n, ts in stamped if ts < cutoff and ts != newest)


def latest_backup(backup_dir: Path) -> Path:
    dumps = sorted(
        (p for p in backup_dir.glob(f"{FILE_PREFIX}*{DUMP_SUFFIX}") if parse_backup_name(p.name)),
        key=lambda p: p.name,
    )
    if not dumps:
        raise ScriptError(f"No backups found in {backup_dir}.", EXIT_CONFIG)
    return dumps[-1]


def manifest_path_for(dump_path: Path) -> Path:
    if not dump_path.name.endswith(DUMP_SUFFIX):
        raise ScriptError(f"Not a backup file (expected *{DUMP_SUFFIX}): {dump_path.name}", EXIT_CONFIG)
    return dump_path.with_name(dump_path.name[: -len(DUMP_SUFFIX)] + MANIFEST_SUFFIX)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ScriptError(f"Manifest not found next to the backup: {path.name}", EXIT_VERIFY)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScriptError(f"Manifest is not valid JSON: {path.name}", EXIT_VERIFY) from exc
    for key in ("sha256", "tables", "encryption"):
        if key not in data:
            raise ScriptError(f"Manifest is missing '{key}': {path.name}", EXIT_VERIFY)
    if not isinstance(data["tables"], dict):
        raise ScriptError(f"Manifest 'tables' must be an object: {path.name}", EXIT_VERIFY)
    return data


@dataclass(frozen=True)
class CountRow:
    table: str
    expected: int | None
    restored: int | None

    @property
    def ok(self) -> bool:
        return self.expected is not None and self.expected == self.restored


def compare_counts(expected: dict[str, int], restored: dict[str, int]) -> list[CountRow]:
    """One row per table in either side; a table missing on one side is a mismatch."""
    return [CountRow(t, expected.get(t), restored.get(t)) for t in sorted(set(expected) | set(restored))]


def format_count_table(rows: list[CountRow]) -> str:
    def cell(value: int | None) -> str:
        return "missing" if value is None else str(value)

    width = max([len("table"), *(len(r.table) for r in rows)])
    lines = [f"{'table':<{width}} | {'expected':>8} | {'restored':>8} | OK"]
    lines.append(f"{'-' * width}-+-{'-' * 8}-+-{'-' * 8}-+---")
    for r in rows:
        lines.append(f"{r.table:<{width}} | {cell(r.expected):>8} | {cell(r.restored):>8} | {'OK' if r.ok else 'NO'}")
    return "\n".join(lines)


#: TOC entries a new database already has; restoring them would fail ("schema public already exists").
_PREEXISTING_TOC = re.compile(r"^\d+;\s+\d+\s+\d+\s+(SCHEMA - public|COMMENT - SCHEMA public)\b")


def restore_list(toc_lines: list[str]) -> list[str]:
    """`pg_restore --list` output without the public schema's own CREATE/COMMENT entries."""
    return [line for line in toc_lines if not _PREEXISTING_TOC.match(line.strip())]


def count_tables(conn: Any) -> dict[str, int]:
    """Exact row count of every table in the public schema (psycopg connection)."""
    from psycopg import sql

    names = [r[0] for r in conn.execute(
        "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    ).fetchall()]
    counts: dict[str, int] = {}
    for name in names:
        query = sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier("public"), sql.Identifier(name))
        counts[name] = int(conn.execute(query).fetchone()[0])
    return counts


def fail(error: ScriptError, *secrets: str) -> int:
    print(f"ERROR: {mask_secrets(str(error), *secrets)}", file=sys.stderr)
    return error.code
