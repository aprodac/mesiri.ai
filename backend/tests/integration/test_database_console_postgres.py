"""SA-15: the control panel's Database page against a real Postgres
(integration): reads cannot write, a dry run changes nothing, a write is
kept only with the dry run's row count, a failing statement leaves the
request usable, and SQL reads and writes reach the audit log. Each test
runs in a transaction that is rolled back.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from mesiri.domains.admin import database_router
from mesiri.infrastructure.postgres.repositories import database_console as console

pytestmark = pytest.mark.integration

ADMIN = {"sub": str(uuid.uuid4()), "role": "ADMIN", "org": "", "name": "Test Admin"}


@pytest.fixture
async def conn():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.connect() as connection:
        tx = await connection.begin()
        await connection.exec_driver_sql(
            "CREATE TEMP TABLE IF NOT EXISTS sa15_probe (id int PRIMARY KEY, note text) ON COMMIT DROP"
        )
        await connection.exec_driver_sql("INSERT INTO sa15_probe VALUES (1, 'a'), (2, 'b'), (3, 'c')")
        yield connection
        await tx.rollback()
    await engine.dispose()


async def _count(conn) -> int:
    return (await conn.execute(text("SELECT count(*) FROM sa15_probe"))).scalar_one()


async def _audit(conn, action: str) -> list:
    rows = await conn.execute(
        text("SELECT summary, details FROM admin_audit_log WHERE action = :a AND actor_label = 'Test Admin'"),
        {"a": action},
    )
    return list(rows)


async def test_read_returns_rows_and_columns(conn) -> None:
    out = await console.run_statement(conn, "SELECT id, note FROM sa15_probe ORDER BY id", mode=console.READ)
    assert out.columns == ["id", "note"]
    assert out.rows == [[1, "a"], [2, "b"], [3, "c"]]
    assert out.row_count == 3 and not out.truncated


async def test_read_mode_cannot_write_even_inside_a_select(conn) -> None:
    # A real table: Postgres lets a read-only transaction write temp tables.
    org = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at)"
            " VALUES (:id, 'SA-15 Read Only', 'local', 'default', 'active', now())"
        ),
        {"id": org},
    )
    with pytest.raises(DBAPIError, match="read-only"):
        await console.run_statement(
            conn,
            f"WITH d AS (DELETE FROM organizations WHERE id = '{org}' RETURNING 1) SELECT count(*) FROM d",
            mode=console.READ,
        )
    left = await conn.execute(text("SELECT count(*) FROM organizations WHERE id = :id"), {"id": org})
    assert left.scalar_one() == 1


async def test_dry_run_reports_the_count_and_changes_nothing(conn) -> None:
    out = await console.run_statement(
        conn, "DELETE FROM sa15_probe WHERE id >= 2 RETURNING id", mode=console.DRY_RUN
    )
    assert out.row_count == 2
    assert sorted(r[0] for r in out.rows) == [2, 3]
    assert await _count(conn) == 3


async def test_write_is_kept_only_with_the_dry_runs_count(conn) -> None:
    with pytest.raises(console.RowCountMismatch):
        await console.run_statement(conn, "DELETE FROM sa15_probe WHERE id >= 2", mode=console.WRITE, expected_rows=1)
    assert await _count(conn) == 3

    with pytest.raises(console.QueryRefused, match="dry run"):
        await console.run_statement(conn, "DELETE FROM sa15_probe WHERE id >= 2", mode=console.WRITE)

    out = await console.run_statement(conn, "DELETE FROM sa15_probe WHERE id >= 2", mode=console.WRITE, expected_rows=2)
    assert out.row_count == 2
    assert await _count(conn) == 1


async def test_a_failing_statement_leaves_the_transaction_usable(conn) -> None:
    with pytest.raises(DBAPIError):
        await console.run_statement(conn, "SELECT * FROM no_such_table", mode=console.DRY_RUN)
    assert await _count(conn) == 3


async def test_two_statements_in_one_run_are_refused_by_postgres(conn) -> None:
    with pytest.raises(DBAPIError):
        await console.run_statement(conn, "SELECT 1; DELETE FROM sa15_probe", mode=console.DRY_RUN)
    assert await _count(conn) == 3


async def test_colons_and_percent_signs_are_plain_sql(conn) -> None:
    out = await console.run_statement(conn, "SELECT '10:30'::time AS t, '50%' AS p", mode=console.READ)
    assert out.rows == [["10:30:00", "50%"]]


async def test_browse_tables_columns_and_a_filtered_page(conn) -> None:
    tables = {t["name"]: t for t in await console.list_tables(conn)}
    assert "organizations" in tables and "admin_audit_log" in tables

    columns = await console.table_columns(conn, "organizations")
    assert [c["name"] for c in columns if c["primary_key"]] == ["id"]
    assert await console.table_columns(conn, "no_such_table") == []

    org = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at)"
            " VALUES (:id, 'SA-15 Builders', 'local', 'default', 'active', now())"
        ),
        {"id": org},
    )
    page = await console.table_rows(
        conn, "organizations", columns=columns, filter_column="id", filter_value=str(org)
    )
    assert page.row_count == 1
    assert page.rows[0][page.columns.index("name")] == "SA-15 Builders"

    with pytest.raises(console.QueryRefused):
        await console.table_rows(conn, "organizations", columns=columns, order_by='name"; drop table x; --')


async def test_router_audits_reads_and_writes_but_not_dry_runs(conn) -> None:
    read = await database_router.run_query(
        database_router.QueryRequest(sql="SELECT 1 AS one"), admin=ADMIN, conn=conn
    )
    assert read["rows"] == [[1]]
    assert len(await _audit(conn, "database.query_read")) == 1


async def test_router_write_flow(conn) -> None:
    sql = "UPDATE sa15_probe SET note = 'z' WHERE id = 1"
    dry = await database_router.run_query(
        database_router.QueryRequest(sql=sql, mode="dry_run"), admin=ADMIN, conn=conn
    )
    assert dry["row_count"] == 1
    assert await _audit(conn, "database.rows_changed") == []

    with pytest.raises(HTTPException) as refused:
        await database_router.run_query(
            database_router.QueryRequest(sql=sql, mode="write", expected_rows=5), admin=ADMIN, conn=conn
        )
    assert refused.value.status_code == 409

    done = await database_router.run_query(
        database_router.QueryRequest(sql=sql, mode="write", expected_rows=1), admin=ADMIN, conn=conn
    )
    assert done["row_count"] == 1
    [(summary, details)] = await _audit(conn, "database.rows_changed")
    assert summary == "SQL write: 1 row(s) changed"
    assert details["sql"] == sql and details["rows"] == 1

    with pytest.raises(HTTPException) as bad:
        await database_router.run_query(
            database_router.QueryRequest(sql="DROP TABLE sa15_probe", mode="write", expected_rows=0),
            admin=ADMIN,
            conn=conn,
        )
    assert bad.value.status_code == 400
