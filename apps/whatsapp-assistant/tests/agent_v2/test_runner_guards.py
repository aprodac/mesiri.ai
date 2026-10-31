"""Request 174: the v2 runners. The model is scripted, everything after it is the real
journey (``tests/replay/test_agent_replay.py``'s World), as in the draft-card tests.

Guards: a material message is never handled twice; a message v2 hands back always reaches
today's agent in the same turn; v2 never writes (only the Save tap does); a shadow saves
nothing and logs.
"""

from __future__ import annotations

import pytest
from tests.replay.test_agent_replay import _make_world
from tests.replay.test_draft_per_message_p1 import open_items, press

from agent_v2.runner import ShadowRunner, V2Runner
from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent.draft_store import MemoryDraftStore
from runtime.agent.runner import AgentRunner

RECEIPT = ("draft_receipt", {"material": "cement", "quantity": 50, "unit": "bags"})
USAGE = ("draft_usage", {"material": "cement", "quantity": 20, "unit": "bags"})
LABOUR = ("save_labour", {"workers": [{"trade": "mason", "headcount": 6}]})


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    return world


class Trace:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def log_stage(self, **kw):
        self.rows.append(kw)


async def run_v2(world, v2_script, classic_script, text, *, trace=None, gateway=None, **kw):
    v2_provider = FakeToolCallingProvider(v2_script, **kw)
    classic_provider = FakeToolCallingProvider(classic_script)
    runner = V2Runner(v2_provider, AgentRunner(classic_provider), trace_logger=trace)
    gw = gateway or world.gateway(text)
    result = await runner.run(
        ctx=world.context(), user_text=text, gateway=gw, scope=world.scope(), correlation_id="cor_v2"
    )
    world.last_gateway = gw
    return result, v2_provider, classic_provider


async def test_a_receipt_is_drafted_by_v2_alone_and_written_only_on_save(world):
    result, v2, classic = await run_v2(world, [[RECEIPT], "Check it."], ["never"], "50 bag cement vannu")

    assert result.outcome == "ok"
    assert classic.calls == 0  # handled once, by v2
    assert [i.kind for i in await open_items(world)] == [dr.KIND_MATERIAL_IN]
    assert world.dispatcher.dispatched == []  # nothing written before the tap
    assert "✅ Save" in [b.title for b in result.reply.buttons]
    saved, _ = await press(world, result.reply, "✅ Save")
    assert saved.text.startswith("✅ *Saved*") and len(world.dispatcher.dispatched) == 1


async def test_receipt_and_usage_in_one_message_are_two_lines_of_one_card(world):
    result, _, classic = await run_v2(
        world, [[RECEIPT, USAGE], "Check it."], ["never"], "50 bags cement came, used 20 bags"
    )
    assert classic.calls == 0
    assert [i.kind for i in await open_items(world)] == [dr.KIND_MATERIAL_IN, dr.KIND_MATERIAL_OUT]


async def test_a_message_v2_hands_back_goes_to_todays_agent_in_the_same_turn(world):
    result, v2, classic = await run_v2(
        world, [[("hand_back", {"reason": "labour"})]], [[LABOUR], "Check it."], "6 mason vannu"
    )
    assert v2.calls == 1 and classic.calls == 1
    assert [i.kind for i in await open_items(world)] == [dr.KIND_LABOUR]  # today's agent made it
    assert result.outcome == "ok"


async def test_a_mixed_message_is_handed_back_whole_and_nothing_is_lost(world):
    classic_script = [[LABOUR, ("save_material_usage", USAGE[1])], "Check it."]
    result, _, classic = await run_v2(
        world, [[("hand_back", {"reason": "mixed"})]], classic_script, "6 mason, 20 bag cement use cheythu"
    )
    assert classic.calls == 1
    assert [i.kind for i in await open_items(world)] == [dr.KIND_LABOUR, dr.KIND_MATERIAL_OUT]


async def test_hand_back_after_a_draft_is_refused_so_nothing_is_handled_twice(world):
    result, v2, classic = await run_v2(
        world, [[RECEIPT, ("hand_back", {"reason": "oops"})], "Check it."], ["never"], "50 bag cement vannu"
    )
    assert classic.calls == 0
    assert [i.kind for i in await open_items(world)] == [dr.KIND_MATERIAL_IN]


async def test_no_tool_at_all_means_today_s_agent_reads_it(world):
    result, v2, classic = await run_v2(world, ["thanks!"], ["Anytime 👍"], "thanks bro")
    assert classic.calls == 1 and result.reply.text.startswith("Anytime")


async def test_a_v2_failure_before_any_action_falls_back_to_todays_agent(world):
    result, v2, classic = await run_v2(
        world, [], [[LABOUR], "Check it."], "6 mason vannu", error=RuntimeError("model down")
    )
    assert classic.calls == 1 and result.outcome == "ok"


async def test_a_failure_after_a_line_is_on_the_card_never_runs_todays_agent_on_top(world):
    class Boom(FakeToolCallingProvider):
        async def run_tools(self, system_prompt, messages, tools, handler, **kw):
            await handler(*RECEIPT)
            raise RuntimeError("model died after the draft")

    classic = FakeToolCallingProvider(["never"])
    runner = V2Runner(Boom([]), AgentRunner(classic))
    result = await runner.run(
        ctx=world.context(), user_text="50 bag cement vannu", gateway=world.gateway("x"), scope=world.scope()
    )
    assert classic.calls == 0 and result.outcome == "degraded"
    assert [i.kind for i in await open_items(world)] == [dr.KIND_MATERIAL_IN]


async def test_v2_never_reads_a_message_when_the_company_has_no_draft_card(world):
    world.draft_v2 = False
    result, v2, classic = await run_v2(world, [[RECEIPT]], [[LABOUR], "ok"], "50 bag cement vannu")
    assert v2.calls == 0 and classic.calls == 1


async def test_a_waiting_site_question_belongs_to_todays_agent(world):
    v2 = FakeToolCallingProvider([[RECEIPT]])
    classic = FakeToolCallingProvider(["ok"])
    await V2Runner(v2, AgentRunner(classic)).run(
        ctx=world.context(), user_text="Site B", gateway=world.gateway("Site B"), scope=world.scope(),
        site_queue=[{"tool": "save_labour"}],
    )
    assert v2.calls == 0 and classic.calls == 1


async def test_a_figure_that_is_not_on_the_card_is_said(world):
    result, _, _ = await run_v2(world, [[RECEIPT], "Check it."], ["never"], "176 50 bag cement vannu")
    assert "176" in result.reply.text and "did not put" in result.reply.text


async def test_a_message_with_all_figures_placed_has_no_such_line(world):
    result, _, _ = await run_v2(world, [[RECEIPT], "Check it."], ["never"], "50 bag cement vannu")
    assert "did not put" not in result.reply.text


async def test_a_question_to_the_sender_is_v2s_and_saves_nothing(world):
    ask = ("ask", {"question": "Was that cement received or used?", "options": ["Received", "Used"]})
    result, v2, classic = await run_v2(world, [[ask]], ["never"], "50 bags cement")
    assert classic.calls == 0 and "?" in result.reply.text
    assert await open_items(world) == [] and world.dispatcher.dispatched == []


async def test_the_live_run_is_traced_with_who_handled_it(world):
    trace = Trace()
    await run_v2(world, [[("hand_back", {"reason": "labour"})]], [[LABOUR], "ok"], "6 mason", trace=trace)
    row = trace.rows[0]
    assert row["stage"] == "agent_v2_live" and row["stage_payload"]["handled_by"] == "classic"
    assert row["stage_payload"]["why"] == "hand_back:labour"


# -- shadow ----------------------------------------------------------------------


async def test_a_shadow_answers_with_todays_agent_and_logs_v2_beside_it_saving_nothing(world):
    trace = Trace()
    v2 = FakeToolCallingProvider([[RECEIPT], "Check it."])
    classic = FakeToolCallingProvider([[("save_material_receipt", RECEIPT[1])], "Check it."])
    runner = ShadowRunner(v2, AgentRunner(classic), trace_logger=trace)
    result = await runner.run(
        ctx=world.context(), user_text="50 bag cement vannu", gateway=world.gateway("x"), scope=world.scope(),
        correlation_id="cor_shadow",
    )
    await __import__("asyncio").gather(*runner._tasks)

    assert result.outcome == "ok" and classic.calls == 1  # the reply is today's
    assert [i.kind for i in await open_items(world)] == [dr.KIND_MATERIAL_IN]  # one line, by today's agent only
    assert world.dispatcher.dispatched == []
    (row,) = trace.rows
    assert row["stage"] == "agent_v2_shadow"
    payload = row["stage_payload"]
    assert payload["v2"]["took_message"] is True
    assert payload["v2"]["calls"][0]["tool"] == "draft_receipt"
    assert payload["classic"]["calls"][0]["tool"] == "save_material_receipt"


async def test_a_shadow_failure_never_reaches_the_sender(world):
    runner = ShadowRunner(
        FakeToolCallingProvider([], error=RuntimeError("down")),
        AgentRunner(FakeToolCallingProvider([[LABOUR], "ok"])),
        trace_logger=Trace(),
    )
    result = await runner.run(
        ctx=world.context(), user_text="6 mason", gateway=world.gateway("x"), scope=world.scope(), correlation_id="c"
    )
    await __import__("asyncio").gather(*runner._tasks)
    assert result.outcome == "ok"
