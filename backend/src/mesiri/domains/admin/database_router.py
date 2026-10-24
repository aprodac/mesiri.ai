"""The control panel's Database page (SA-15): browse every table, run SQL.

Platform admins only (require_platform_admin). Reads are free; a write is a
dry run (changes nothing, shows how many rows it would change) followed by
the real run, which is kept only if it changes that same number of rows.
Every SQL read and every write is recorded in the admin audit log with the
statement. The rules for what runs, and how, are in
infrastructure/postgres/repositories/database_console.py.

One router, mounted by both apps (backend http/app.py and the assistant's
runtime/lifecycle.py), like the costs router.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.audit.record import record_admin_action
from mesiri.domains.audit.actions import (
    DATABASE_QUERY_READ,
    DATABASE_ROWS_CHANGED,
    actor_from_admin,
)
from mesiri.domains.shared.auth import require_platform_admin
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories import database_console as console

router = APIRouter(prefix="/admin/database", tags=["admin"])

#: What the audit entry keeps of a statement.
_AUDIT_SQL_CHARS = 4000


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)
    mode: str = console.READ
    #: For mode "write": the row count the dry run showed.
    expected_rows: int | None = None


def _result(out: console.QueryResult) -> dict[str, Any]:
    return {
        "columns": out.columns,
        "rows": out.rows,
        "row_count": out.row_count,
        "truncated": out.truncated,
        "duration_ms": out.duration_ms,
        "max_rows": console.MAX_ROWS,
    }


def _db_message(exc: DBAPIError) -> str:
    """Postgres' own message, without the driver's class-name prefix."""
    text = str(exc.orig) if exc.orig is not None else str(exc)
    return re.sub(r"^<class '[^']+'>:\s*", "", text).strip()


@router.get("/tables")
async def get_tables(
    _admin: dict = Depends(require_platform_admin),
    conn: AsyncConnection = Depends(get_db_conn),
) -> dict[str, Any]:
    return {"tables": await console.list_tables(conn)}


@router.get("/tables/{table}")
async def get_table(
    table: str,
    limit: int = Query(50, ge=1, le=console.MAX_ROWS),
    offset: int = Query(0, ge=0),
    order_by: str | None = None,
    desc: bool = True,
    filter_column: str | None = None,
    filter_value: str | None = None,
    _admin: dict = Depends(require_platform_admin),
    conn: AsyncConnection = Depends(get_db_conn),
) -> dict[str, Any]:
    columns = await console.table_columns(conn, table)
    if not columns:
        raise HTTPException(status_code=404, detail=f"No table {table!r}")
    try:
        page = await console.table_rows(
            conn,
            table,
            columns=columns,
            limit=limit,
            offset=offset,
            order_by=order_by,
            descending=desc,
            filter_column=filter_column,
            filter_value=filter_value,
        )
    except console.QueryRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"table": table, "column_info": columns, "offset": offset, **_result(page)}


@router.post("/query")
async def run_query(
    body: QueryRequest,
    admin: dict = Depends(require_platform_admin),
    conn: AsyncConnection = Depends(get_db_conn),
) -> dict[str, Any]:
    try:
        console.check_statement(body.sql, body.mode)
    except console.QueryRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    actor = actor_from_admin(admin)
    sql_for_audit = body.sql.strip()[:_AUDIT_SQL_CHARS]
    if body.mode == console.READ:
        # Written before the transaction turns read-only.
        await record_admin_action(
            conn,
            actor=actor,
            action=DATABASE_QUERY_READ,
            target_type="database",
            summary="SQL read",
            details={"sql": sql_for_audit},
        )
    try:
        out = await console.run_statement(
            conn, body.sql, mode=body.mode, expected_rows=body.expected_rows
        )
    except console.QueryRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except console.RowCountMismatch as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Nothing changed: {exc}. The data moved since the dry run; dry-run again.",
        ) from exc
    except DBAPIError as exc:
        raise HTTPException(status_code=400, detail=_db_message(exc)) from exc

    if body.mode == console.WRITE:
        await record_admin_action(
            conn,
            actor=actor,
            action=DATABASE_ROWS_CHANGED,
            target_type="database",
            summary=f"SQL write: {out.row_count} row(s) changed",
            details={"sql": sql_for_audit, "rows": out.row_count},
        )
    return {"mode": body.mode, **_result(out)}
