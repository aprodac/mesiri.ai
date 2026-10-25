"""Materials day questions (audit 05, MAT-03) against a real database:
"cement used today?", "received yesterday?", "this week?" are answered from
the movements of that period in the project's zone, not from the all-time
totals."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from tests.integration.test_wa103_transfer_opening_e2e import (  # noqa: F401 -- the fixture
    MESSAGE,
    _send,
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


async def _ask(world, **fields):
    entry = QueryEntry(
        context_resolver=world.entry.context_resolver, org_settings_query=None, actor=world.entry.actor,
        inventory_query=world.entry.inventory_query,
    )
    candidate = Candidate(semantic_type=SemanticType.INVENTORY_QUERY, fields={"material_name": "cement", **fields})
    ready = await entry.prepare(MESSAGE, _Understanding(candidate), candidate)
    assert isinstance(ready, Ready), ready
    run = await world.runtime.start(ready.decision, ready.event)
    return run.pending_prompt


async def test_mat03_used_and_received_by_day_are_not_the_all_time_totals(world):
    yesterday = (_today() - dt.timedelta(days=1)).isoformat()
    await _send(world, direction="opening_stock", quantity=500)
    await _send(world, direction="used", quantity=10, occurred_on=yesterday)
    await _send(world, direction="received", quantity=50)
    await _send(world, direction="used", quantity=5)

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


async def test_mat03_a_day_without_movements_says_so_with_the_stock(world):
    await _send(world, direction="opening_stock", quantity=500)
    said = await _ask(world, date="2020-01-01")
    assert "no cement was used or received" in said.lower() and "left now" in said
