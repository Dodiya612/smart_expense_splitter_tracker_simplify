"""Real-database test of the backup script and the restore drill (T-51 / US-34).

Done when: "restore completes and row counts match". A throwaway LOCAL source
database is built with ``alembic upgrade head`` and realistic rows, backed up with
scripts/backup_db.py, and restored by scripts/restore_drill.py into a scratch
database; every table's row count and alembic_version must match.

Skipped cleanly when no local PostgreSQL is reachable or pg_dump/pg_restore/openssl
are missing. Set COINSCIOUS_TEST_PG_URL to an admin URL on a LOCAL server
(default postgresql://postgres:postgres@localhost:5432/postgres). Every database
this test creates is dropped at the end. It never connects anywhere else.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))

import backup_common as bc  # noqa: E402

ADMIN_URL = os.getenv("COINSCIOUS_TEST_PG_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
PASSPHRASE = "drill-test-passphrase-2026"
GROCERIES = "00000000-0000-4000-8000-000000000002"


def _admin() -> bc.DbTarget:
    return bc.parse_db_url(ADMIN_URL)


def _alembic_head() -> str:
    """The single head of the migration chain (read from Alembic, so new migrations need no test change)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, heads
    return heads[0]


@pytest.fixture(scope="module")
def pg() -> Iterator[dict[str, Any]]:
    try:
        import psycopg
    except ImportError:
        pytest.skip("psycopg is not installed")
    admin = _admin()
    if admin.host not in bc.LOCAL_HOSTS:
        pytest.skip("COINSCIOUS_TEST_PG_URL must point at a local server")
    try:
        tools = {t: bc.find_tool(t) for t in ("pg_dump", "pg_restore", "openssl")}
    except bc.ScriptError as exc:
        pytest.skip(f"Backup tools unavailable: {exc}")
    try:
        with psycopg.connect(**admin.connect_kwargs(), autocommit=True) as conn:
            conn.execute("SELECT 1")
            before = {r[0] for r in conn.execute("SELECT datname FROM pg_database")}
    except psycopg.Error as exc:
        pytest.skip(f"No local PostgreSQL reachable at {admin.masked()} ({type(exc).__name__}).")

    source = f"coinscious_backup_src_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(**admin.connect_kwargs(), autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(source)))
    try:
        yield {"admin": admin, "source": admin.with_dbname(source), "tools": tools}
    finally:
        with psycopg.connect(**admin.connect_kwargs(), autocommit=True) as conn:
            now = {r[0] for r in conn.execute("SELECT datname FROM pg_database")}
            for name in sorted(now - before):
                conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,))
                conn.execute(psycopg.sql.SQL("DROP DATABASE IF EXISTS {}").format(psycopg.sql.Identifier(name)))


def _url(t: bc.DbTarget, scheme: str = "postgresql") -> str:
    return f"{scheme}://{t.user}:{t.password}@{t.host}:{t.port}/{t.dbname}"


def _env(tmp: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() not in bc.SECRET_ENV_VARS}
    env.update(PYTHONPATH=str(BACKEND.parent), TMP=str(tmp), TEMP=str(tmp), TMPDIR=str(tmp))
    env.update(extra)
    return env


def _run(script: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(BACKEND / "scripts" / script), *args],
                          capture_output=True, text=True, env=env, cwd=BACKEND, timeout=600)


def _migrate_and_seed(source: bc.DbTarget, tmp: Path) -> None:
    env = _env(tmp, DATABASE_URL=_url(source, "postgresql+asyncpg"), ENV_FILE=str(tmp / "no-such.env"))
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], capture_output=True,
                            text=True, env=env, cwd=BACKEND, timeout=600)
    assert result.returncode == 0, result.stderr[-2000:]

    import psycopg

    alex, blair, casey = (uuid.uuid4() for _ in range(3))
    group, shared, chai, personal, rule = (uuid.uuid4() for _ in range(5))
    with psycopg.connect(**source.connect_kwargs(), autocommit=True) as c:
        for uid, name in ((alex, "Alex"), (blair, "Blair"), (casey, "Casey")):
            c.execute("INSERT INTO users (id, email, name, hashed_password) VALUES (%s, %s, %s, 'x')",
                      (uid, f"{name.lower()}@example.com", name))
        c.execute("INSERT INTO groups (id, name, type, created_by) VALUES (%s, 'Flat Expenses', 'flat', %s)", (group, alex))
        for i, uid in enumerate((alex, blair, casey)):
            c.execute("INSERT INTO group_members (group_id, user_id, role) VALUES (%s, %s, %s)",
                      (group, uid, "admin" if i == 0 else "member"))
        for eid, payer, amount, desc, gid in (
            (shared, alex, 300000, "Groceries", group), (chai, casey, 10000, "Chai", group),
            (personal, alex, 50000, "Metro recharge", None),
        ):
            c.execute(
                "INSERT INTO expenses (id, user_id, group_id, category_id, amount_minor, description, expense_date,"
                " version, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, '2026-11-16', 1, now(), now())",
                (eid, payer, gid, GROCERIES, amount, desc),
            )
        for eid, payer, total, parts in ((shared, alex, 300000, (100000, 100000, 100000)),
                                         (chai, casey, 10000, (3334, 3333, 3333))):
            c.execute("INSERT INTO expense_payments (expense_id, user_id, amount_paise) VALUES (%s, %s, %s)",
                      (eid, payer, total))
            for uid, part in zip((alex, blair, casey), parts):
                c.execute("INSERT INTO expense_shares (expense_id, user_id, amount_paise) VALUES (%s, %s, %s)",
                          (eid, uid, part))
        c.execute("INSERT INTO settlements (id, group_id, payer_id, payee_id, amount_paise) VALUES (%s, %s, %s, %s, 100000)",
                  (uuid.uuid4(), group, blair, alex))
        for uid in (blair, casey):
            c.execute("INSERT INTO notifications (user_id, group_id, kind, title, body, dedupe_key) VALUES"
                      " (%s, %s, 'group_expense_created', 'New expense', 'Alex added Groceries', %s)",
                      (uid, group, f"group_expense_created:{shared}:{uid}"))
        c.execute("INSERT INTO recurring_rules (id, owner_id, frequency, start_date, next_run_date, amount_paise,"
                  " category_id, description) VALUES (%s, %s, 'monthly', '2026-10-01', '2026-12-01', 49900, %s, 'Gym')",
                  (rule, alex, GROCERIES))
        c.execute("INSERT INTO recurring_occurrences (id, rule_id, occurrence_date, status, expense_id) VALUES"
                  " (%s, %s, '2026-11-01', 'created', %s)", (uuid.uuid4(), rule, personal))
        c.execute("INSERT INTO recurring_occurrences (id, rule_id, occurrence_date, status, skip_reason) VALUES"
                  " (%s, %s, '2026-10-01', 'skipped', 'paused')", (uuid.uuid4(), rule))


def _counts(target: bc.DbTarget) -> dict[str, int]:
    import psycopg

    with psycopg.connect(**target.connect_kwargs()) as conn:
        return bc.count_tables(conn)


def _drill_databases(admin: bc.DbTarget) -> set[str]:
    import psycopg

    with psycopg.connect(**admin.connect_kwargs(), autocommit=True) as conn:
        return {r[0] for r in conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE 'coinscious_restore_drill_%'")}


def test_backup_and_restore_drill_end_to_end(pg, tmp_path):
    admin, source = pg["admin"], pg["source"]
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    backups = tmp_path / "backups"
    _migrate_and_seed(source, tmp)
    source_counts = _counts(source)
    assert source_counts["expense_shares"] == 6
    assert source_counts["recurring_occurrences"] == 2

    common = {"BACKUP_PASSPHRASE": PASSPHRASE, "BACKUP_DIR": str(backups)}

    # A failed backup (database does not exist) leaves nothing behind.
    failed = _run("backup_db.py", _env(tmp, **common, BACKUP_DATABASE_URL=_url(source.with_dbname("no_such_db_t51"))))
    assert failed.returncode == bc.EXIT_FAILED, failed.stdout + failed.stderr
    assert not backups.exists() or list(backups.iterdir()) == []
    # The password never appears (the user name may, in the masked URL "user:***@host").
    assert f":{source.password}@" not in failed.stdout + failed.stderr
    assert ":***@" in failed.stdout

    # The backup.
    backup = _run("backup_db.py", _env(tmp, **common, BACKUP_DATABASE_URL=_url(source, "postgresql+asyncpg")))
    assert backup.returncode == 0, backup.stdout + backup.stderr
    assert "snapshot used" in backup.stdout
    assert PASSPHRASE not in backup.stdout + backup.stderr
    dumps = sorted(backups.glob("coinscious-*.dump.enc"))
    assert len(dumps) == 1
    files = sorted(p.name for p in backups.iterdir())
    assert files == sorted([dumps[0].name, bc.manifest_path_for(dumps[0]).name])  # no .part, no plaintext
    manifest = json.loads(bc.manifest_path_for(dumps[0]).read_text(encoding="utf-8"))
    assert manifest["tables"] == source_counts
    assert manifest["snapshot"]["used"] is True
    assert manifest["row_counts_exact"] is True
    head = _alembic_head()
    assert manifest["alembic_version"] == [head]
    assert {e["name"] for e in manifest["extensions"]} >= {"pg_trgm"}
    assert manifest["sha256"] == bc.sha256_file(dumps[0])
    assert "password" not in json.dumps(manifest).lower()

    # The encrypted file reveals nothing: no pg_dump header, SQL or table names.
    blob = dumps[0].read_bytes()
    for plain in (b"PGDMP", b"CREATE TABLE", b"expenses", b"alembic_version", b"Groceries", b"alex@example.com"):
        assert plain not in blob

    drill_env = _env(tmp, BACKUP_PASSPHRASE=PASSPHRASE, BACKUP_DIR=str(backups), RESTORE_ADMIN_URL=_url(admin))
    existing = _drill_databases(admin)

    # THE DONE-WHEN: restore completes and every row count matches.
    drill = _run("restore_drill.py", drill_env, "latest", "--keep")
    print(drill.stdout)
    assert drill.returncode == 0, drill.stdout + drill.stderr
    assert "Restore:  completed" in drill.stdout
    assert f"OK: restore completed and all {len(source_counts)} tables match" in drill.stdout
    assert " NO" not in drill.stdout
    assert f"alembic_version: expected ['{head}'], restored ['{head}'] -> OK" in drill.stdout
    kept = _drill_databases(admin) - existing
    assert len(kept) == 1
    restored = admin.with_dbname(kept.pop())
    assert _counts(restored) == source_counts  # independent check, straight from the restored database
    import psycopg

    with psycopg.connect(**restored.connect_kwargs()) as conn:
        assert conn.execute("SELECT count(*) FROM pg_extension WHERE extname = 'pg_trgm'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM pg_indexes WHERE indexname = 'ix_expenses_description_trgm'"
                            ).fetchone()[0] == 1
        assert conn.execute("SELECT sum(amount_paise) FROM expense_shares").fetchone()[0] == 310000

    # Without --keep the scratch database is dropped.
    again = _run("restore_drill.py", drill_env, str(dumps[0]))
    assert again.returncode == 0, again.stdout + again.stderr
    assert "Dropped scratch database" in again.stdout

    # A wrong passphrase fails clearly and leaves no scratch database or decrypted file.
    before = _drill_databases(admin)
    wrong = _run("restore_drill.py", {**drill_env, "BACKUP_PASSPHRASE": "not-the-right-passphrase"})
    assert wrong.returncode == bc.EXIT_FAILED, wrong.stdout + wrong.stderr
    assert "wrong BACKUP_PASSPHRASE" in wrong.stderr
    assert _drill_databases(admin) == before

    # A tampered file fails the checksum before anything is decrypted.
    tampered_dir = tmp_path / "tampered"
    tampered_dir.mkdir()
    tampered = tampered_dir / dumps[0].name
    data = bytearray(blob)
    data[len(data) // 2] ^= 0x01
    tampered.write_bytes(bytes(data))
    bc.manifest_path_for(tampered).write_bytes(bc.manifest_path_for(dumps[0]).read_bytes())
    bad = _run("restore_drill.py", drill_env, str(tampered))
    assert bad.returncode == bc.EXIT_VERIFY, bad.stdout + bad.stderr
    assert "Checksum mismatch" in bad.stderr

    # No decrypted dump or restore list is left in the temp folder.
    assert [p.name for p in tmp.iterdir() if p.name.startswith("coinscious-restore-")] == []
