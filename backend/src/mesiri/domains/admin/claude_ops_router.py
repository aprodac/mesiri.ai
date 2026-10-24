"""Claude's read-only window on the control plane (SA-16).

So Claude Code can answer "why didn't Acme's DPR go out?" or "which trials
haven't sent an update?" itself, from the live data, without anyone opening
the control panel. Used by `scripts/control_plane.py` and the
`control-plane` skill.

- Auth: `Authorization: Bearer <MESIRI_CLAUDE_OPS_TOKEN>`, a dedicated token
  (not a superadmin login), revoked by changing or removing it. With no
  token configured (or one under 32 characters) every path here answers 404.
- Read-only, enforced by Postgres: every request's transaction is READ ONLY.
  SQL runs through the Database page's console in `read` mode
  (infrastructure/postgres/repositories/database_console.py), so the same
  rules apply: one statement, SELECT/WITH/EXPLAIN/SHOW/TABLE/VALUES only,
  15 s timeout, 500 rows.
- Every SQL read is in the admin audit log (`database.query_read`, actor
  "Claude (ops token)").
- Secrets stay out: SQL naming the secret tables or columns
  (`ai_provider_secrets`, `login_codes`, `users.hashed_password`, …) is
  refused, and results hide those columns and password-hash values, also
  inside JSON. This guards against accidental exposure, not a token holder
  set on getting round it; the token is as sensitive as a read-only
  database login.

One router, mounted by both apps (backend http/app.py and the assistant's
runtime/lifecycle.py), like the costs and database routers.
"""

from __future__ import annotations

import dataclasses
import hmac
import re
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.audit.record import record_admin_action
from mesiri.application.organizations.companies_overview import list_companies
from mesiri.domains.audit.actions import ACTOR_SYSTEM, DATABASE_QUERY_READ, AuditActor
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories import database_console as console

router = APIRouter(prefix="/claude-ops", tags=["claude-ops"])

MIN_TOKEN_CHARS = 32
#: Secret tables and columns (find them again: columns named like
#: password/secret/token/api_key/hash in information_schema).
SECRET_TABLES = frozenset({"ai_provider_secrets", "login_codes"})
SECRET_COLUMNS = frozenset({"hashed_password", "api_key", "code_hash", "password", "secret"})
HIDDEN = "[hidden]"
#: Password hashes anywhere in a text (a whole row cast to text, JSON, …):
#: bcrypt, argon2, pbkdf2 formats.
_HASH = re.compile(
    r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}"
    r"|\$argon2(?:id|i|d)\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]+\$[A-Za-z0-9+/]+"
    r"|\$pbkdf2[-a-z0-9]*\$\d+\$[./A-Za-z0-9+]+\$[./A-Za-z0-9+]+"
)
ACTOR = AuditActor(kind=ACTOR_SYSTEM, label="Claude (ops token)")
_AUDIT_SQL_CHARS = 4000


def _configured_token() -> str | None:
    from mesiri.bootstrap.settings import get_settings

    secret = get_settings().claude_ops_token
    token = secret.get_secret_value().strip() if secret is not None else ""
    return token if len(token) >= MIN_TOKEN_CHARS else None


async def require_claude_ops(authorization: str | None = Header(None)) -> None:
    expected = _configured_token()
    if expected is None:
        raise HTTPException(status_code=404, detail="Not Found")
    given = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid ops token")


async def read_only_conn(
    _auth: None = Depends(require_claude_ops),
    conn: AsyncConnection = Depends(get_db_conn),
) -> AsyncConnection:
    await conn.exec_driver_sql("SET TRANSACTION READ ONLY")
    return conn


class SqlRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)


def check_no_secrets(sql: str) -> None:
    # "password"/"secret" alone are too common in innocent SQL to refuse;
    # those columns are still hidden in the results.
    lowered = sql.lower()
    names = SECRET_TABLES | (SECRET_COLUMNS - {"password", "secret"})
    named = sorted(n for n in names if n in lowered)
    if named:
        raise HTTPException(
            status_code=400,
            detail=f"Secrets are not readable through this API ({', '.join(named)}).",
        )


def hide_secrets(value: Any, key: str | None = None) -> Any:
    """`value` with secret columns/keys and password hashes replaced by
    HIDDEN, recursively."""
    if key is not None and key.lower() in SECRET_COLUMNS and value is not None:
        return HIDDEN
    if isinstance(value, str):
        return _HASH.sub(HIDDEN, value)
    if isinstance(value, dict):
        return {k: hide_secrets(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [hide_secrets(v) for v in value]
    return value


def _db_message(exc: DBAPIError) -> str:
    text = str(exc.orig) if exc.orig is not None else str(exc)
    return re.sub(r"^<class '[^']+'>:\s*", "", text).strip()


def _result(out: console.QueryResult) -> dict[str, Any]:
    rows = [[hide_secrets(v, c) for c, v in zip(out.columns, row, strict=False)] for row in out.rows]
    return {
        "columns": out.columns,
        "rows": rows,
        "row_count": out.row_count,
        "truncated": out.truncated,
        "duration_ms": out.duration_ms,
        "max_rows": console.MAX_ROWS,
    }


@router.get("/whoami")
async def whoami(conn: AsyncConnection = Depends(read_only_conn)) -> dict[str, Any]:
    database = (await conn.exec_driver_sql("SELECT current_database()")).scalar_one()
    return {"ok": True, "read_only": True, "database": database}


@router.get("/companies")
async def companies(conn: AsyncConnection = Depends(read_only_conn)) -> dict[str, Any]:
    """Every company, newest first: status, trial days left, setup progress
    (the control panel's Companies list)."""
    rows = await list_companies(conn)
    return {"companies": [console.json_safe(dataclasses.asdict(c)) for c in rows]}


@router.get("/tables")
async def tables(conn: AsyncConnection = Depends(read_only_conn)) -> dict[str, Any]:
    return {"tables": await console.list_tables(conn)}


@router.get("/tables/{table}")
async def table(
    table: str,
    limit: int = Query(20, ge=1, le=console.MAX_ROWS),
    conn: AsyncConnection = Depends(read_only_conn),
) -> dict[str, Any]:
    """A table's columns and its newest rows."""
    if table.lower() in SECRET_TABLES:
        raise HTTPException(status_code=400, detail="Secrets are not readable through this API.")
    columns = await console.table_columns(conn, table)
    if not columns:
        raise HTTPException(status_code=404, detail=f"No table {table!r}")
    page = await console.table_rows(conn, table, columns=columns, limit=limit)
    return {"table": table, "column_info": console.json_safe(columns), **_result(page)}


@router.post("/sql")
async def sql(
    body: SqlRequest,
    _auth: None = Depends(require_claude_ops),
    conn: AsyncConnection = Depends(get_db_conn),
) -> dict[str, Any]:
    try:
        console.check_statement(body.sql, console.READ)
    except console.QueryRefused as exc:
        detail = str(exc)
        if console.first_keyword(body.sql) in {"insert", "update", "delete", "merge"}:
            detail = "This API is read-only; changes are made in the control panel (Database page)."
        raise HTTPException(status_code=400, detail=detail) from exc
    check_no_secrets(body.sql)
    # Recorded before the transaction turns read-only (run_statement does that).
    await record_admin_action(
        conn,
        actor=ACTOR,
        action=DATABASE_QUERY_READ,
        target_type="database",
        summary="SQL read (Claude ops token)",
        details={"sql": body.sql.strip()[:_AUDIT_SQL_CHARS]},
    )
    try:
        out = await console.run_statement(conn, body.sql, mode=console.READ)
    except console.QueryRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DBAPIError as exc:
        raise HTTPException(status_code=400, detail=_db_message(exc)) from exc
    return _result(out)
