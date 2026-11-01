"""Request 185: every module is a v2 skill (labour, work, issues, expenses, site, reports).

CI: each skill's rules reach the model, its tools are v2's, and each eval case's good run gives
exactly the expected lines through the real card code (so the cases themselves are right).
Live (``pytest -m live``, needs GEMINI_API_KEY): the real model reads every case; gate >= 90%
right and 0 wrong saves, per module.
"""

from __future__ import annotations

import os
from collections import Counter

import pytest
from tests.agent_v2.skillkit import all_cases, run_case, scripted

from agent_v2 import skills
from agent_v2.agents.main import GENERAL_TOOLS, all_specs, system_prompt

CASES = all_cases()


def test_every_module_has_rules_tools_and_cases():
    for module in skills.MODULES:
        folder = skills.DIR / module
        assert (folder / "SKILL.md").read_text(encoding="utf-8").startswith("# "), module
        assert (folder / "tools.py").exists() and (folder / "evals.yaml").exists(), module
    assert {m for m, _ in CASES} == set(skills.MODULES)
    ids = [c["id"] for _, c in CASES]
    assert len(ids) == len(set(ids))


def test_the_model_reads_every_module_rule_file_in_order():
    rules = system_prompt("english")
    heads = [f"# {name}" for name in ("General rules", "Labour rules", "Work done rules", "Issues rules",
                                       "Expenses rules", "Site day rules", "Projects rules", "Reports rules", "Materials rules")]
    positions = [rules.index(h) for h in heads]
    assert positions == sorted(positions)


def test_the_module_tools_are_offered_to_the_model_and_nothing_else_changed():
    offered = {s.name for s in all_specs()}
    assert GENERAL_TOOLS <= offered
    # Request 197: create_project / create_site are the projects skill's. Members stay classic.
    assert {"create_site", "create_project"} <= offered
    assert not offered & {"add_member", "get_join_code"}


@pytest.mark.parametrize(("module", "case"), CASES, ids=[f"{m}#{c['id']}:{c['message'][:24]}" for m, c in CASES])
async def test_the_good_run_of_each_case_gives_exactly_the_expected_lines(module, case):
    verdict, _ = await run_case(case, scripted(case))
    assert verdict.right, verdict.why
    assert not verdict.wrong_save


async def test_the_judge_calls_absent_people_saved_as_labour_a_wrong_save():
    module, case = next((m, c) for m, c in CASES if c["id"] == 306)
    from mesiri_ai.fakes import FakeToolCallingProvider

    bad = FakeToolCallingProvider([[("save_labour", {"workers": [{"trade": "worker", "headcount": 5}]})], "ok"])
    verdict, _ = await run_case(case, bad)
    assert verdict.wrong_save and not verdict.right


@pytest.mark.live
async def test_live_model_on_the_module_skills():
    """Gate per module on the real model: >= 90% right, 0 wrong saves. Prints one line per case."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    engine = os.environ.get("MESIRI_V2_ENGINE", "v2")  # v2 | adk
    provider = GeminiProvider(GeminiSettings(api_key=SecretStr(key), model=model))
    right, total, wrong = Counter(), Counter(), []
    import asyncio

    pace = float(os.environ.get("MESIRI_LIVE_PACE_SECONDS", "0"))  # stay under the tokens-per-minute cap
    for module, case in CASES:
        if pace:
            await asyncio.sleep(pace)
        verdict, _ = await run_case(case, provider, engine=engine)
        total[module] += 1
        right[module] += verdict.right
        if verdict.wrong_save:
            wrong.append(case["id"])
        print(f"{'PASS' if verdict.right else 'FAIL'} {module}#{case['id']} {case['message']!r} {verdict.why}")
    for module in skills.MODULES:
        print(f"ENGINE {engine} MODEL {model} {module}: {right[module]}/{total[module]}")
    print(f"WRONG SAVES {wrong}")
    assert not wrong
    assert all(right[m] / total[m] >= 0.9 for m in skills.MODULES)


@pytest.mark.parametrize(("module", "case"), CASES[:6], ids=[f"adk:{m}#{c['id']}" for m, c in CASES[:6]])
async def test_the_same_cases_run_on_the_adk_engine(module, case):
    """The kit runs a case on v2-on-ADK too (scripted ADK model), so the live run can compare engines."""
    from agent_v2.adk.models import ScriptedLlm

    calls = [(name, args) for name, args in case["calls"]]
    verdict, _ = await run_case(case, ScriptedLlm([calls, "Check it."] if calls else ["Sorry, I don't have that."]), engine="adk")
    assert verdict.right, verdict.why
