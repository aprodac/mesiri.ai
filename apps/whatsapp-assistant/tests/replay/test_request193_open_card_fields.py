"""Request 193: every figure a line of the OPEN card shows can be corrected, and a failed
tool call says why in the trace.

Root cause: the change schema the model sees (``tools._CHANGES``, shared by
update_pending_card and, until WA-134, v2's change_line) lacked fields the draft tools themselves take, so
the model had no way to send "rate 420 alla 400", "count 15 alla 12" or "Site C-lekk alla"
as a change (the code behind it already accepted them). The trace kept only "error", never
the reason.

Guards: change_or_undo offers the same fields as before; Labour fields are unchanged; the
code path for a changed cost (already accepted) stays working.
"""

from __future__ import annotations

import pytest
from tests.replay.test_agent_replay import _make_world, _MemoryRedis
from tests.replay.test_draft_per_message_p1 import open_items

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import tools as t
from runtime.agent.cards import CardStore
from runtime.agent.draft_store import MemoryDraftStore
from runtime.agent.turn import trace_reason

CEMENT = ("save_material_receipt", {"material": "cement", "quantity": 50, "unit": "bags", "total_cost": 20000})


def _changes(spec_name: str, specs) -> set[str]:  # noqa: ANN001
    spec = next(s for s in specs if s.name == spec_name)
    return set(spec.parameters["properties"]["changes"]["properties"])


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.cards = CardStore(_MemoryRedis())
    return world


async def test_a_delivery_cost_on_the_open_card_is_corrected_in_place(world):
    await world.say(FakeToolCallingProvider([[CEMENT], "Check it."]), "50 bag cement vannu, 20000")
    fix = ("update_pending_card", {"item_index": 1, "changes": {"total_cost": 18000}})
    result = await world.say(FakeToolCallingProvider([[fix], "Sheri."]), "alla, 18000 aanu")

    (item,) = await open_items(world)
    assert item.args["total_cost"] == 18000 and item.args["quantity"] == 50
    assert "cannot be changed" not in (result.reply.text or "")
    assert world.dispatcher.dispatched == []  # nothing written before Save


def test_every_figure_a_draft_tool_takes_is_changeable_on_the_open_card():
    """The class: stock count, delivery cost, transfer destination, issue kind."""
    open_card = _changes(t.UPDATE_PENDING_CARD, t.tool_specs())
    assert set(t.OPEN_CARD_ONLY_FIELDS) <= open_card


def test_guard_change_or_undo_offers_the_same_fields_as_before():
    saved = _changes(t.CHANGE_OR_UNDO, t.tool_specs())
    assert not set(t.OPEN_CARD_ONLY_FIELDS) & saved
    assert saved == set(t._CHANGES["properties"])
    assert "contractor" not in _changes(t.UPDATE_PENDING_CARD, t.tool_specs())  # Labour unchanged


def test_the_trace_keeps_why_a_call_failed_never_what_was_said():
    assert trace_reason("That line waits for an answer to: How many bags of Cement?") == (
        "That line waits for an answer to"
    )
    assert trace_reason("total_cost cannot be changed on this kind of entry, so nothing was changed.") == (
        "total_cost cannot be changed on this kind of entry, so nothing was changed."
    )
    assert trace_reason("Couldn't read it: 176 bags") == "Couldn't read it"
    assert trace_reason("Site 12 is closed") == "Site ## is closed"
    assert len(trace_reason("x" * 300)) == 80
    assert trace_reason(None) == ""
