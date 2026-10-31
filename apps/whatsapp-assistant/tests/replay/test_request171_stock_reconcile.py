"""Request 171 (production watch, 31 Oct, Adarsh @ Paraclette): "cement stock kazhinju" while the
books show 176 bags.  The card asks "Records show 176 bag Cement. Set stock to 0?" (Set to 0 /
Enter count / Keep); a tap fills a stock count that is written as an adjustment for the
difference, only after Save.  "Stock count: cement 20" is the same line.  Nothing is adjusted
by a tap on the question alone.  The model is scripted; the rest is the real journey."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from tests.replay.test_agent_replay import _Catalog, _make_world
from tests.replay.test_draft_per_message_p1 import open_items, press, titles

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.draft_action import DraftActionType
from runtime.agent import draft as dr
from runtime.agent.draft_store import MemoryDraftStore

SHORTAGE = ("report_issue", {"issue_type": "MATERIAL_SHORTAGE", "narrative": "Cement stock finished", "severity": "HIGH"})


class _Books:
    def __init__(self, stock: float) -> None:
        self.stock = stock

    async def query(self, **kwargs: Any) -> list[dict]:
        return [{"current_stock": self.stock, "unit": "bag", "material_name": "Cement", "received": 176, "used": 0}]


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.catalog = _Catalog()
    world.inventory = _Books(176)
    world.actor = replace(world.actor, role="PROJECT_MANAGER")
    return world


async def test_a_shortage_for_cement_the_books_still_show_asks_on_the_card(world):
    """13:27: "cement is finished" -> the card asks with the 176, never "what do you want to know?"."""
    result = await world.say(
        FakeToolCallingProvider([[SHORTAGE], "Noted the cement shortage."]), "cement stock kazhinju"
    )
    text = result.reply.text
    assert "Records show 176 bag cement. Set stock to 0?" in text  # the catalogue's own spelling
    assert {"Set to 0", "Enter count", "Keep"} <= set(titles(result.reply))
    assert world.dispatcher.dispatched == []  # nothing is written, nothing adjusted


async def test_set_to_zero_becomes_a_stock_count_line_and_save_writes_an_adjustment_out(world):
    result = await world.say(FakeToolCallingProvider([[SHORTAGE], "ok"]), "cement stock kazhinju")
    reply, _ = await press(world, result.reply, "Set to 0")
    assert "Stock count: Cement 0" in reply.text and "(records 176)" in reply.text
    assert world.dispatcher.dispatched == []  # the tap on the question writes nothing
    items = await open_items(world)
    assert [i.kind for i in items if i.kind == dr.KIND_STOCK_COUNT] == [dr.KIND_STOCK_COUNT]

    saved, _ = await press(world, reply, "✅ Save")
    usage = [c for c in world.dispatcher.dispatched if c.draft_action.action_type is DraftActionType.RECORD_MATERIAL_USAGE]
    (adjust,) = usage
    f = adjust.draft_action.fields
    assert (f["quantity"], f["movement_reason"]) == (176.0, "ADJUSTMENT_OUT")  # an adjustment, never a fake "used"
    assert f["notes"].startswith("Stock count: records 176, counted 0")
    assert saved is not None


async def test_keep_leaves_the_books_alone(world):
    result = await world.say(FakeToolCallingProvider([[SHORTAGE], "ok"]), "cement stock kazhinju")
    reply, _ = await press(world, result.reply, "Keep")
    assert "stay as they are" in reply.text
    assert not [i for i in await open_items(world) if i.kind == dr.KIND_STOCK_COUNT]
    await press(world, reply, "✅ Save")
    assert not [c for c in world.dispatcher.dispatched if c.draft_action.action_type is DraftActionType.RECORD_MATERIAL_USAGE]


async def test_enter_count_then_a_typed_figure_is_the_count(world):
    result = await world.say(FakeToolCallingProvider([[SHORTAGE], "ok"]), "cement stock kazhinju")
    asked, _ = await press(world, result.reply, "Enter count")
    assert "Type how much" in asked.text
    # the journey reads a typed answer to the card's question before the model runs
    draft = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    typed = await world.gateway("20 bags").answer_draft_typed(draft, "20 bags")
    assert "Stock count: Cement 20" in typed.text and "(records 176)" in typed.text
    await press(world, typed, "✅ Save")
    (adjust,) = [c for c in world.dispatcher.dispatched if c.draft_action.action_type is DraftActionType.RECORD_MATERIAL_USAGE]
    assert adjust.draft_action.fields["quantity"] == 156.0


async def test_stock_count_message_is_the_same_line_without_a_question(world):
    """"Stock count: cement 20 bags" -> the adjustment line, ready to Save."""
    count = ("adjust_stock", {"material": "cement", "counted": 20, "unit": "bags"})
    result = await world.say(FakeToolCallingProvider([[count], "Check it and tap Save."]), "Stock count: cement 20 bags")
    assert "Stock count: Cement 20 bags (records 176)" in result.reply.text
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]
    assert world.dispatcher.dispatched == []


async def test_no_question_when_the_books_already_show_none(world):
    world.inventory = _Books(0)
    result = await world.say(FakeToolCallingProvider([[SHORTAGE], "ok"]), "cement stock kazhinju")
    assert "Records show" not in result.reply.text
    assert "Set to 0" not in titles(result.reply)


async def test_no_question_for_a_sender_who_cannot_adjust(world):
    world.actor = replace(world.actor, role="SITE_ENGINEER")
    result = await world.say(FakeToolCallingProvider([[SHORTAGE], "ok"]), "cement stock kazhinju")
    assert "Records show" not in result.reply.text


async def test_a_plain_stock_question_still_answers_the_level_and_adjusts_nothing(world):
    """Guard: "how much cement is there" is a question; no count line, no write."""
    result = await world.say(FakeToolCallingProvider([[("query_materials", {"material": "cement"})], "176 bags."]), "how much cement is there")
    assert not [i for i in await open_items(world) if i.kind == dr.KIND_STOCK_COUNT]
    assert world.dispatcher.dispatched == []
    assert result.reply is not None


# -- "what to get tomorrow" (13:23 / 13:25) ----------------------------------------------


class _Levels:
    """Paraclette Tower A: cement 176, laterite 0, m sand and bricks negative (used, never received)."""

    ROWS = [
        {"material_name": "cement", "unit": "bag", "received": 176, "used": 0, "current_stock": 176},
        {"material_name": "laterite stone", "unit": "nos", "received": 10, "used": 10, "current_stock": 0},
        {"material_name": "m sand", "unit": "cum", "received": 0, "used": 20, "current_stock": -20},
    ]

    async def query(self, **kwargs: Any) -> list[dict]:
        return [dict(r) for r in self.ROWS]


class _Needs:
    def __init__(self, requests: list[dict] | None = None, issues: list[dict] | None = None) -> None:
        self.requests = requests if requests is not None else [
            {"request": "50 nails (needed tomorrow)", "site_id": None, "asked_on": None, "sent_to": 1},
            {"request": "ladder", "site_id": None, "asked_on": None, "sent_to": 1},
        ]
        self.issues = issues or []

    async def open_requests(self, **kwargs: Any) -> list[dict]:
        return self.requests

    async def list_open(self, **kwargs: Any) -> list[dict]:
        return self.issues

    async def find_latest(self, **kwargs: Any) -> None:
        return None


ASK = ("query_open_needs", {})
GET_TOMORROW = "Give me a list of what's out of stock and what to get tomorrow"


@pytest.fixture
async def asking_world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.query = {"inventory_query": _Levels(), "site_issue_query": _Needs()}
    return world


async def _list_text(world, text: str = GET_TOMORROW) -> str:
    result = await world.say(FakeToolCallingProvider([[ASK], "ok"]), text)
    (call,) = result.run.calls
    assert call.outcome.content["status"] == "answer", call.outcome.content
    return call.outcome.content["text"]


async def test_13_23_what_to_get_tomorrow_is_the_open_needs_not_the_inventory(asking_world):
    text = await _list_text(asking_world)
    assert "50 nails (needed tomorrow)" in text and "ladder" in text  # what he reported earlier
    assert "Laterite Stone" in text  # out of stock
    assert "⚠️ M Sand −20 cum" in text  # a negative balance is flagged
    assert "176" not in text and "Current inventory" not in text  # not the inventory dump


async def test_13_25_the_same_list_again_without_an_ask_back(asking_world):
    first = await _list_text(asking_world, "ഇന്നലെ ഞാൻ പറഞ്ഞത് തന്നെ, നാളെ എടുക്കേണ്ടത്")
    second = await _list_text(asking_world, "what I told you before, what to get")
    assert first == second and "which information" not in second.lower()


async def test_a_request_delivered_is_gone_from_the_list(asking_world):
    asking_world.query["site_issue_query"] = _Needs(requests=[{"request": "ladder", "site_id": None, "asked_on": None, "sent_to": 1}])
    text = await _list_text(asking_world)
    assert "ladder" in text and "nails" not in text


async def test_open_shortage_issues_are_listed(asking_world):
    asking_world.query["site_issue_query"] = _Needs(
        requests=[], issues=[{"issue_type": "MATERIAL_SHORTAGE", "narrative": "Tiles short for 2nd floor"}, {"issue_type": "SAFETY", "narrative": "x"}]
    )
    text = await _list_text(asking_world)
    assert "Tiles short for 2nd floor" in text and "\nx" not in text


async def test_the_plain_level_question_is_still_the_stock(asking_world):
    result = await asking_world.say(FakeToolCallingProvider([[("query_materials", {"material": "cement"})], "176"]), "how much cement is there")
    (call,) = result.run.calls
    assert "176" in call.outcome.content["text"] and "What to get" not in call.outcome.content["text"]
