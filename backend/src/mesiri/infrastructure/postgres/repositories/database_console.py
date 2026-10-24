"""The control panel's Database page (SA-15): browse tables, run SQL.

Takes an externally-supplied connection (the request's transaction from
`get_db_conn`) and never commits; every statement typed on the page runs in
a SAVEPOINT on it, so a failing statement is undone and reported without
spoiling the request's transaction (the audit entry written beside it).

Three ways to run SQL, chosen by the caller:

- `read`: the transaction is switched to READ ONLY first, so Postgres
  itself refuses any write, whatever the statement says;
- `dry_run`: the statement runs and is rolled back; the caller learns how
  many rows it would change (and sees RETURNING rows);
- `write`: the statement runs and is kept, but only if it changes exactly
  the number of rows the caller expects (the dry run's count) -- otherwise
  it is rolled back and `RowCountMismatch` raised.

Statements are checked by their first keyword: reads are SELECT / WITH /
EXPLAIN / SHOW / TABLE / VALUES; writes add INSERT / UPDATE / DELETE /
MERGE. Schema changes, transaction control, DO blocks, COPY, SET and the
rest are refused: schema changes go through migrations (they run on every
deploy) and transaction control would escape the savepoint. One statement
per run (asyncpg prepares the text, and a prepared statement is one
command). Each run has a statement timeout and a lock timeout.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

READ, DRY_RUN, WRITE = "read", "dry_run", "write"
MODES = (READ, DRY_RUN, WRITE)

#: Rows sent back from one statement or one page of a table.
MAX_ROWS = 500
#: A single cell's text is cut to this many characters.
MAX_CELL_CHARS = 10_000
STATEMENT_TIMEOUT_MS = {READ: 15_000, DRY_RUN: 30_000, WRITE: 30_000}
LOCK_TIMEOUT_MS = 5_000

_READ_KEYWORDS = frozenset({"select", "with", "explain", "show", "table", "values"})
_WRITE_KEYWORDS = _READ_KEYWORDS | {"insert", "update", "delete", "merge"}

_COMMENTS = re.compile(r"(--[^\n]*(\n|$))|(/\*.*?\*/)", re.DOTALL)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class QueryRefused(ValueError):
    """The statement is not one this page runs (wrong kind, or empty)."""


class RowCountMismatch(Exception):
    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"expected {expected} row(s) to change, the statement changed {actual}")
        self.expected = expected
        self.actual = actual


@dataclass(slots=True)
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    #: Rows changed (INSERT/UPDATE/DELETE) or returned; None when unknown.
    row_count: int | None = None
    truncated: bool = False
    duration_ms: float = 0.0


def first_keyword(sql: str) -> str:
    """The statement's first word, lower-case, comments and leading
    parentheses ignored ("" for an empty statement)."""
    stripped = _COMMENTS.sub(" ", sql).strip().lstrip("(").strip()
    match = re.match(r"[A-Za-z]+", stripped)
    return match.group(0).lower() if match else ""


def check_statement(sql: str, mode: str) -> str:
    """The statement, trimmed (a trailing `;` dropped), if `mode` may run it;
    raises QueryRefused otherwise."""
    if mode not in MODES:
        raise QueryRefused(f"unknown mode {mode!r}")
    statement = sql.strip().rstrip(";").strip()
    keyword = first_keyword(statement)
    if not keyword:
        raise QueryRefused("Type a SQL statement first.")
    allowed = _READ_KEYWORDS if mode == READ else _WRITE_KEYWORDS
    if keyword not in allowed:
        if mode == READ and keyword in _WRITE_KEYWORDS:
            raise QueryRefused(
                f"{keyword.upper()} changes data: use Dry run, then Run write."
            )
        raise QueryRefused(
            f"{keyword.upper()} statements are not run here. Schema changes go through"
            " migrations; transaction control, DO, COPY and SET are not allowed."
        )
    return statement


def json_safe(value: Any) -> Any:
    """A cell value the API can send as JSON."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value if len(value) <= MAX_CELL_CHARS else value[:MAX_CELL_CHARS] + "…"
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        raw = bytes(value)
        return f"\\x{raw[:64].hex()}{'…' if len(raw) > 64 else ''} ({len(raw)} bytes)"
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [json_safe(v) for v in value]
    return json_safe(str(value))


async def run_statement(
    conn: AsyncConnection,
    sql: str,
    *,
    mode: str,
    expected_rows: int | None = None,
) -> QueryResult:
    """Run one statement typed on the page (see the module docstring).
    Raises QueryRefused, RowCountMismatch, or the database's own error
    (sqlalchemy.exc.DBAPIError) -- after undoing the statement."""
    statement = check_statement(sql, mode)
    if mode == WRITE and expected_rows is None:
        raise QueryRefused("Run a dry run first: a write needs the row count it showed.")
    if mode == READ:
        # Allowed at any point of a transaction (only READ WRITE is not).
        await conn.exec_driver_sql("SET TRANSACTION READ ONLY")
    await conn.exec_driver_sql(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS[mode]}")
    await conn.exec_driver_sql(f"SET LOCAL lock_timeout = {LOCK_TIMEOUT_MS}")

    started = dt.datetime.now(dt.UTC)
    savepoint = await conn.begin_nested()
    try:
        result = await conn.exec_driver_sql(statement)
        out = QueryResult()
        if result.returns_rows:
            out.columns = list(result.keys())
            fetched = result.fetchmany(MAX_ROWS + 1)
            out.truncated = len(fetched) > MAX_ROWS
            out.rows = [[json_safe(v) for v in row] for row in fetched[:MAX_ROWS]]
        if result.rowcount is not None and result.rowcount >= 0:
            out.row_count = result.rowcount
        elif result.returns_rows and not out.truncated:
            out.row_count = len(out.rows)
        if mode == WRITE and out.row_count != expected_rows:
            raise RowCountMismatch(expected_rows or 0, out.row_count or 0)
    except BaseException:
        await savepoint.rollback()
        raise
    if mode == DRY_RUN:
        await savepoint.rollback()
    else:
        await savepoint.commit()
    out.duration_ms = round((dt.datetime.now(dt.UTC) - started).total_seconds() * 1000, 1)
    return out


# ── Browsing ────────────────────────────────────────────────────────────────


async def list_tables(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Every table in `public`: name, estimated rows (Postgres' statistics,
    None if never analysed), total size on disk including indexes."""
    result = await conn.execute(
        sa.text(
            "SELECT c.relname AS name,"
            " CASE WHEN c.reltuples < 0 THEN NULL ELSE c.reltuples::bigint END AS estimated_rows,"
            " pg_total_relation_size(c.oid) AS size_bytes"
            " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
            " ORDER BY c.relname"
        )
    )
    return [dict(row) for row in result.mappings()]


async def table_columns(conn: AsyncConnection, table: str) -> list[dict[str, Any]]:
    """The table's columns in order (name, type, nullable, default, primary
    key); empty if there is no such table in `public`."""
    result = await conn.execute(
        sa.text(
            "SELECT c.column_name AS name, c.data_type AS type,"
            " c.is_nullable = 'YES' AS nullable, c.column_default AS default,"
            " EXISTS ("
            "   SELECT 1 FROM pg_index i"
            "   JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)"
            "   WHERE i.indrelid = to_regclass('public.' || quote_ident(:table))"
            "     AND i.indisprimary AND a.attname = c.column_name"
            " ) AS primary_key"
            " FROM information_schema.columns c"
            " WHERE c.table_schema = 'public' AND c.table_name = :table"
            " ORDER BY c.ordinal_position"
        ),
        {"table": table},
    )
    return [dict(row) for row in result.mappings()]


def _quote(identifier: str) -> str:
    # Only ever called with names read back from the catalogue; checked anyway.
    if not _IDENT.match(identifier):
        raise QueryRefused(f"unexpected identifier {identifier!r}")
    return f'"{identifier}"'


async def table_rows(
    conn: AsyncConnection,
    table: str,
    *,
    columns: list[dict[str, Any]],
    limit: int = 50,
    offset: int = 0,
    order_by: str | None = None,
    descending: bool = True,
    filter_column: str | None = None,
    filter_value: str | None = None,
) -> QueryResult:
    """One page of a table, newest first by default (`created_at` if the
    table has it, else its primary key). `filter_column`/`filter_value`
    keeps the rows whose column, as text, equals the value. Column names
    are checked against `columns` (the catalogue), never taken as typed."""
    names = [c["name"] for c in columns]
    if order_by is not None and order_by not in names:
        raise QueryRefused(f"no column {order_by!r} in {table}")
    if filter_column is not None and filter_column not in names:
        raise QueryRefused(f"no column {filter_column!r} in {table}")
    if order_by is None:
        primary = [c["name"] for c in columns if c["primary_key"]]
        order_by = "created_at" if "created_at" in names else (primary[0] if primary else None)

    sql = f"SELECT * FROM public.{_quote(table)}"
    params: dict[str, Any] = {"limit": min(max(limit, 1), MAX_ROWS) + 1, "offset": max(offset, 0)}
    if filter_column is not None:
        sql += f" WHERE {_quote(filter_column)}::text = :value"
        params["value"] = filter_value or ""
    if order_by is not None:
        sql += f" ORDER BY {_quote(order_by)} {'DESC' if descending else 'ASC'} NULLS LAST"
    sql += " LIMIT :limit OFFSET :offset"

    await conn.exec_driver_sql(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS[READ]}")
    started = dt.datetime.now(dt.UTC)
    result = await conn.execute(sa.text(sql), params)
    fetched = result.fetchall()
    page = fetched[: params["limit"] - 1]
    return QueryResult(
        columns=list(result.keys()),
        rows=[[json_safe(v) for v in row] for row in page],
        row_count=len(page),
        truncated=len(fetched) > len(page),
        duration_ms=round((dt.datetime.now(dt.UTC) - started).total_seconds() * 1000, 1),
    )
