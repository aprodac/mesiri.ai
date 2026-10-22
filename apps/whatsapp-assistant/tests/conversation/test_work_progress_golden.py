"""Request [84]: work progress, a report in a mixed message, and the sentence
above the card -- the four live messages of 22 Oct and the checks after deploy.

Two runs over the same cases, as for the other golden sets:

- CI (scripted): the case's ``calls`` go through the real journey over the seed
  company (the real save code), the model's ``sentence`` is scripted, and the
  card must show the ``card`` lines, each once.
- live (``pytest -m live``, needs GEMINI_API_KEY): the real model reads each
  ``message``; its tool calls fill the card, and its sentence must speak of
  every saved item.
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

from tests.replay.test_agent_replay import _make_world  # noqa: E402

from context import seed  # noqa: E402
from runtime.agent.sentence import items_of, missing_items  # noqa: E402

PATH = Path(__file__).with_name("work_progress_golden.yaml")
CASES = [
    json.loads(line.strip()[2:])
    for line in PATH.read_text(encoding="utf-8").splitlines()
    if line.strip().startswith("- {")
]


def mismatch(case: dict[str, Any], result: Any) -> str | None:
    """Why the reply is wrong for ``case``, or None."""
    text = result.reply.text
    for line in case["card"]:
        if text.count(line) != 1:
            return f"card line {line!r} appears {text.count(line)}x in {text!r}"
    if result.toolbox.parked is not None:
        return f"unexpected question: {result.toolbox.parked.text!r}"
    if "labour details" in text.casefold():
        return "asked for details already given"
    items = items_of(result.run.calls) if result.run else []
    absent = missing_items(text.split("\n\n✅ Saved")[0], items)
    if absent:
        return f"sentence leaves out {[i.label for i in absent]}"
    return None


def test_the_work_progress_set_is_well_formed():
    assert len(CASES) == 5
    assert len({c["id"] for c in CASES}) == len(CASES)
    for case in CASES:
        assert case["message"] and case["calls"] and case["sentence"] and case["card"], case["id"]
    assert {"en", "manglish"} <= {c["lang"] for c in CASES}


@pytest.mark.parametrize("case", CASES, ids=[f"{c['id']}:{c['message'][:30]}" for c in CASES])
async def test_the_card_and_the_sentence_for_the_live_messages(case):
    world = await _make_world(site_keys=(seed.SITE_A1,))
    provider = FakeToolCallingProvider([[tuple(c) for c in case["calls"]], case["sentence"]])

    result = await world.say(provider, case["message"])

    assert result.outcome == "ok"
    assert provider.calls == 1  # the sentence covered every item: no second ask
    assert mismatch(case, result) is None, mismatch(case, result)
    if case.get("report"):
        statuses = [c.name for c in result.run.calls]
        assert statuses.index("request_dpr") > statuses.index("save_labour")  # saves first, then the report


@pytest.mark.live
async def test_live_model_on_the_work_progress_set():
    """The recorded smoke run: the real model, every case."""
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
        why = mismatch(case, result) if result.outcome == "ok" and result.reply else f"outcome {result.outcome}"
        print(f"{'PASS' if why is None else 'FAIL'} #{case['id']} {case['message']!r} ({times[-1]:.1f}s) {why or ''}")
        print(f"    reply={(result.reply.text if result.reply else '')!r}")
        if why is not None:
            failures.append(case["id"])
    print(f"ACCURACY {1 - len(failures) / len(CASES):.0%} p50 {statistics.median(times):.1f}s")
    assert not failures, f"failed cases: {failures}"
