"""Materials golden set (WA-36): the exact records each material message saves.

The pilot's pass bar (ADR "Direction", section 8) is 100% save accuracy on
this set. Two runs over the same cases:

- CI (scripted): each case's ``calls`` -- what a good model does -- go through
  the real journey (gates, planner, workflow graphs, save-first) over the seed
  company, and the saved records must be exactly ``expect``. This keeps the
  save half of "the AI decides, the code saves" honest.
- live (``pytest -m live``, needs GEMINI_API_KEY): the real model reads each
  ``message`` and chooses the tools itself. Prints one line per case, the
  accuracy and the p50 time, and fails below 100%.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from pathlib import Path
from typing import Any

import pytest

from mesiri_ai.fakes import FakeToolCallingProvider

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.replay.test_agent_replay import World, _make_world  # noqa: E402

from context import seed  # noqa: E402

PATH = Path(__file__).with_name("materials_golden.yaml")


def load_golden() -> list[dict[str, Any]]:
    return [
        json.loads(line.strip()[2:])
        for line in PATH.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- {")
    ]


CASES = load_golden()
QUERY_TOOLS = frozenset({"query_materials", "query_labour", "query_work_log", "query_project", "query_expenses"})


def _name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _unit(value: Any) -> str:
    unit = str(value or "").strip().lower().rstrip(".")
    return unit[:-1] if unit.endswith("s") and len(unit) > 2 else unit


def _matches(expected: dict[str, Any], action: str, fields: dict[str, Any]) -> bool:
    if action != expected["action"]:
        return False
    if "material" in expected and _name(fields.get("material_name")) not in {_name(m) for m in expected["material"]}:
        return False
    if "quantity" in expected:
        try:
            if float(fields.get("quantity")) != float(expected["quantity"]):
                return False
        except (TypeError, ValueError):
            return False
    if "unit" in expected and _unit(fields.get("unit")) not in {_unit(u) for u in expected["unit"]}:
        return False
    for key in ("supplier", "work_item"):
        if key in expected and expected[key] not in str(fields.get(key) or "").lower():
            return False
    return True


def saved_records(world: World) -> list[tuple[str, dict[str, Any]]]:
    return [(c.draft_action.action_type.value, dict(c.draft_action.fields)) for c in world.dispatcher.dispatched]


def mismatch(case: dict[str, Any], world: World, result: Any) -> str | None:
    """Why the run is wrong for ``case``, or None when it is exactly right."""
    records = saved_records(world)
    left = list(records)
    for expected in case["expect"]:
        hit = next((r for r in left if _matches(expected, *r)), None)
        if hit is None:
            return f"missing {expected} in {records}"
        left.remove(hit)
    if left:
        return f"extra records {left}"
    called = [c.name for c in (result.run.calls if result.run else [])]
    if case.get("ask") and (result.toolbox.parked is None or "?" not in result.reply.text):
        return f"expected one question, got {result.reply.text!r}"
    if case.get("query") and not QUERY_TOOLS.intersection(called):
        return f"expected a query tool, called {called}"
    if case.get("chat") and called:
        return f"expected a plain reply, called {called}"
    if case.get("card") and not world.last_gateway.action_items:
        return "expected a card waiting on the tap"
    return None


_NATIVE = re.compile(r"[\u0900-\u0d7f]")  # Devanagari .. Malayalam


def wrong_script(case: dict[str, Any], reply: str) -> str | None:
    """Live only: the reply is in the letters of the message (Malayalam
    script gets Malayalam script; English and Manglish get English letters)."""
    native = bool(_NATIVE.search(reply))
    if case["lang"] == "ml" and not native:
        return "expected Malayalam script"
    if case["lang"] in ("en", "manglish") and native:
        return "expected English letters"
    return None


def test_the_golden_set_is_well_formed():
    assert len(CASES) == 24
    assert len({c["id"] for c in CASES}) == len(CASES)
    for case in CASES:
        assert case["message"] and (case["calls"] or case.get("chat")), case["id"]
        assert bool(case["expect"]) != bool(
            case.get("ask") or case.get("query") or case.get("chat") or case.get("card")
        ), case["id"]
    langs = {c["lang"] for c in CASES}
    assert {"en", "manglish", "ml", "hindi"} <= langs


@pytest.mark.parametrize("case", CASES, ids=[f"{c['id']}:{c['message'][:30]}" for c in CASES])
async def test_the_save_code_files_exactly_the_expected_records(case):
    world = await _make_world(site_keys=(seed.SITE_A1,))
    if case.get("card"):
        from tests.unit.request104_fakes import ENGINEER, FakeActions

        world.actions = FakeActions(people=[ENGINEER])
    calls = [(name, args) for name, args in case["calls"]]
    question = next((args["question"] for name, args in calls if name == "ask_user"), "")
    provider = FakeToolCallingProvider([calls, question or "Done."] if calls else ["Anytime 👍"])

    result = await world.say(provider, case["message"])

    assert result.outcome == "ok"
    assert mismatch(case, world, result) is None, mismatch(case, world, result)


@pytest.mark.live
async def test_live_model_on_the_materials_golden_set():
    """The pilot measurement: the real model, every case. Prints the per-case
    result, the accuracy and the p50 time (record them in the ADR, section 8)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider

    provider = GeminiProvider(
        GeminiSettings(api_key=SecretStr(key), model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    )
    failures, times = [], []
    for case in CASES:
        world = await _make_world(site_keys=(seed.SITE_A1,))
        started = time.perf_counter()
        result = await world.say(provider, case["message"])
        times.append(time.perf_counter() - started)
        why = mismatch(case, world, result) if result.outcome == "ok" else f"outcome {result.outcome}"
        why = why or wrong_script(case, result.reply.text if result.reply else "")
        print(f"{'PASS' if why is None else 'FAIL'} #{case['id']} {case['message']!r} ({times[-1]:.1f}s) {why or ''}")
        if why is not None:
            failures.append(case["id"])
            calls = [(c.name, c.outcome.content.get("status"), str(c.outcome.content.get("text") or "")[:160]) for c in (result.run.calls if result.run else [])]
            print(f"    reply={(result.reply.text if result.reply else '')[:200]!r} calls={calls}")
    accuracy = 1 - len(failures) / len(CASES)
    print(f"ACCURACY {accuracy:.0%} ({len(CASES) - len(failures)}/{len(CASES)}) p50 {statistics.median(times):.1f}s")
    assert not failures, f"failed cases: {failures}"


@pytest.mark.parametrize(
    ("lang", "reply", "ok"),
    [
        ("ml", "ശരി, 40 ചാക്ക് സിമന്റ് വന്നു.", True),
        ("ml", "Sheri, 40 bag cement vannu.", False),
        ("manglish", "Sheri, 40 bag cement vannu.", True),
        ("en", "സന്തോഷം!", False),  # the 21 Oct "thanks bro 👍" reply
        ("en", "Anytime 👍", True),
    ],
)
def test_the_live_run_checks_the_reply_script(lang, reply, ok):
    assert (wrong_script({"lang": lang}, reply) is None) is ok
