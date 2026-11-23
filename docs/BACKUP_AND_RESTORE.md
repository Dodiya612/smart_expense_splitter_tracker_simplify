# Backups and restore drill (T-51 / US-34)

Supabase's free plan has no downloadable backups, so the team takes its own:
an **encrypted `pg_dump` every night from a team machine**, kept for **14 days**,
plus a **restore drill** that proves a backup can be restored and that every
table's row count matches.

There is no CI/CD in this project, so backups run from a team member's computer
(Windows Task Scheduler or macOS launchd/cron), never from GitHub Actions.

| Script | What it does |
|---|---|
| `backend/scripts/backup_db.py` | Encrypted backup + manifest, then deletes its own backups older than 14 days |
| `backend/scripts/restore_drill.py` | Restores a backup into a **new local scratch database** and compares row counts |
| `backend/scripts/backup_common.py` | Shared helpers (URL parsing and masking, retention, manifest, safety checks) |

---

## 1. What is backed up, and how

- **What:** the application schema `public`: every app table and `alembic_version`
  (format `pg_dump -Fc`, `--schema=public --no-owner --no-privileges`).
  Supabase's own schemas (`auth`, `storage`, …) are not part of the app and are not included.
- **Exact row counts:** the script opens a `REPEATABLE READ`, read-only transaction,
  exports its snapshot (`pg_export_snapshot()`), counts every table inside that
  snapshot, and runs `pg_dump --snapshot=<id>`, so the dump and the counts describe
  the same moment. If the server refuses the exported snapshot (some connection
  poolers do), the script dumps without it, counts again afterwards, and records
  this in the manifest (`"snapshot": {"used": false, ...}`).
- **Encryption:** `pg_dump` writes straight into `openssl enc` through a pipe, so an
  unencrypted dump never touches the disk. Cipher **AES-256-CBC**, random **salt**,
  key derived with **PBKDF2-SHA256, 600,000 iterations**. The passphrase is given
  to openssl through an environment variable, never on a command line.
- **Files:** each backup is two files in the backup folder:
  - `coinscious-<UTC time>.dump.enc`: the encrypted dump
  - `coinscious-<UTC time>.manifest.json`: time, masked source host, server and
    `pg_dump` versions, the SHA-256 of the encrypted file, whether the snapshot was
    used, the exact row count of every table, `alembic_version`, and the source's
    extensions (for example `pg_trgm` from migration 007, which a restore must create first).
- **Retention:** after a successful backup, the script deletes **only its own files**
  (names exactly `coinscious-YYYYMMDDTHHMMSSZ.dump.enc` / `.manifest.json`) older than
  `BACKUP_RETENTION_DAYS` (default **14**, minimum 1). The newest backup is always kept.
  Nothing else in the folder is ever touched.

The manifest contains no password, passphrase or full host name.

---

## 2. One-time setup

1. **Tools:** PostgreSQL client tools (`pg_dump`, `pg_restore`; version ≥ the server's)
   and `openssl`.
   - Windows: PostgreSQL 18 installer (client tools are in `C:\Program Files\PostgreSQL\18\bin`)
     and Git for Windows (`C:\Program Files\Git\ucrt64\bin\openssl.exe`). The scripts find
     both there automatically; otherwise set `PG_BIN_DIR` / `OPENSSL_BIN`.
   - macOS: `brew install libpq openssl@3` and add `$(brew --prefix libpq)/bin` to `PATH`
     (or set `PG_BIN_DIR`).
2. **Python:** the backend virtual environment (`backend/.venv`, created from
   `requirements.txt`). No extra packages are needed.
3. **Passphrase:** choose a long passphrase (at least 12 characters; 20+ recommended)
   and store it in the team's password manager. **Without it the backups cannot be
   read.** Never put it in the repository, a `.env` file inside the repository, or a chat.
4. **Source URL:** for Supabase use the **direct connection** or the **session pooler
   (port 5432)**, with `?sslmode=require`. The transaction pooler (port 6543) does not
   support `pg_dump`. Copy it from Supabase → Project Settings → Database.

### Environment variables

| Variable | Used by | Meaning |
|---|---|---|
| `BACKUP_DATABASE_URL` | backup | Source database. `postgres://`, `postgresql://` or `postgresql+asyncpg://` (converted automatically; `?ssl=require` becomes `sslmode=require`). |
| `BACKUP_PASSPHRASE` | both | Encryption passphrase (≥ 12 characters). |
| `BACKUP_DIR` | both | Backup folder. Default `~/coinscious-backups`. **Must be outside the repository** (the scripts refuse otherwise). |
| `BACKUP_RETENTION_DAYS` | backup | Days to keep (default 14, minimum 1). |
| `RESTORE_ADMIN_URL` | drill | Admin URL of a **local** PostgreSQL (`localhost`, `127.0.0.1` or `::1` only; anything else is refused). |
| `PG_BIN_DIR`, `OPENSSL_BIN` | both | Optional tool locations. |

The scripts never print secrets: URLs are always shown as `postgresql://user:***@host:port/db`.

---

## 3. Running a backup

**Windows (PowerShell):**

```powershell
cd <repo>\backend
$env:PYTHONPATH = ".."
$env:BACKUP_DATABASE_URL = Read-Host "Source database URL"      # paste; not saved anywhere
$env:BACKUP_PASSPHRASE   = Read-Host "Backup passphrase"
.\.venv\Scripts\python.exe scripts\backup_db.py
```

**macOS / Linux:**

```bash
cd <repo>/backend
export PYTHONPATH=..
read -rs -p "Source database URL: " BACKUP_DATABASE_URL; echo; export BACKUP_DATABASE_URL
read -rs -p "Backup passphrase: " BACKUP_PASSPHRASE; echo; export BACKUP_PASSPHRASE
.venv/bin/python scripts/backup_db.py
```

Expected output:

```
Backup of postgresql://postgres:***@***.supabase.com:5432/postgres
Server 17.4; snapshot used
Tables: 22, rows: 1234
Saved:    C:\Users\you\coinscious-backups\coinscious-20261121T013000Z.dump.enc (65808 bytes, sha256 0bb704c5e9f9...)
Manifest: C:\Users\you\coinscious-backups\coinscious-20261121T013000Z.manifest.json
Retention (14 days): deleted 0 file(s)
OK
```

`python scripts/backup_db.py --dry-run` only shows which old backups retention would
delete (no connection, nothing deleted).

**Exit codes:** `0` ok · `1` failed (database or tool error; nothing is kept) ·
`2` configuration or safety refusal · `3` backup kept but the row counts may be
inexact (no snapshot and rows changed during the dump: run again in a quiet period).

---

## 4. Scheduling (nightly, on one team machine)

The scheduled job needs the two secrets in its environment. Keep them **outside the
repository**, readable only by your user account.

### Windows: Task Scheduler

1. Store the secrets as **user** environment variables (kept in your Windows profile, not in the repo).
   Open a new PowerShell window afterwards so they are loaded:

   ```powershell
   [Environment]::SetEnvironmentVariable("BACKUP_DATABASE_URL", (Read-Host "Source database URL"), "User")
   [Environment]::SetEnvironmentVariable("BACKUP_PASSPHRASE", (Read-Host "Backup passphrase"), "User")
   ```

2. Create the daily task (02:30), replacing `E:\SE` with your repository path:

   ```powershell
   $cmd = "Set-Location 'E:\SE\backend'; `$env:PYTHONPATH='..'; " +
          "& '.\.venv\Scripts\python.exe' 'scripts\backup_db.py' *>> `"`$HOME\coinscious-backups\backup.log`""
   $action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -Command $cmd"
   $trigger = New-ScheduledTaskTrigger -Daily -At 2:30am
   $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
   Register-ScheduledTask -TaskName "Coinscious backup" -Action $action -Trigger $trigger -Settings $settings
   ```

   `-StartWhenAvailable` runs a missed backup when the computer is next on.
   Check: `Get-ScheduledTaskInfo "Coinscious backup"` (LastTaskResult `0` = success) and
   `Get-Content $HOME\coinscious-backups\backup.log -Tail 20`.
   Remove: `Unregister-ScheduledTask -TaskName "Coinscious backup"`.

### macOS: launchd (recommended) or cron

1. Put the secrets in a file only you can read, outside the repository:

   ```bash
   cat > ~/.coinscious-backup.env <<'EOF'
   export BACKUP_DATABASE_URL='postgresql://...'
   export BACKUP_PASSPHRASE='...'
   EOF
   chmod 600 ~/.coinscious-backup.env
   mkdir -p ~/coinscious-backups
   ```

2. **launchd:** save as `~/Library/LaunchAgents/com.coinscious.backup.plist`
   (replace `/path/to/repo`), then `launchctl load ~/Library/LaunchAgents/com.coinscious.backup.plist`:

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0"><dict>
     <key>Label</key><string>com.coinscious.backup</string>
     <key>ProgramArguments</key><array>
       <string>/bin/bash</string><string>-c</string>
       <string>. "$HOME/.coinscious-backup.env" &amp;&amp; cd /path/to/repo/backend &amp;&amp; PYTHONPATH=.. .venv/bin/python scripts/backup_db.py &gt;&gt; "$HOME/coinscious-backups/backup.log" 2&gt;&amp;1</string>
     </array>
     <key>StartCalendarInterval</key><dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>30</integer></dict>
   </dict></plist>
   ```

   launchd runs a missed job when the Mac wakes up.

3. **cron alternative** (`crontab -e`):

   ```
   30 2 * * * . "$HOME/.coinscious-backup.env" && cd /path/to/repo/backend && PYTHONPATH=.. .venv/bin/python scripts/backup_db.py >> "$HOME/coinscious-backups/backup.log" 2>&1
   ```

Keep a copy of recent backups somewhere other than the backup machine (for example a
private cloud drive). They are encrypted, but the passphrase must never be stored with them.

---

## 5. Restore drill (run monthly and before each review)

The drill restores into a **new scratch database on your own computer** and never
touches Supabase. It needs a local PostgreSQL server.

**Windows (PowerShell):**

```powershell
cd <repo>\backend
$env:PYTHONPATH = ".."
$env:RESTORE_ADMIN_URL = "postgresql://postgres:<local-password>@localhost:5432/postgres"
$env:BACKUP_PASSPHRASE = Read-Host "Backup passphrase"
.\.venv\Scripts\python.exe scripts\restore_drill.py            # newest backup in BACKUP_DIR
.\.venv\Scripts\python.exe scripts\restore_drill.py <path>\coinscious-....dump.enc
```

macOS: the same with `export ...` and `.venv/bin/python`.

What it does:

1. Checks the file's SHA-256 against the manifest (a changed or damaged file stops here).
2. Decrypts to a temporary file in the system temp folder (outside the repository) and
   checks it is a `pg_dump` archive (a wrong passphrase stops here).
3. Creates a new database `coinscious_restore_drill_<time>_<random>` on the local server.
4. Creates the extensions the source had (e.g. `pg_trgm`) in their original schemas.
5. `pg_restore --no-owner --no-privileges --exit-on-error`.
6. Counts every table and compares with the manifest, and compares `alembic_version`.
7. Drops the scratch database (keep it with `--keep`) and always deletes the decrypted file.

Expected output (local test run, 21 Nov 2026):

```
Backup:   coinscious-20261120T190306Z.dump.enc (made 2026-11-20T19:03:06Z, source localhost)
Checksum: OK
Decrypt:  OK
Scratch:  postgresql://postgres:***@localhost:5432/coinscious_restore_drill_20261120190307_5626f0
Restore:  completed

table                        | expected | restored | OK
-----------------------------+----------+----------+---
alembic_version              |        1 |        1 | OK
categories                   |       12 |       12 | OK
expense_payments             |        2 |        2 | OK
expense_shares               |        6 |        6 | OK
expenses                     |        3 |        3 | OK
...                          |          |          |
users                        |        3 |        3 | OK

alembic_version: expected ['015_recurring_expenses'], restored ['015_recurring_expenses'] -> OK
OK: restore completed and all 22 tables match (37 rows).
Dropped scratch database coinscious_restore_drill_20261120190307_5626f0.
```

**Exit codes:** `0` restore completed and every table matches · `1` failed
(wrong passphrase, restore error) · `2` configuration or safety refusal ·
`3` verification failed (checksum, a missing table, a row count or `alembic_version`).

Record every drill in the [drill log](#7-drill-log).

---

## 6. A real restore (production data lost or corrupted)

1. **Stop writes:** put the backend in maintenance (stop the Render service) so nothing
   changes while you restore.
2. **Pick the backup:** the newest one from before the problem. Run the restore drill on
   it first (section 5) and check the row counts look right.
3. **Take a fresh backup of the current (broken) database** with `backup_db.py`, so
   nothing is lost if you need to go back.
4. **Restore into a new, empty database**, not over the existing one. Either a new Supabase
   project, or a new database on the same server. Create the extensions first
   (e.g. `CREATE EXTENSION IF NOT EXISTS pg_trgm;` in the schema the manifest lists),
   then, with the decrypted file:

   ```
   openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 -pass env:BACKUP_PASSPHRASE -in coinscious-<time>.dump.enc -out restore.dump
   pg_restore --list restore.dump | grep -v -E "SCHEMA - public|COMMENT - SCHEMA public" > restore.list
   pg_restore --no-owner --no-privileges --exit-on-error --use-list=restore.list --dbname="<new database URL>" restore.dump
   ```

   Do this in a folder **outside the repository** and delete `restore.dump` and
   `restore.list` afterwards.
5. **Verify** the row counts against the manifest (`SELECT count(*) FROM <table>`) and run
   `alembic current` against the new database (it must show the manifest's `alembic_version`).
6. **Switch** the backend's `DATABASE_URL` (Render environment) to the new database, start
   the service, and check sign-in, an expense list and a group balance.
7. Write down what happened and when in the drill log.

---

## 7. Drill log

| Date | Who | Backup file | Source | Result (tables matched / total) | Time taken | Notes |
|---|---|---|---|---|---|---|
| 2026-11-21 | Claude Code (local test) | `coinscious-20261120T190306Z.dump.enc` | local throwaway database | 22 / 22, 37 rows, `alembic_version` OK | ~1 min | `tests/test_backup_restore_pg.py` |
|  |  |  |  |  |  |  |

---

## 8. Troubleshooting

| Message | Fix |
|---|---|
| `BACKUP_PASSPHRASE is not set` / `BACKUP_DATABASE_URL is not set` | Set the variable in this shell (or the scheduled task's user environment). |
| `pg_dump was not found` / `openssl was not found` | Install the tools or set `PG_BIN_DIR` / `OPENSSL_BIN`. |
| `Refusing to keep backups inside the repository` | Set `BACKUP_DIR` to a folder outside the repository. |
| `Refusing to restore to '...'` | `RESTORE_ADMIN_URL` must point to `localhost`, `127.0.0.1` or `::1`. |
| `snapshot NOT used: the server refused the exported snapshot` | Use the direct connection or session pooler (port 5432) instead of the transaction pooler. |
| `pg_dump failed: server version mismatch` | Install a `pg_dump` at least as new as the server. |
| `Could not decrypt the backup: wrong BACKUP_PASSPHRASE or a damaged file` | Use the passphrase from the password manager that was current when the backup was made. |
| `Checksum mismatch` | The file changed after the backup; use another backup. |
