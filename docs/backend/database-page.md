# Control panel → Database (SA-15)

A page in the control panel (`https://control.mesiri.ai/database`) to browse every table
in the live database and run SQL. Platform admins only. Approved by Alan (relayed 24 Oct).

## What it does

| | How | Safeguard |
|---|---|---|
| Browse | Table list (estimated rows, size), a table's columns (type, PK), 50 rows a page, newest first, sort by any column, filter "column equals value" | Column names are checked against the catalogue; read only |
| Read SQL | **Run read** (Ctrl+Enter) | Transaction set `READ ONLY` by Postgres itself: no write can happen, even inside a `WITH … DELETE`. 15 s timeout, 500 rows shown |
| Change rows | **Dry run**, then **Run write** | The dry run runs the statement and rolls it back, showing the row count (and `RETURNING` rows). The write is kept only if it changes that same number of rows (else rolled back, 409). The page enables Run write only for the exact dry-run text, then asks for confirmation. 30 s timeout, 5 s lock timeout |

Refused in every mode: schema changes (`CREATE`/`ALTER`/`DROP`/`TRUNCATE`/`GRANT`…),
transaction control, `DO`, `COPY`, `SET`, `VACUUM`. Schema changes go through migrations
(they run on every deploy; a hand-made change would fork the schema from the code). One
statement per run (asyncpg prepares the text, and a prepared statement is one command).

Audit: every SQL read (`database.query_read`) and every kept write
(`database.rows_changed`, with the row count) is in the admin audit log with the
statement (first 4000 characters) and who ran it. Dry runs and browsing are not recorded.

**No automatic backup before a write.** Backups are nightly (02:15 IST, 14 kept) and
before every migration; before a large change, run `vps-backup-now` in the `claude-ops`
workflow first.

## Code

- `backend/src/mesiri/infrastructure/postgres/repositories/database_console.py` — the rules
  (statement check, read-only / dry-run / write runs in a savepoint, browsing queries).
- `backend/src/mesiri/domains/admin/database_router.py` — `GET /admin/database/tables`,
  `GET /admin/database/tables/{table}`, `POST /admin/database/query`
  (`{sql, mode: read|dry_run|write, expected_rows}`); mounted by both apps.
- `apps/control-panel/src/Database.tsx` — the page.
- Tests: `backend/tests/unit/test_database_console.py`,
  `backend/tests/integration/test_database_console_postgres.py` (real Postgres).

## Rollback

Revert the commit. No migration, no data change.
