"""Request 174: the v2 materials eval set.

CI (scripted): each case's ``calls`` go through V2Runner and the real draft code, so the card
half is checked: right lines, no wrong line. Live (``pytest -m live``, needs GEMINI_API_KEY):
the real model reads each message; the Phase C gate is >= 90% right and 0 wrong saves over
the 30 new cases plus the 25 of the golden set, and the reply-time numbers are printed.
"""

from __future__ import annotations

import os
import statistics
import time

import pytest
from tests.agent_v2.evalkit import golden_as_evals, load_evals, run_case, run_classic_timing

from mesiri_ai.fakes import FakeToolCallingProvider

EVALS = load_evals()
GOLDEN = golden_as_evals()


def test_the_eval_set_is_well_formed():
    assert len(EVALS) == 50 and len({c["id"] for c in EVALS}) == 50
    assert len(GOLDEN) == 25
    for case in EVALS:
        kinds = [bool(case["expect"]), bool(case.get("ask")), bool(case.get("query")), bool(case.get("other")), bool(case.get("not_built"))]
        assert sum(kinds) == 1, case["id"]
        assert case["calls"] or case.get("other"), case["id"]
    langs = {c["lang"] for c in EVALS}
    assert {"en", "manglish", "ml", "hindi"} <= langs


@pytest.mark.parametrize("case", EVALS, ids=[f"{c['id']}:{c['message'][:28]}" for c in EVALS])
async def test_the_good_run_of_each_case_gives_exactly_the_expected_card(case):
    calls = [(name, args) for name, args in case["calls"]]
    if not calls:
        script = ["I am sorry about that. I will answer only what you ask."]
    else:
        script = [calls, "Check it."] if not case.get("ask") else [calls]
    provider = FakeToolCallingProvider(script)
    verdict, _ = await run_case(case, provider)
    assert verdict.right, verdict.why
    assert not verdict.wrong_save


async def test_the_judge_calls_a_wrong_material_line_in_a_non_material_message_a_wrong_save():
    case = next(c for c in EVALS if c["id"] == 125)  # "JCB breakdown aayi" is an issue, never a material line
    provider = FakeToolCallingProvider([[("draft_usage", {"material": "cement", "quantity": 20, "unit": "bags"})], "ok"])
    verdict, _ = await run_case(case, provider)
    assert verdict.wrong_save and not verdict.right


async def test_the_judge_calls_a_count_saved_as_usage_a_wrong_save():
    case = next(c for c in EVALS if c["id"] == 104)  # "cement theernnu" is a count of 0
    provider = FakeToolCallingProvider([[("draft_usage", {"material": "cement", "quantity": 20, "unit": "bags"})], "ok"])
    verdict, _ = await run_case(case, provider)
    assert verdict.wrong_save


async def test_the_judge_calls_split_cement_a_wrong_save():
    case = next(c for c in EVALS if c["id"] == 101)  # സിമൻറ് must land on the catalog's Cement
    provider = FakeToolCallingProvider([[("draft_receipt", {"material": "സിമൻറ്", "quantity": 30, "unit": "bags"})], "ok"])
    verdict, _ = await run_case(case, provider)
    assert verdict.wrong_save


@pytest.mark.live
async def test_live_model_on_the_v2_gate_set():
    """The go-live gate on the real model (request 178). Prints one line per case, then accuracy, wrong
    saves and p50/p95 of v2 and of today's agent on the same messages. Run it with
    ``GEMINI_MODEL=<model>`` per candidate brain and put the numbers in
    docs/agents/ADR-v2-agent-framework.md. Gate: >= 90% right, 0 wrong saves, v2 p95 no worse than
    today's agent. No GEMINI_API_KEY: skipped, and v2 does not go to a team bot live run."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    provider = GeminiProvider(GeminiSettings(api_key=SecretStr(key), model=model))
    cases = [*EVALS, *GOLDEN]
    right, wrong_saves, times, classic_times = 0, [], [], []
    for case in cases:
        started = time.perf_counter()
        verdict, _ = await run_case(case, provider)
        times.append(time.perf_counter() - started)
        classic_times.append(await run_classic_timing(case, provider))
        right += verdict.right
        if verdict.wrong_save:
            wrong_saves.append(case["id"])
        print(
            f"{'PASS' if verdict.right else 'FAIL'} #{case['id']} {case['message']!r} "
            f"(v2 {times[-1]:.1f}s, today's {classic_times[-1]:.1f}s) {verdict.why}"
        )
    accuracy = right / len(cases)
    times.sort()
    classic_times.sort()

    def p95(values: list[float]) -> float:
        return values[max(0, int(len(values) * 0.95) - 1)]

    print(
        f"MODEL {model} ACCURACY {accuracy:.0%} ({right}/{len(cases)}) WRONG SAVES {len(wrong_saves)} {wrong_saves} "
        f"v2 p50 {statistics.median(times):.1f}s p95 {p95(times):.1f}s | "
        f"today's p50 {statistics.median(classic_times):.1f}s p95 {p95(classic_times):.1f}s"
    )
    assert not wrong_saves, f"wrong saves: {wrong_saves}"
    assert accuracy >= 0.90
    assert p95(times) <= p95(classic_times), "v2's p95 reply time is worse than today's agent"


async def test_the_judge_fails_a_complaint_answered_with_a_stock_inventory():
    case = next(c for c in EVALS if c["id"] == 151)  # Paraclette 31 Oct 18:55: "I never asked for inventory"
    provider = FakeToolCallingProvider([[("stock_for", {"material": "cement"})], "176 bags"])
    verdict, _ = await run_case(case, provider)
    assert not verdict.right and "stock_for" in verdict.why


async def test_the_judge_fails_other_engineers_asked_but_not_looked_up():
    case = next(c for c in EVALS if c["id"] == 154)
    verdict, _ = await run_case(case, FakeToolCallingProvider(["Nobody has."]))
    assert not verdict.right and "query_work_log" in verdict.why
