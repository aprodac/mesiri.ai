"""BE-44: the control panel's "delete company" works for a company that has
used Mesiri: material entries (saved, and one cancelled, which leaves a
reversal), not only the empty tenant of test_admin_delete_organization."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from tests.integration._tap_save import tap_save
from tests.integration.test_wa103_transfer_opening_e2e import (  # noqa: F401 -- the fixture
    _send,
    world,
)

from admin import router as admin_router

pytestmark = pytest.mark.integration


async def test_a_company_with_material_entries_and_a_cancel_can_be_deleted(world, monkeypatch):  # noqa: F811 -- pytest fixture imported from the shared e2e module
    from mesiri.bootstrap.settings import Settings

    await _send(world, direction="opening_stock", quantity=50)
    await _send(world, direction="received", quantity=20)
    await tap_save(world.db, world.org)
    used = await _send(world, direction="used", quantity=5)
    assert used is not None and used.saved_draft
    # Cancel the use: its draft is rejected and the movement reversed.
    await world.handler.undo_latest_draft(organization_id=str(world.org), user_id=world.user)

    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    monkeypatch.setattr(admin_router, "get_engine", lambda: engine)
    try:
        await admin_router.delete_organization(world.org, _admin={"sub": "platform-admin"})
        async with engine.connect() as conn:
            for table in ("organizations", "material_movements", "material_receipts", "material_usage", "fact_reviews"):
                column = "id" if table == "organizations" else "organization_id"
                left = (
                    await conn.execute(sa.text(f"SELECT count(*) FROM {table} WHERE {column} = :o"), {"o": world.org})  # noqa: S608
                ).scalar_one()
                assert left == 0, f"{table} still has rows for the deleted company"
    finally:
        await engine.dispose()
