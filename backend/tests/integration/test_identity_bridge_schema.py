"""WhatsApp identity schema (integration, requires Postgres).

M6.5 (migration 0190) added canonical_* bridge columns to the assistant's
``context_*`` copy of identity. BE-01 step 3 (migration 0482) dropped that copy:
WhatsApp reads people, companies, projects and sites straight from the main
tables and finds the sender by the digits of ``users.whatsapp_number``. This
checks whichever of the two the database is at.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

pytestmark = pytest.mark.integration

_BRIDGE_COLUMNS = (
    ("context_organizations", "canonical_organization_id"),
    ("context_users", "canonical_user_id"),
    ("context_projects", "canonical_project_id"),
    ("context_sites", "canonical_site_id"),
)


@pytest.fixture
async def engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    settings = Settings()
    eng = create_async_engine(settings.postgres.dsn())
    yield eng
    await eng.dispose()


async def _revision(engine) -> str:
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()


async def test_bridge_columns_present_until_the_copy_was_dropped(engine) -> None:
    revision = await _revision(engine)
    assert revision >= "0190", f"expected migration >= 0190, got {revision}"
    if revision >= "0482":
        pytest.skip("0482 dropped the context_* copy; see the test below")

    async with engine.connect() as conn:

        def _check(sync_conn):
            inspector = inspect(sync_conn)
            for table, column in _BRIDGE_COLUMNS:
                cols = {c["name"] for c in inspector.get_columns(table)}
                assert column in cols, f"{table}.{column} missing"

        await conn.run_sync(_check)


async def test_whatsapp_reads_identity_from_the_main_tables(engine) -> None:
    """BE-01 step 3: no context_* copy; the sender is found on users by the
    digits of the WhatsApp number, uniquely (0483)."""
    if await _revision(engine) < "0482":
        pytest.skip("database below 0482: the context_* copy is still in use")

    async with engine.connect() as conn:

        def _check(sync_conn):
            inspector = inspect(sync_conn)
            tables = set(inspector.get_table_names())
            for table, _ in _BRIDGE_COLUMNS:
                assert table not in tables, f"{table} should be gone since 0482"
            assert "whatsapp_number" in {c["name"] for c in inspector.get_columns("users")}
            indexes = {i["name"] for i in inspector.get_indexes("users")}
            assert "ix_users_whatsapp_digits" in indexes

        await conn.run_sync(_check)
