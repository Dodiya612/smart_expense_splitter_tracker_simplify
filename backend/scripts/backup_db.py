"""Encrypted PostgreSQL backup with exact row counts (T-51 / US-34).

Usage (from backend/):
    python scripts/backup_db.py            # back up, then apply 14-day retention
    python scripts/backup_db.py --dry-run  # only show what retention would delete

Environment (never stored in the repository):
    BACKUP_DATABASE_URL    source database (postgres://, postgresql:// or postgresql+asyncpg://)
    BACKUP_PASSPHRASE      encryption passphrase (at least 12 characters)
    BACKUP_DIR             optional; default ~/coinscious-backups (never inside the repository)
    BACKUP_RETENTION_DAYS  optional; default 14, minimum 1
    PG_BIN_DIR, OPENSSL_BIN optional tool locations if they are not on PATH

How it works:
1. A REPEATABLE READ, read-only transaction exports its snapshot and counts the
   rows of every table in the public schema inside that snapshot.
2. pg_dump --snapshot=<id> dumps the same moment (custom format, public schema,
   no owners or privileges) straight into openssl through a pipe, so no
   unencrypted dump is ever written to disk. If the server refuses the exported
   snapshot (some connection poolers), it dumps without it and counts again
   afterwards; the manifest says which happened.
3. openssl encrypts with AES-256-CBC, a random salt and PBKDF2-SHA256 (600,000
   iterations); the passphrase reaches openssl through an environment variable.
4. <stamp>.dump.enc and <stamp>.manifest.json are written; then backups of this
   script older than the retention period are deleted (the newest is always kept).

Exit codes: 0 ok, 1 failed, 2 configuration or safety refusal, 3 row counts changed during a
backup taken without a snapshot (the backup is kept; run again in a quiet period).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backup_common as bc  # noqa: E402


class SnapshotRejected(Exception):
    """pg_dump could not import the exported snapshot."""


def _drain(stream: IO[bytes], sink: list[bytes]) -> None:
    sink.append(stream.read())


def tool_version(tool: str) -> str:
    result = subprocess.run([tool, "version" if tool.lower().endswith(("openssl", "openssl.exe")) else "--version"],
                            capture_output=True, text=True, env=bc.child_env())
    return (result.stdout or result.stderr).strip().splitlines()[0] if result.returncode == 0 else "unknown"


def dump_encrypted(
    pg_dump: str,
    openssl: str,
    target: bc.DbTarget,
    passphrase: str,
    out_part: Path,
    snapshot: str | None,
) -> None:
    """pg_dump | openssl enc > out_part. Raises SnapshotRejected or ScriptError; never leaves plaintext."""
    dump_cmd = [pg_dump, "--format=custom", "--schema=public", "--no-owner", "--no-privileges"]
    if snapshot:
        dump_cmd.append(f"--snapshot={snapshot}")
    enc_cmd = [
        openssl, "enc", f"-{bc.CIPHER}", "-salt", "-pbkdf2", "-iter", str(bc.PBKDF2_ITERATIONS),
        "-md", bc.KDF_DIGEST, "-pass", f"env:{bc.OPENSSL_PASS_VAR}", "-out", str(out_part),
    ]
    dump_err: list[bytes] = []
    try:
        dump = subprocess.Popen(dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=target.libpq_env())
        assert dump.stdout is not None and dump.stderr is not None
        reader = threading.Thread(target=_drain, args=(dump.stderr, dump_err), daemon=True)
        reader.start()
        enc = subprocess.Popen(
            enc_cmd, stdin=dump.stdout, stderr=subprocess.PIPE,
            env=bc.child_env(**{bc.OPENSSL_PASS_VAR: passphrase}),
        )
        dump.stdout.close()  # openssl owns the read end now
        _, enc_err = enc.communicate()
        dump.wait()
        reader.join()
    except OSError as exc:
        out_part.unlink(missing_ok=True)
        raise bc.ScriptError(f"Could not start pg_dump/openssl: {exc}") from exc

    if dump.returncode != 0 or enc.returncode != 0:
        out_part.unlink(missing_ok=True)
        message = b"".join(dump_err).decode(errors="replace").strip()
        if snapshot and "snapshot" in message.lower():
            raise SnapshotRejected(message)
        detail = message or enc_err.decode(errors="replace").strip() or "no error output"
        tool = "pg_dump" if dump.returncode != 0 else "openssl"
        raise bc.ScriptError(f"{tool} failed: {bc.mask_secrets(detail.splitlines()[-1], passphrase, target.password)}")
    if not out_part.is_file() or out_part.stat().st_size == 0:
        out_part.unlink(missing_ok=True)
        raise bc.ScriptError("The encrypted backup is empty.")


def read_details(conn: Any, tables: dict[str, int]) -> tuple[list[str], list[dict[str, str]]]:
    alembic: list[str] = []
    if "alembic_version" in tables:
        alembic = [r[0] for r in conn.execute("SELECT version_num FROM public.alembic_version ORDER BY 1").fetchall()]
    extensions = [
        {"name": r[0], "schema": r[1], "version": r[2]}
        for r in conn.execute(
            "SELECT e.extname, n.nspname, e.extversion FROM pg_catalog.pg_extension e "
            "JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace ORDER BY e.extname"
        ).fetchall()
    ]
    return alembic, extensions


def apply_retention(backup_dir: Path, days: int, dry_run: bool, now: datetime) -> list[str]:
    names = [p.name for p in backup_dir.iterdir() if p.is_file()] if backup_dir.is_dir() else []
    expired = bc.select_expired(names, now, days)
    if not dry_run:
        for name in expired:
            (backup_dir / name).unlink(missing_ok=True)
    return expired


def run_backup(backup_dir: Path, days: int) -> int:
    passphrase = bc.require_passphrase()
    target = bc.parse_db_url(bc.require_env("BACKUP_DATABASE_URL"))
    pg_dump = bc.find_tool("pg_dump")
    openssl = bc.find_tool("openssl")
    try:
        import psycopg
    except ImportError:
        raise bc.ScriptError("psycopg is not installed; run from backend/.venv.", bc.EXIT_CONFIG) from None

    backup_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    stem = bc.backup_stem(now)
    dump_path = backup_dir / f"{stem}{bc.DUMP_SUFFIX}"
    manifest_path = backup_dir / f"{stem}{bc.MANIFEST_SUFFIX}"
    if dump_path.exists():
        raise bc.ScriptError(f"{dump_path.name} already exists; wait a second and run again.")
    part = dump_path.with_name(dump_path.name + ".part")

    print(f"Backup of {target.masked()}")
    snapshot_note = ""
    counts_after: dict[str, int] | None = None
    try:
        with psycopg.connect(**target.connect_kwargs()) as conn:
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            conn.read_only = True
            server_version = str(conn.execute("SHOW server_version").fetchone()[0])
            snapshot: str | None
            try:
                snapshot = str(conn.execute("SELECT pg_export_snapshot()").fetchone()[0])
            except psycopg.Error as exc:
                conn.rollback()
                snapshot, snapshot_note = None, f"pg_export_snapshot unavailable ({type(exc).__name__})"
            counts = bc.count_tables(conn)
            alembic, extensions = read_details(conn, counts)
            try:
                dump_encrypted(pg_dump, openssl, target, passphrase, part, snapshot)
            except SnapshotRejected:
                snapshot, snapshot_note = None, "the server refused the exported snapshot (connection pooler?)"
                dump_encrypted(pg_dump, openssl, target, passphrase, part, None)
            if snapshot is None:
                conn.rollback()  # new transaction: count again after the dump
                counts_after = bc.count_tables(conn)
    except psycopg.Error as exc:
        part.unlink(missing_ok=True)
        raise bc.ScriptError(f"Database error: {bc.mask_secrets(str(exc).splitlines()[0], passphrase, target.password)}") from None

    part.replace(dump_path)
    stable = counts_after is None or counts_after == counts
    manifest = {
        "format_version": 1,
        "created_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file": dump_path.name,
        "sha256": bc.sha256_file(dump_path),
        "size_bytes": dump_path.stat().st_size,
        "source": {"host": bc.mask_host(target.host), "database": target.dbname, "server_version": server_version},
        "pg_dump_version": tool_version(pg_dump),
        "dump": {"format": "custom", "schema": "public", "no_owner": True, "no_privileges": True},
        "encryption": {
            "tool": tool_version(openssl), "cipher": bc.CIPHER, "kdf": "pbkdf2",
            "digest": bc.KDF_DIGEST, "iterations": bc.PBKDF2_ITERATIONS, "salt": True,
        },
        "snapshot": {"used": snapshot is not None, "note": snapshot_note or "dump and counts share one snapshot"},
        "row_counts_exact": snapshot is not None or stable,
        "tables": counts_after if counts_after is not None else counts,
        "alembic_version": alembic,
        "extensions": extensions,
    }
    bc.write_manifest(manifest_path, manifest)

    print(f"Server {server_version}; snapshot {'used' if snapshot else 'NOT used: ' + snapshot_note}")
    print(f"Tables: {len(counts)}, rows: {sum(manifest['tables'].values())}")
    print(f"Saved:    {dump_path} ({manifest['size_bytes']} bytes, sha256 {manifest['sha256'][:12]}...)")
    print(f"Manifest: {manifest_path}")
    deleted = apply_retention(backup_dir, days, dry_run=False, now=now)
    print(f"Retention ({days} days): deleted {len(deleted)} file(s)" + (": " + ", ".join(deleted) if deleted else ""))
    if not stable:
        print("WARNING: rows changed while the backup ran without a snapshot; the row counts may not match "
              "the dump. The backup is kept; run it again in a quiet period.", file=sys.stderr)
        return bc.EXIT_VERIFY
    print("OK")
    return bc.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Encrypted PostgreSQL backup (Coinscious).")
    parser.add_argument("--dry-run", action="store_true", help="only show what retention would delete")
    parser.add_argument("--retention-days", help=f"override BACKUP_RETENTION_DAYS (default {bc.DEFAULT_RETENTION_DAYS})")
    args = parser.parse_args(argv)
    try:
        backup_dir = bc.resolve_backup_dir()
        days = bc.retention_days(args.retention_days)
        if args.dry_run:
            would = apply_retention(backup_dir, days, dry_run=True, now=datetime.now(UTC))
            print(f"Dry run: backups in {backup_dir}; retention {days} days.")
            print(f"Would delete {len(would)} file(s)" + (": " + ", ".join(would) if would else "."))
            return bc.EXIT_OK
        return run_backup(backup_dir, days)
    except bc.ScriptError as exc:
        return bc.fail(exc, os.environ.get("BACKUP_PASSPHRASE", ""))


if __name__ == "__main__":
    sys.exit(main())
