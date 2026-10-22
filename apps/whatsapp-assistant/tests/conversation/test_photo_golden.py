"""Photos and bills golden set (ARCH-06; ADR section 10b).

Photos (after the purpose tap) and documents reach the agent as the vision
model's description (runtime/agent/turn.py). This pins what the agent saves
from them. Two runs, as for the other sets:

- CI (scripted): each case's ``calls`` go through the real journey over the
  seed company and the saved records must be exactly ``expect``.
- live (``pytest -m live``, needs GEMINI_API_KEY): the real model reads each
  ``message`` with its ``hint``. Prints one line per case, the accuracy and the
  p50 time, and fails below 100%.
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

from tests.conversation.test_materials_golden import _matches, saved_records  # noqa: E402
from tests.conversation.test_site_golden import _has  # noqa: E402
from tests.replay.test_agent_replay import World, _make_world  # noqa: E402

from context import seed  # noqa: E402

PATH = Path(__file__).with_name("photo_golden.yaml")
CASES = [
    json.loads(line.strip()[2:])
    for line in PATH.read_text(encoding="utf-8").splitlines()
    if line.strip().startswith("- {")
]


def _modality(case: dict[str, Any]) -> Any:
    from mesiri_contracts.assistant.enums import InputModality

    return InputModality.DOCUMENT if case["message"].startswith("(They sent a document") else InputModality.IMAGE


def _hit(expected: dict[str, Any], action: str, fields: dict[str, Any]) -> bool:
    if "material" in expected:
        return _matches(expected, action, fields)
    return action == expected["action"] and all(_has(fields.get(k), v) for k, v in expected.get("fields", {}).items())


def mismatch(case: dict[str, Any], world: World, result: Any) -> str | None:
    """Why the run is wrong for ``case``, or None when it is exactly right."""
    records = saved_records(world)
    left = list(records)
    for expected in case["expect"]:
        hit = next((r for r in left if _hit(expected, *r)), None)
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
    return None


def test_the_photo_golden_set_is_well_formed():
    assert len(CASES) == 10
    assert len({c["id"] for c in CASES}) == len(CASES)
    for case in CASES:
        assert case["message"].startswith("(They sent a "), case["id"]
        assert bool(case["expect"]) != bool(case.get("confirm") or case.get("ask")), case["id"]
    assert {"expense", "material_invoice", "labour_update"} <= {c.get("hint") for c in CASES}


@pytest.mark.parametrize("case", CASES, ids=[f"{c['id']}" for c in CASES])
async def test_the_save_code_files_exactly_the_expected_records(case):
    world = await _make_world(site_keys=(seed.SITE_A1,))
    question = next((args["question"] for name, args in case["calls"] if name == "ask_user"), "")
    provider = FakeToolCallingProvider([[tuple(c) for c in case["calls"]], question or "Done."])

    result = await world.say(provider, case["message"], menu_hint=case.get("hint"), modality=_modality(case))

    assert result.outcome == "ok"
    assert mismatch(case, world, result) is None, mismatch(case, world, result)


@pytest.mark.live
async def test_live_model_on_the_photo_golden_set():
    """The measurement for photos and bills: the real model, every case."""
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
        result = await world.say(provider, case["message"], menu_hint=case.get("hint"), modality=_modality(case))
        times.append(time.perf_counter() - started)
        why = mismatch(case, world, result) if result.outcome == "ok" else f"outcome {result.outcome}"
        print(f"{'PASS' if why is None else 'FAIL'} #{case['id']} {case['message'][:60]!r} ({times[-1]:.1f}s) {why or ''}")
        if why is not None:
            failures.append(case["id"])
            calls = [(c.name, c.outcome.content.get("status"), str(c.outcome.content.get("text") or "")[:160]) for c in (result.run.calls if result.run else [])]
            print(f"    reply={(result.reply.text if result.reply else '')[:200]!r} calls={calls}")
    accuracy = 1 - len(failures) / len(CASES)
    print(f"ACCURACY {accuracy:.0%} ({len(CASES) - len(failures)}/{len(CASES)}) p50 {statistics.median(times):.1f}s")
    assert not failures, f"failed cases: {failures}"
