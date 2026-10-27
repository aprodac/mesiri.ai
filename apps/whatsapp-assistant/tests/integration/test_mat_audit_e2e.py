"""Materials day questions (audit 05, MAT-03) against a real database:
"cement used today?", "received yesterday?", "this week?" are answered from
the movements of that period in the project's zone, not from the all-time
totals."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from tests.integration._tap_save import tap_save
from tests.integration.test_wa103_transfer_opening_e2e import (  # noqa: F401 -- the fixture
    MESSAGE,
    _send,
    _stock,
    _Understanding,
    world,
)

from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.enums import SemanticType
from runtime.agent.entry_base import Ready
from runtime.agent.query_entry import QueryEntry

pytestmark = pytest.mark.integration


def _today() -> dt.date:
    return dt.datetime.now(ZoneInfo("Asia/Kolkata")).date()


async def _ask(world, **fields):  # noqa: F811 -- pytest fixture imported from the shared e2e module
    entry = QueryEntry(
        context_resolver=world.entry.context_resolver, org_settings_query=None, actor=world.entry.actor,
        inventory_query=world.entry.inventory_query,
    )
    candidate = Candidate(semantic_type=SemanticType.INVENTORY_QUERY, fields={"material_name": "cement", **fields})
    ready = await entry.prepare(MESSAGE, _Understanding(candidate), candidate)
    assert isinstance(ready, Ready), ready
    run = await world.runtime.start(ready.decision, ready.event)
    return run.pending_prompt


async def test_mat03_used_and_received_by_day_are_not_the_all_time_totals(world):  # noqa: F811 -- pytest fixture imported from the shared e2e module
    yesterday = (_today() - dt.timedelta(days=1)).isoformat()
    await _send(world, direction="opening_stock", quantity=500)
    await _send(world, direction="used", quantity=10, occurred_on=yesterday)
    await _send(world, direction="received", quantity=50)
    await _send(world, direction="used", quantity=5)
    await tap_save(world.db, world.org)  # WA-77: counted once saved

    said = await _ask(world, date_range="yesterday")
    assert "10 bags cement used" in said and "received" not in said.split(".")[0]
    assert said.startswith("Yesterday (")
    assert "535 bags left now" in said  # 500 + 50 - 10 - 5

    said = await _ask(world, date_range="today")
    assert "5 bags cement used" in said and "50 bags cement received" in said and "left now" in said

    said = await _ask(world, date_range="this_week")
    assert "bags cement used" in said

    # no period named: the totals, as before
    assert "In stock" in await _ask(world)


async def test_wa42_an_entry_not_yet_saved_is_not_in_the_days_figures(world):  # noqa: F811 -- pytest fixture imported from the shared e2e module
    """WA-42 + WA-77: today's used / received and the stock left are what was
    saved; an entry still waiting for ✅ Save is in neither."""
    await _send(world, direction="opening_stock", quantity=500)
    await _send(world, direction="used", quantity=5)
    await tap_save(world.db, world.org)
    await _send(world, direction="used", quantity=7)  # not saved yet

    said = await _ask(world, date_range="today")
    assert "5 bags cement used" in said and "12 bags" not in said and "7 bags" not in said
    assert "495 bags left now" in said

    await tap_save(world.db, world.org)
    said = await _ask(world, date_range="today")
    assert "12 bags cement used" in said and "488 bags left now" in said


async def test_mat03_a_day_without_movements_says_so_with_the_stock(world):  # noqa: F811 -- pytest fixture imported from the shared e2e module
    await _send(world, direction="opening_stock", quantity=500)
    await tap_save(world.db, world.org)  # WA-77: counted once saved
    said = await _ask(world, date="2020-01-01")
    assert "no cement was used or received" in said.lower() and "left now" in said


async def test_mat06_once_the_conversion_is_stored_an_engineer_is_never_asked(world):  # noqa: F811 -- pytest fixture imported from the shared e2e module
    """"2 loads sand came" for sand counted in cum: the admin's stored
    "1 load = 4 cum" is used for the engineer's report, with no question."""
    from runtime.agent.entry_base import Say
    from runtime.material_catalog_query import MaterialCatalogQueryService

    catalog = MaterialCatalogQueryService(world.db)
    org = str(world.org)
    [sand] = await catalog.find_materials(organization_id=org, name="Sand")
    stock_unit = await catalog.get_unit(str(sand["default_unit_id"]))

    async def report(role: str):
        world.entry.actor.role = role
        candidate = Candidate(
            semantic_type=SemanticType.MATERIAL_UPDATE,
            fields={"material_name": "sand", "quantity": 2, "unit": "loads", "direction": "received"},
        )
        return await world.entry.prepare(MESSAGE, _Understanding(candidate), candidate)

    before = await report("SITE_ENGINEER")
    if stock_unit["code"] == "load":
        pytest.skip("the starter catalogue counts sand in loads")
    assert isinstance(before, Say), "no conversion yet: the engineer is asked for the amount"
    assert "cum" in before.text and "Cubic Meters" not in before.text

    saved = await catalog.set_conversion(
        organization_id=org, role="PROJECT_MANAGER", user_id=str(world.user),
        material_name="sand", unit_text="loads", count=0.25,  # 0.25 load per cum: 1 load = 4 cum
    )
    assert "Saved" in saved, saved

    ready = await report("SITE_ENGINEER")
    assert isinstance(ready, Ready), ready
    assert ready.event.fields["quantity"] == 8 and ready.event.fields["unit"] == stock_unit["code"]
    assert ready.event.fields["reported_quantity"] == 2


async def test_pho03_the_bill_photo_stays_with_the_material_receipt(world):  # noqa: F811 -- pytest fixture imported from the shared e2e module
    from sqlalchemy import text

    saved = await _send(world, direction="received", quantity=50, supplier="Sharma Traders",
                        media_object_key="media/wamid.bill/1")
    assert saved is not None and saved.saved_draft
    async with world.db.transaction() as conn:
        row = (await conn.execute(text(
            "SELECT r.invoice_id, i.supplier_name, i.source, a.media_object_key, a.attachment_type"
            " FROM material_receipts r JOIN material_invoices i ON i.id = r.invoice_id"
            " JOIN material_invoice_attachments a ON a.invoice_id = i.id"
            " WHERE r.organization_id = :o"), {"o": world.org})).one()
    assert row[1:] == ("Sharma Traders", "whatsapp", "media/wamid.bill/1", "bill")
    assert await _stock(world, 0) == 50  # inventory does not care how it arrived

    # a delivery typed in, with no photo, makes no invoice
    await _send(world, direction="received", quantity=10)
    async with world.db.transaction() as conn:
        n = (await conn.execute(text("SELECT count(*) FROM material_invoices WHERE organization_id = :o"),
                                {"o": world.org})).scalar_one()
    assert n == 1
