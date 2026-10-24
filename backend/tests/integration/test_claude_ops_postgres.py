"""SA-16: Claude's read-only control-plane API against a real Postgres
(integration): read-only even through SQL, secrets hidden in results,
reads audited as "Claude (ops token)". Rolled back after each test."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from mesiri.domains.admin import claude_ops_router as ops

pytestmark = pytest.mark.integration

BCRYPT = "$2b$12$abcdefghijklmnopqrstuvabcdefghijklmnopqrstuvwxyz12345"


@pytest.fixture
async def conn():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.connect() as connection:
        tx = await connection.begin()
        org = uuid.uuid4()
        await connection.execute(
            text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at)"
                " VALUES (:id, 'SA-16 Builders', 'local', 'default', 'active', now())"
            ),
            {"id": org},
        )
        await connection.execute(
            text(
                "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, created_at)"
                " VALUES (gen_random_uuid(), :org, 'sa16@example.in', :pw, 'SA-16 Owner', 'ADMIN', 'active', now())"
            ),
            {"org": org, "pw": BCRYPT},
        )
        yield connection
        await tx.rollback()
    await engine.dispose()


async def test_sql_hides_password_hashes_however_they_are_selected(conn) -> None:
    out = await ops.sql(
        ops.SqlRequest(
            sql="SELECT u.*, row_to_json(u) AS j, u::text AS t FROM users u WHERE email = 'sa16@example.in'"
        ),
        conn=conn,
    )
    assert BCRYPT not in str(out["rows"])
    row = dict(zip(out["columns"], out["rows"][0], strict=False))
    assert row["hashed_password"] == ops.HIDDEN
    assert row["j"]["hashed_password"] == ops.HIDDEN
    assert ops.HIDDEN in row["t"] and "SA-16 Owner" in row["t"]


async def test_sql_cannot_write_and_reads_are_audited(conn) -> None:
    with pytest.raises(HTTPException) as refused:
        await ops.sql(ops.SqlRequest(sql="DELETE FROM users"), conn=conn)
    assert "read-only" in refused.value.detail

    with pytest.raises(HTTPException) as hidden_write:
        await ops.sql(
            ops.SqlRequest(sql="WITH d AS (DELETE FROM users WHERE email = 'sa16@example.in' RETURNING 1) SELECT * FROM d"),
            conn=conn,
        )
    assert "read-only" in hidden_write.value.detail
    left = await conn.execute(text("SELECT count(*) FROM users WHERE email = 'sa16@example.in'"))
    assert left.scalar_one() == 1


async def test_reads_are_audited_as_claude(conn) -> None:
    await ops.sql(ops.SqlRequest(sql="SELECT 1"), conn=conn)
    rows = await conn.execute(
        text("SELECT actor_kind, details->>'sql' FROM admin_audit_log WHERE actor_label = 'Claude (ops token)'")
    )
    assert ("system", "SELECT 1") in [tuple(r) for r in rows]


async def test_companies_and_tables_on_a_read_only_transaction(conn) -> None:
    await conn.exec_driver_sql("SET TRANSACTION READ ONLY")
    names = [c["name"] for c in (await ops.companies(conn=conn))["companies"]]
    assert "SA-16 Builders" in names
    page = await ops.table("users", limit=500, conn=conn)
    assert BCRYPT not in str(page["rows"])
    with pytest.raises(HTTPException):
        await ops.table("ai_provider_secrets", limit=5, conn=conn)
