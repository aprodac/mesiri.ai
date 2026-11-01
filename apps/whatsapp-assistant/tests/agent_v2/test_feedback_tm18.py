"""TM-18: v2 passes a missing feature and a "bad UX" complaint to the team (``tell_the_team``).

CI: the tool is offered, the rule is in the general skill, the call writes nothing and reaches the
``agent_v2_live`` trace (what the team bot's production watch reads), the model is told to ask
what was bad when no reason was given, and every case of ``skills/general/evals.yaml`` gives
exactly its lines. Live (``pytest -m live``, needs GEMINI_API_KEY): the real model on that set.
"""

from __future__ import annotations

import os

import pytest
from tests.agent_v2.evalkit import Recording
from tests.agent_v2.replaykit import new_world
from tests.agent_v2.skillkit import load, run_case, scripted

from agent_v2.agents.main import all_specs, system_prompt
from agent_v2.runner import LIVE_STAGE, V2Runner
from agent_v2.skills.general import tools as general
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.runner import AgentRunner

CASES = load("general")


def test_the_tool_is_offered_and_the_rule_reaches_the_model():
    spec = next(s for s in all_specs() if s.name == general.TELL_THE_TEAM)
    assert spec.parameters["properties"]["kind"]["enum"] == list(general.FEEDBACK_KINDS)
    rules = system_prompt("english")
    assert "tell_the_team" in rules and "bad_ux" in rules and "missing_feature" in rules


def test_bad_ux_without_a_reason_asks_what_was_bad_and_with_one_does_not():
    ask = general.feedback_instruction({"kind": "bad_ux", "about": "the last reply"})
    assert "ONE short question" in ask
    told = general.feedback_instruction({"kind": "bad_ux", "about": "the last reply", "why": "too many buttons"})
    assert "question" not in told
    missing = general.feedback_instruction({"kind": "missing_feature", "about": "create a project"})
    assert "passed it to the team" in missing and "message them here when it works" in missing


class _Trace:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def log_stage(self, **row) -> None:  # noqa: ANN003
        self.rows.append(row)


async def test_the_call_saves_nothing_reaches_the_trace_and_the_reply_says_it_was_passed_on():
    world = await new_world()
    trace = _Trace()
    reply = "That isn't here yet. I've passed it to the team to build and will message you here when it works."
    provider = FakeToolCallingProvider(
        [[("tell_the_team", {"kind": "missing_feature", "about": "create a project from WhatsApp"})], reply]
    )
    recording = Recording(provider)
    runner = V2Runner(recording, AgentRunner(FakeToolCallingProvider(["(today's agent)"])), trace_logger=trace)
    result = await runner.run(
        ctx=world.context(), user_text="create a new project Green Villa", gateway=world.gateway("create a new project"),
        scope=world.scope(), correlation_id="cor_tm18",
    )
    assert result.outcome == "ok"
    assert not result.toolbox.attempted_writes
    assert "passed it to the team" in result.reply.text
    live = [r for r in trace.rows if r["stage"] == LIVE_STAGE]
    assert live and live[-1]["stage_payload"]["calls"][0]["tool"] == "tell_the_team"
    assert live[-1]["stage_payload"]["calls"][0]["args"]["kind"] == "missing_feature"


async def test_a_shadow_run_records_the_call_and_tells_nothing():
    from agent_v2.agents.main import MainAgent, V2Run
    from runtime.agent.toolbox import AgentToolbox

    world = await new_world()
    state = V2Run(toolbox=AgentToolbox(gateway=world.gateway("bad ux"), scope=world.scope(), user_text="bad ux"))
    handle = MainAgent(FakeToolCallingProvider(["x"])).handler(state, None, shadow=True)
    outcome = await handle("tell_the_team", {"kind": "bad_ux", "about": "the last reply"})
    assert outcome.content == {"status": "shadow"}
    assert state.calls == [("tell_the_team", {"kind": "bad_ux", "about": "the last reply"})]


def test_the_eval_set_has_the_feature_the_complaint_and_the_guards():
    kinds = {c["calls"][0][1].get("kind") for c in CASES if c["calls"] and c["calls"][0][0] == "tell_the_team"}
    assert {"missing_feature", "bad_ux"} <= kinds
    assert any("tell_the_team" in c.get("must_not_call", []) for c in CASES)
    assert len({c["id"] for c in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[f"general#{c['id']}:{c['message'][:24]}" for c in CASES])
async def test_the_good_run_of_each_case_gives_exactly_the_expected_lines(case):
    verdict, _ = await run_case(case, scripted(case))
    assert verdict.right, verdict.why
    assert not verdict.wrong_save


@pytest.mark.live
async def test_live_model_on_the_feedback_set():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider

    provider = GeminiProvider(GeminiSettings(api_key=SecretStr(key), model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")))
    right, wrong = 0, []
    for case in CASES:
        verdict, _ = await run_case(case, provider)
        right += verdict.right
        if verdict.wrong_save:
            wrong.append(case["id"])
        print(f"{'PASS' if verdict.right else 'FAIL'} general#{case['id']} {case['message']!r} {verdict.why}")
    assert not wrong
    assert right / len(CASES) >= 0.9
