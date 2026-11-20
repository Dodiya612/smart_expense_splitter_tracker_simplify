"""Restore drill: restore an encrypted backup into a NEW local scratch database and
check that every table's row count matches the manifest (T-51 / US-34).

Usage (from backend/):
    python scripts/restore_drill.py                 # newest backup in BACKUP_DIR
    python scripts/restore_drill.py <file.dump.enc> # a specific backup
    python scripts/restore_drill.py latest --keep   # keep the scratch database afterwards

Environment (never stored in the repository):
    RESTORE_ADMIN_URL   admin URL of a LOCAL server (localhost, 127.0.0.1 or ::1 only)
    BACKUP_PASSPHRASE   the passphrase the backup was made with
    BACKUP_DIR          optional; where "latest" is looked up (default ~/coinscious-backups)
    PG_BIN_DIR, OPENSSL_BIN optional tool locations if they are not on PATH

Steps: verify the sha256 from the manifest; decrypt to a temporary file in the
system temp folder; check it is a pg_dump archive; create a new scratch database;
create the extensions the source had (e.g. pg_trgm); pg_restore --no-owner
--no-privileges --exit-on-error; compare row counts and alembic_version; drop the
scratch database (unless --keep); always delete the decrypted file.

Exit codes: 0 restore completed and everything matches, 1 failed (wrong passphrase,
restore error), 2 configuration or safety refusal, 3 verification failed (checksum,
missing table, row count or alembic_version mismatch).
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backup_common as bc  # noqa: E402


def decrypt(openssl: str, encrypted: Path, plain: Path, manifest: dict[str, Any], passphrase: str) -> None:
    enc = manifest["encryption"]
    cmd = [
        openssl, "enc", "-d", f"-{enc.get('cipher', bc.CIPHER)}", "-pbkdf2",
        "-iter", str(enc.get("iterations", bc.PBKDF2_ITERATIONS)), "-md", enc.get("digest", bc.KDF_DIGEST),
        "-pass", f"env:{bc.OPENSSL_PASS_VAR}", "-in", str(encrypted), "-out", str(plain),
    ]
    result = subprocess.run(cmd, capture_output=True, env=bc.child_env(**{bc.OPENSSL_PASS_VAR: passphrase}))
    if result.returncode != 0:
        raise bc.ScriptError("Could not decrypt the backup: wrong BACKUP_PASSPHRASE or a damaged file.")


def write_restore_list(pg_restore: str, plain: Path, list_path: Path) -> None:
    """Check the file is a pg_dump archive and write the TOC to restore (public schema entries removed)."""
    result = subprocess.run([pg_restore, "--list", str(plain)], capture_output=True, text=True, env=bc.child_env())
    if result.returncode != 0:
        raise bc.ScriptError("The decrypted file is not a pg_dump archive (wrong passphrase or damaged file).")
    lines = bc.restore_list(result.stdout.splitlines())
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_extensions(conn: Any, extensions: list[dict[str, str]]) -> list[str]:
    from psycopg import sql

    available = {r[0] for r in conn.execute("SELECT name FROM pg_catalog.pg_available_extensions").fetchall()}
    skipped: list[str] = []
    for ext in extensions:
        name, schema = ext.get("name", ""), ext.get("schema", "public")
        if not name or name == "plpgsql":
            continue
        if name not in available:
            skipped.append(name)
            continue
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS {} WITH SCHEMA {}").format(
            sql.Identifier(name), sql.Identifier(schema)))
    return skipped


def run_drill(backup_arg: str, keep: bool) -> int:
    passphrase = bc.require_passphrase()
    admin = bc.parse_db_url(bc.require_env("RESTORE_ADMIN_URL"))
    bc.require_local(admin)
    dump_path = bc.latest_backup(bc.resolve_backup_dir()) if backup_arg == "latest" else Path(backup_arg).expanduser()
    if not dump_path.is_file():
        raise bc.ScriptError(f"Backup file not found: {dump_path}", bc.EXIT_CONFIG)
    manifest = bc.read_manifest(bc.manifest_path_for(dump_path))
    openssl = bc.find_tool("openssl")
    pg_restore = bc.find_tool("pg_restore")
    try:
        import psycopg
        from psycopg import sql
    except ImportError:
        raise bc.ScriptError("psycopg is not installed; run from backend/.venv.", bc.EXIT_CONFIG) from None

    print(f"Backup:   {dump_path.name} (made {manifest.get('created_at_utc', '?')}, "
          f"source {manifest.get('source', {}).get('host', '?')})")
    if bc.sha256_file(dump_path) != manifest["sha256"]:
        raise bc.ScriptError("Checksum mismatch: the backup file was changed or damaged.", bc.EXIT_VERIFY)
    print("Checksum: OK")
    if not manifest.get("row_counts_exact", True):
        print("WARNING: this backup's row counts were not taken in the dump's snapshot.", file=sys.stderr)

    temp_dir = Path(tempfile.gettempdir())
    if bc.is_inside(temp_dir, bc.REPO_ROOT):
        raise bc.ScriptError("The system temp folder is inside the repository; set TMP/TEMP elsewhere.", bc.EXIT_CONFIG)
    fd, plain_name = tempfile.mkstemp(prefix="coinscious-restore-", suffix=".dump", dir=temp_dir)
    os.close(fd)
    plain = Path(plain_name)
    toc = plain.with_suffix(".list")
    scratch_name = "coinscious_restore_drill_" + datetime.now(UTC).strftime("%Y%m%d%H%M%S") + "_" + secrets.token_hex(3)
    scratch = admin.with_dbname(scratch_name)
    created = False
    try:
        decrypt(openssl, dump_path, plain, manifest, passphrase)
        write_restore_list(pg_restore, plain, toc)
        print("Decrypt:  OK")

        with psycopg.connect(**admin.connect_kwargs(), autocommit=True) as conn:
            if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (scratch_name,)).fetchone():
                raise bc.ScriptError(f"Scratch database {scratch_name} already exists.", bc.EXIT_CONFIG)
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch_name)))
            created = True
        print(f"Scratch:  {scratch.masked()}")

        with psycopg.connect(**scratch.connect_kwargs(), autocommit=True) as conn:
            skipped = create_extensions(conn, manifest.get("extensions", []))
        if skipped:
            print(f"Note: extensions not available locally, skipped: {', '.join(skipped)}")

        result = subprocess.run(
            [pg_restore, "--no-owner", "--no-privileges", "--exit-on-error", f"--use-list={toc}",
             f"--dbname={scratch_name}", str(plain)],
            capture_output=True, text=True, env=scratch.libpq_env(),
        )
        if result.returncode != 0:
            last = (result.stderr.strip().splitlines() or ["no error output"])[-1]
            raise bc.ScriptError(f"pg_restore failed: {bc.mask_secrets(last, passphrase, admin.password)}")
        print("Restore:  completed")

        with psycopg.connect(**scratch.connect_kwargs()) as conn:
            restored = bc.count_tables(conn)
            alembic = ([r[0] for r in conn.execute("SELECT version_num FROM public.alembic_version ORDER BY 1")]
                       if "alembic_version" in restored else [])

        rows = bc.compare_counts({k: int(v) for k, v in manifest["tables"].items()}, restored)
        print()
        print(bc.format_count_table(rows))
        print()
        alembic_ok = alembic == manifest.get("alembic_version", [])
        print(f"alembic_version: expected {manifest.get('alembic_version', [])}, restored {alembic} "
              f"-> {'OK' if alembic_ok else 'MISMATCH'}")
        mismatches = [r.table for r in rows if not r.ok]
        if mismatches or not alembic_ok:
            print(f"FAILED: {len(mismatches)} table(s) differ" + (f": {', '.join(mismatches)}" if mismatches else ""),
                  file=sys.stderr)
            return bc.EXIT_VERIFY
        print(f"OK: restore completed and all {len(rows)} tables match ({sum(restored.values())} rows).")
        return bc.EXIT_OK
    except psycopg.Error as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise bc.ScriptError(f"Database error: {bc.mask_secrets(first, passphrase, admin.password)}") from None
    finally:
        plain.unlink(missing_ok=True)
        toc.unlink(missing_ok=True)
        if created and not keep:
            with psycopg.connect(**admin.connect_kwargs(), autocommit=True) as conn:
                conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                    (scratch_name,),
                )
                conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(scratch_name)))
            print(f"Dropped scratch database {scratch_name}.")
        elif created:
            print(f"Kept scratch database {scratch_name} (--keep). Drop it when done.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore drill into a local scratch database (Coinscious).")
    parser.add_argument("backup", nargs="?", default="latest", help="a .dump.enc file, or 'latest' (default)")
    parser.add_argument("--keep", action="store_true", help="keep the scratch database after the drill")
    args = parser.parse_args(argv)
    try:
        return run_drill(args.backup, args.keep)
    except bc.ScriptError as exc:
        return bc.fail(exc, os.environ.get("BACKUP_PASSPHRASE", ""))


if __name__ == "__main__":
    sys.exit(main())
