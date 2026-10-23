"""Work done, site issues, expenses and labour golden set (ARCH-02, ARCH-03; ADR section 10b).

Each area moves off the classic route only when its set is exact. Two runs
over the same cases, as for materials (``test_materials_golden.py``):

- CI (scripted): each case's ``calls`` go through the real journey over the
  seed company and the saved records must be exactly ``expect``.
- live (``pytest -m live``, needs GEMINI_API_KEY): the real model reads each
  ``message``. Prints one line per case, the accuracy and the p50 time, and
  fails below 100%.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

import pytest

from mesiri_ai.fakes import FakeToolCallingProvider

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.conversation.test_materials_golden import wrong_script  # noqa: E402
from tests.replay.test_agent_replay import World, _make_world  # noqa: E402

from context import seed  # noqa: E402

PATH = Path(__file__).with_name("site_golden.yaml")
CASES = [
    json.loads(line.strip()[2:])
    for line in PATH.read_text(encoding="utf-8").splitlines()
    if line.strip().startswith("- {")
]


def _has(saved: Any, want: Any) -> bool:
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        try:
            return float(saved) == float(want)
        except (TypeError, ValueError):
            return False
    return str(want).lower() in str(saved or "").lower()


def mismatch(case: dict[str, Any], world: World, result: Any) -> str | None:
    """Why the run is wrong for ``case``, or None when it is exactly right."""
    records = [(c.draft_action.action_type.value, dict(c.draft_action.fields)) for c in world.dispatcher.dispatched]
    left = list(records)
    for expected in case["expect"]:
        hit = next(
            (
                r
                for r in left
                if r[0] == expected["action"]
                and all(_has(r[1].get(k), v) for k, v in expected.get("fields", {}).items())
            ),
            None,
        )
        if hit is None:
            return f"missing {expected} in {records}"
        left.remove(hit)
    if left:
        return f"extra records {left}"
    statuses = [c.outcome.content.get("status") for c in (result.run.calls if result.run else [])]
    if case.get("confirm") and "waiting_for_user" not in statuses:
        return f"expected a confirmation, got {statuses}"
    if case.get("ask") and (result.toolbox.parked is None or "?" not in result.reply.text):
        return f"expected one question, got {result.reply.text!r}"
    return lost_part(case, result)


def lost_part(case: dict[str, Any], result: Any) -> str | None:
    """WA-58: a part of the message that was neither saved, nor noted for later,
    nor named in the question."""
    box = result.toolbox
    saved = [i.tool for i in box.saved]
    noted = [i.tool for i in box.later]
    question = (result.reply.text if result.reply else "").lower()
    for part in case.get("keeps", []):
        tool = part["tool"]
        if tool in saved:
            saved.remove(tool)
        elif tool in noted:
            noted.remove(tool)
        elif not any(w in question for w in part["words"]):
            return f"lost the {part['words'][0]} part ({tool}): not saved, noted or asked; reply {question!r}"
    return None


def test_the_site_golden_set_is_well_formed():
    assert len(CASES) == 28
    assert len({c["id"] for c in CASES}) == len(CASES)
    for case in CASES:
        assert case["message"] and case["calls"], case["id"]
        if case.get("keeps"):
            # WA-58: a message with several parts may save some and ask about the rest.
            assert case.get("ask") or case["expect"], case["id"]
        else:
            assert bool(case["expect"]) != bool(case.get("confirm") or case.get("ask")), case["id"]
    assert {"en", "manglish", "ml", "hindi"} <= {c["lang"] for c in CASES}


@pytest.mark.parametrize("case", CASES, ids=[f"{c['id']}:{c['message'][:30]}" for c in CASES])
async def test_the_save_code_files_exactly_the_expected_records(case):
    world = await _make_world(site_keys=(seed.SITE_A1,))
    question = next((args["question"] for name, args in case["calls"] if name == "ask_user"), "")
    provider = FakeToolCallingProvider([[tuple(c) for c in case["calls"]], question or "Done."])

    result = await world.say(provider, case["message"])

    assert result.outcome == "ok"
    assert mismatch(case, world, result) is None, mismatch(case, world, result)


@pytest.mark.live
async def test_live_model_on_the_site_golden_set():
    """The measurement for ARCH-02: the real model, every case. Record the
    accuracy and p50 in the ADR (section 10b) when it runs."""
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
