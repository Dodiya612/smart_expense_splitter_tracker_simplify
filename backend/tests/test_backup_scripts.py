"""Unit tests for the backup and restore-drill scripts (T-51 / US-34). No database needed."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import backup_common as bc  # noqa: E402
import backup_db  # noqa: E402
import restore_drill  # noqa: E402

GOOD_PASS = "a-long-test-passphrase"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("BACKUP_DATABASE_URL", "BACKUP_PASSPHRASE", "BACKUP_DIR", "BACKUP_RETENTION_DAYS",
                 "RESTORE_ADMIN_URL", "OPENSSL_BIN", "PG_BIN_DIR"):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# URLs and masking
# ---------------------------------------------------------------------------


def test_parse_url_accepts_supported_schemes_and_maps_ssl():
    t = bc.parse_db_url("postgresql+asyncpg://app:s%40cret@db.example.supabase.co:6543/postgres"
                        "?ssl=require&prepared_statement_cache_size=0")
    assert (t.host, t.port, t.user, t.password, t.dbname) == ("db.example.supabase.co", 6543, "app", "s@cret", "postgres")
    assert t.params == {"sslmode": "require"}  # asyncpg-only parameter dropped
    assert bc.parse_db_url("postgres://u:p@localhost/x").port == 5432
    assert bc.parse_db_url("postgresql://u:p@127.0.0.1:5433/x?sslmode=disable").params == {"sslmode": "disable"}
    with pytest.raises(bc.ScriptError) as exc:
        bc.parse_db_url("mysql://u:p@localhost/x")
    assert exc.value.code == bc.EXIT_CONFIG


def test_password_is_never_shown():
    t = bc.parse_db_url("postgresql://app:TopSecret99@db.example.com:5432/coin")
    assert "TopSecret99" not in t.masked()
    assert t.masked() == "postgresql://app:***@db.example.com:5432/coin"
    assert "TopSecret99" not in repr(t)
    assert bc.mask_host("aws-0-ap-south-1.pooler.supabase.com") == "***.supabase.com"
    assert bc.mask_host("localhost") == "localhost"
    text = "could not connect to postgresql://app:TopSecret99@db.example.com/coin (pass phrase-xyz)"
    masked = bc.mask_secrets(text, "phrase-xyz")
    assert "TopSecret99" not in masked
    assert "phrase-xyz" not in masked


def test_child_processes_never_get_the_backup_secrets(monkeypatch):
    monkeypatch.setenv("BACKUP_PASSPHRASE", GOOD_PASS)
    monkeypatch.setenv("BACKUP_DATABASE_URL", "postgresql://u:p@h/d")
    monkeypatch.setenv("PGPASSFILE", "somewhere")
    env = bc.parse_db_url("postgresql://u:pw@localhost:5432/d").libpq_env()
    assert env["PGPASSWORD"] == "pw"
    assert env["PGHOST"] == "localhost"
    assert "BACKUP_PASSPHRASE" not in env
    assert "BACKUP_DATABASE_URL" not in env
    assert "PGPASSFILE" not in env
    assert bc.child_env(**{bc.OPENSSL_PASS_VAR: "x"})[bc.OPENSSL_PASS_VAR] == "x"


@pytest.mark.parametrize("host", ["db.supabase.co", "10.0.0.5", "example.com"])
def test_restore_target_must_be_local(host):
    with pytest.raises(bc.ScriptError) as exc:
        bc.require_local(bc.parse_db_url(f"postgresql://u:p@{host}:5432/postgres"))
    assert exc.value.code == bc.EXIT_CONFIG
    assert "only runs against" in str(exc.value)


@pytest.mark.parametrize("url", ["postgresql://u:p@localhost/postgres", "postgresql://u:p@127.0.0.1/postgres",
                                 "postgresql://u:p@[::1]:5432/postgres"])
def test_local_restore_targets_are_allowed(url):
    bc.require_local(bc.parse_db_url(url))


# ---------------------------------------------------------------------------
# Settings and folders
# ---------------------------------------------------------------------------


def test_backup_dir_inside_repository_is_refused(tmp_path):
    repo = tmp_path / "repo"
    (repo / "backend").mkdir(parents=True)
    for inside in (repo, repo / "backups", repo / "backend" / "x"):
        with pytest.raises(bc.ScriptError) as exc:
            bc.resolve_backup_dir(str(inside), repo_root=repo)
        assert exc.value.code == bc.EXIT_CONFIG
    outside = tmp_path / "elsewhere"
    assert bc.resolve_backup_dir(str(outside), repo_root=repo) == outside
    assert bc.resolve_backup_dir(str(tmp_path / "repo2"), repo_root=repo) == tmp_path / "repo2"  # prefix is not inside


def test_backup_dir_default_is_in_home(monkeypatch):
    assert bc.resolve_backup_dir("") == Path.home() / "coinscious-backups"
    with pytest.raises(bc.ScriptError):
        bc.resolve_backup_dir(str(bc.REPO_ROOT / "backups"))


def test_retention_days_setting():
    assert bc.retention_days("") == 14
    assert bc.retention_days("7") == 7
    for bad in ("0", "-3", "two"):
        with pytest.raises(bc.ScriptError):
            bc.retention_days(bad)


def test_missing_or_weak_settings_fail_clearly(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    assert backup_db.main([]) == bc.EXIT_CONFIG
    assert "BACKUP_PASSPHRASE is not set" in capsys.readouterr().err
    monkeypatch.setenv("BACKUP_PASSPHRASE", "short")
    assert backup_db.main([]) == bc.EXIT_CONFIG
    assert "at least 12 characters" in capsys.readouterr().err
    monkeypatch.setenv("BACKUP_PASSPHRASE", GOOD_PASS)
    assert backup_db.main([]) == bc.EXIT_CONFIG
    assert "BACKUP_DATABASE_URL is not set" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []  # nothing written

    assert restore_drill.main([]) == bc.EXIT_CONFIG
    assert "RESTORE_ADMIN_URL is not set" in capsys.readouterr().err
    monkeypatch.setenv("RESTORE_ADMIN_URL", "postgresql://u:SuperSecret1@db.supabase.co:5432/postgres")
    assert restore_drill.main([]) == bc.EXIT_CONFIG
    err = capsys.readouterr().err
    assert "Refusing to restore" in err
    assert "SuperSecret1" not in err


def test_backup_dir_in_repo_is_refused_by_the_script(monkeypatch, capsys):
    monkeypatch.setenv("BACKUP_DIR", str(bc.REPO_ROOT / "backend" / "backups"))
    assert backup_db.main(["--dry-run"]) == bc.EXIT_CONFIG
    assert "inside the repository" in capsys.readouterr().err


def test_openssl_override_must_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSSL_BIN", str(tmp_path / "no-openssl.exe"))
    with pytest.raises(bc.ScriptError) as exc:
        bc.find_tool("openssl")
    assert exc.value.code == bc.EXIT_CONFIG


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def names_at(*days_ago: float) -> list[str]:
    out = []
    for d in days_ago:
        stem = bc.backup_stem(NOW - timedelta(days=d))
        out += [stem + bc.DUMP_SUFFIX, stem + bc.MANIFEST_SUFFIX]
    return out


def test_retention_selects_only_own_files_older_than_the_limit():
    own = names_at(0.5, 13.9, 14.1, 30)
    others = ["notes.txt", "coinscious-20261001T000000Z.dump", "coinscious-20261001T000000Z.dump.enc.part",
              "other-20261001T000000Z.dump.enc", "coinscious-2026-10-01.dump.enc", "COINSCIOUS-20261001T000000Z.dump.enc"]
    expired = bc.select_expired(own + others, NOW, 14)
    assert expired == sorted(names_at(14.1, 30))
    assert not set(expired) & set(others)


def test_retention_always_keeps_the_newest_backup():
    old = names_at(40, 60)
    assert bc.select_expired(old, NOW, 14) == sorted(names_at(60))
    assert bc.select_expired([], NOW, 14) == []


def test_dry_run_deletes_nothing_and_real_run_deletes_only_expired(tmp_path):
    for name in names_at(1, 20) + ["keep-me.txt"]:
        (tmp_path / name).write_text("x", encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())
    would = backup_db.apply_retention(tmp_path, 14, dry_run=True, now=NOW)
    assert would == sorted(names_at(20))
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    deleted = backup_db.apply_retention(tmp_path, 14, dry_run=False, now=NOW)
    assert deleted == would
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(names_at(1) + ["keep-me.txt"])


def test_dry_run_command(monkeypatch, tmp_path, capsys):
    for name in names_at(1, 20):
        (tmp_path / name).write_text("x", encoding="utf-8")
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    assert backup_db.main(["--dry-run"]) == bc.EXIT_OK
    out = capsys.readouterr().out
    assert "Would delete 2 file(s)" in out
    assert len(list(tmp_path.iterdir())) == 4


def test_latest_backup(tmp_path):
    with pytest.raises(bc.ScriptError):
        bc.latest_backup(tmp_path)
    for name in names_at(3, 1, 2):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert bc.latest_backup(tmp_path).name == names_at(1)[0]
    assert bc.manifest_path_for(bc.latest_backup(tmp_path)).name == names_at(1)[1]


# ---------------------------------------------------------------------------
# Manifest and comparison
# ---------------------------------------------------------------------------


def test_manifest_round_trip_and_validation(tmp_path):
    path = tmp_path / "m.manifest.json"
    with pytest.raises(bc.ScriptError) as exc:
        bc.read_manifest(path)
    assert exc.value.code == bc.EXIT_VERIFY
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(bc.ScriptError):
        bc.read_manifest(path)
    path.write_text(json.dumps({"sha256": "x", "tables": {}}), encoding="utf-8")
    with pytest.raises(bc.ScriptError, match="encryption"):
        bc.read_manifest(path)
    data = {"sha256": "ab", "tables": {"users": 3}, "encryption": {"cipher": bc.CIPHER}}
    bc.write_manifest(path, data)
    assert bc.read_manifest(path) == data
    assert not (tmp_path / "m.manifest.json.part").exists()


def test_compare_counts_flags_mismatches_and_missing_tables():
    rows = bc.compare_counts({"users": 3, "expenses": 5, "gone": 1}, {"users": 3, "expenses": 4, "extra": 0})
    by = {r.table: r for r in rows}
    assert by["users"].ok
    assert not by["expenses"].ok
    assert (by["gone"].expected, by["gone"].restored, by["gone"].ok) == (1, None, False)
    assert (by["extra"].expected, by["extra"].ok) == (None, False)
    table = bc.format_count_table(rows)
    assert "table" in table.splitlines()[0]
    assert "missing" in table
    assert " NO" in table
    assert all(r.ok for r in bc.compare_counts({"a": 0}, {"a": 0}))


def test_sha256_file(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    assert bc.sha256_file(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_restore_list_drops_only_the_public_schema_entries():
    toc = [
        ";",
        "; Archive created at 2026-11-21",
        "5; 2615 2200 SCHEMA - public pg_database_owner",
        "5380; 0 0 COMMENT - SCHEMA public pg_database_owner",
        "230; 1259 16400 TABLE public users postgres",
        "4001; 0 16400 TABLE DATA public users postgres",
        "300; 1259 16500 INDEX public ix_expenses_description_trgm postgres",
    ]
    kept = bc.restore_list(toc)
    assert "SCHEMA - public" not in "\n".join(kept)
    assert "COMMENT - SCHEMA public" not in "\n".join(kept)
    assert len(kept) == 5
