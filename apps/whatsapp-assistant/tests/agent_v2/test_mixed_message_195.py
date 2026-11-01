"""Request 195 (live 1 Nov, Paraclette, Ilan's voice note): "How are you? How's the weather, did
anyone report it? 50 sacks cement and 20 TMT bars came. Did anyone else report today? 50 labourers
too: 10 helpers, 20 electricians, the rest others."

Root cause (vps-agent-trace 13:25:42): the model's first step called only draft_receipt; a round
that only made card lines ends the run (request 143, speed), so the TMT, the labour, the
"did anyone report" read, the weather answer and the greeting never got a model round.
Fix: such a round ends the run only when the message is plainly finished (every figure placed, one
short sentence); otherwise the model gets the next round, told what is still open.
Guard: "50 bag cement vannu" still ends after its card line (no extra model call: speed).
"""

from __future__ import annotations

from dataclasses import replace

from tests.agent_v2.evalkit import _Books
from tests.replay.test_agent_replay import _Catalog, _make_world
from tests.replay.test_draft_per_message_p1 import open_items

from agent_v2.agents.main import MORE_TO_DO, is_one_part
from agent_v2.runner import V2Runner
from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent.draft_store import MemoryDraftStore
from runtime.agent.runner import AgentRunner

LIVE = (
    "How are you? How is the weather, did anyone report about the weather? By the way 50 sacks of cement "
    "came in and 20 TMT steel bars came in. Did anyone else report anything today? 50 laborers also came, "
    "10 helpers, 20 electricians and others."
)
CEMENT = ("draft_receipt", {"material": "cement", "quantity": 50, "unit": "bags", "figures_placed": [50]})
STEEL = ("draft_receipt", {"material": "steel", "quantity": 20, "unit": "nos", "figures_placed": [20]})
LABOUR = ("save_labour", {"workers": [
    {"trade": "helper", "headcount": 10}, {"trade": "electrician", "headcount": 20}, {"trade": "worker", "headcount": 20},
]})
LOG = ("query_work_log", {"date": "today"})


async def _world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2, world.drafts, world.catalog, world.inventory = True, MemoryDraftStore(), _Catalog(), _Books()
    world.actor = replace(world.actor, role="PROJECT_MANAGER")
    return world


async def _say(world, text: str, script: list):  # noqa: ANN001
    provider = FakeToolCallingProvider(script)
    runner = V2Runner(provider, AgentRunner(FakeToolCallingProvider(["x"])))
    result = await runner.run(
        ctx=world.context(), user_text=text, gateway=world.gateway(text), scope=world.scope(), correlation_id="cor_195",
    )
    return result


async def test_the_live_message_gets_every_part_when_the_first_step_drafts_only_one_line():
    world = await _world()
    # The live run's first step: ONE call. Then the model must get the next round.
    result = await _say(world, LIVE, [[CEMENT], [STEEL, LABOUR, LOG], "I'm fine! No weather data with me."])
    kinds = sorted(i.kind for i in await open_items(world))
    assert kinds == sorted([dr.KIND_MATERIAL_IN, dr.KIND_MATERIAL_IN, dr.KIND_LABOUR])
    assert result.run.stop_reason == "answered"  # the model wrote the reply after all its calls
    assert world.dispatcher.dispatched == []  # nothing written before Save


async def test_sibling_two_materials_in_one_line_still_get_a_second_round():
    world = await _world()
    text = "50 bag cement vannu, 20 rod steel um vannu"
    await _say(world, text, [[CEMENT], [STEEL], "Both below."])
    assert len(await open_items(world)) == 2


async def test_guard_a_one_line_report_still_ends_after_its_card_line():
    world = await _world()
    result = await _say(world, "50 bag cement vannu", [[CEMENT], "NEVER READ"])
    assert result.run.stop_reason == "done_by_tools"  # no extra model call: speed kept
    assert "NEVER READ" not in (result.reply.text if result.reply else "")


def test_what_counts_as_a_finished_message():
    assert is_one_part("50 bag cement vannu", [CEMENT])
    assert not is_one_part("50 bag cement vannu", [])  # 50 not placed yet
    assert not is_one_part(LIVE, [CEMENT])
    assert not is_one_part("50 bag cement vannu, 20 rod steel um vannu", [CEMENT, STEEL])  # two parts
    assert is_one_part("50 bag cement vannu, Raju-nte", [CEMENT])  # a supplier is not a second part
    assert "read tools" in MORE_TO_DO and "greeting" in MORE_TO_DO
