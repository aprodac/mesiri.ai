"""Request 194: v2 takes every message of its companies (no hand-back, request 180), so a tool
today's agent has and v2 lacks is a feature those companies lost. Undo / change of a SAVED entry
and money transfers are v2 tools again; what is still classic-only is listed here on purpose and
waits for an owner decision (material requests, admin), so a new gap fails this test."""

from __future__ import annotations

from agent_v2.agents.main import all_specs
from agent_v2.skills import rule_files
from agent_v2.skills.materials import tools as m
from runtime.agent import tools as t

#: Today's tools v2 does not offer, each with why. Adding a tool to today's agent without
#: deciding about v2 makes this test fail.
NOT_IN_V2 = {
    t.REQUEST_MATERIAL: "material requests: out of scope of v2 until the owner decides (ADR, Out of scope)",
    t.CREATE_SITE: "admin: owner decision (ADR, Out of scope)",
    t.CREATE_PROJECT: "admin: owner decision",
    t.ADD_MEMBER: "admin: owner decision",
    t.GET_JOIN_CODE: "admin: owner decision",
    t.SAVE_OPENING_STOCK: "draft_stock_count covers a count; opening stock is set in the dashboard",
    t.SET_UNIT_CONVERSION: "answer_question answers the unit question (same code as the tap)",
    t.STILL_TO_DO: "v2 does every part in one turn",
    t.SET_REPLY_LANGUAGE: "v2 replies in the sender's language each turn",
}


def _v2_reaches() -> set[str]:
    names = {s.name for s in all_specs()}
    return names | {m.CLASSIC_NAME[n] for n in names if n in m.CLASSIC_NAME}


def test_undo_change_and_money_transfer_are_v2_tools():
    reach = _v2_reaches()
    assert {t.CHANGE_OR_UNDO, t.UNDO_LAST, t.TRANSFER_MONEY} <= reach


def test_every_tool_of_todays_agent_is_in_v2_or_listed_with_its_reason():
    missing = {s.name for s in t.tool_specs()} - _v2_reaches()
    assert missing == set(NOT_IN_V2), f"decide about v2 for: {sorted(missing ^ set(NOT_IN_V2))}"


def test_the_rules_tell_the_model_to_ask_with_buttons_and_how_to_undo():
    general = rule_files()[0].read_text(encoding="utf-8")
    assert "`ask`" in general and "options" in general and "buttons" in general
    assert "`change_or_undo`" in general and "`undo_last`" in general and "`transfer_money`" in general


async def test_undo_last_through_v2_cancels_the_open_card_and_says_nothing_was_saved():
    from dataclasses import replace

    from tests.agent_v2.evalkit import _Books, _given
    from tests.replay.test_agent_replay import _Catalog, _make_world
    from tests.replay.test_draft_per_message_p1 import open_items

    from agent_v2.runner import V2Runner
    from context import seed
    from mesiri_ai.fakes import FakeToolCallingProvider
    from runtime.agent.draft_store import MemoryDraftStore
    from runtime.agent.runner import AgentRunner

    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2, world.drafts, world.catalog, world.inventory = True, MemoryDraftStore(), _Catalog(), _Books()
    world.actor = replace(world.actor, role="PROJECT_MANAGER")
    await _given(world, {"given": [[["draft_receipt", {"material": "cement", "quantity": 30, "unit": "bags"}]]]})
    assert len(await open_items(world)) == 1

    runner = V2Runner(FakeToolCallingProvider([[("undo_last", {})], "Okay, cancelled."]), AgentRunner(FakeToolCallingProvider(["x"])))
    result = await runner.run(
        ctx=world.context(), user_text="ellam cancel cheyyu", gateway=world.gateway("ellam cancel cheyyu"),
        scope=world.scope(), correlation_id="cor_undo",
    )
    assert await open_items(world) == []
    assert world.dispatcher.dispatched == []  # nothing was ever written
    assert result.reply is not None
