"""WEB-60 (5 Nov, Ilan's voice note "മേസിരി എന്തൊക്കെ ചെയ്യാൻ പറ്റും"): the question about what Mesiri can do left no
sign in the turn (no tool: the answer comes from the prompt's "What Mesiri does" block), so the dashboard's Live could
not play Mesiri's introduction for it. The model now calls ``explain_mesiri`` first (SOP rule 11): it writes nothing and
is in the turn's calls, where the Live feed reads it.
"""

from __future__ import annotations

from typing import Any

from tests.agent_api.replaykit import RecordedApi, _real_tools
from tests.agent_api.test_api_lose_nothing_198 import Runs

from agent_api.agent import EXPLAIN, SOP, ApiAgent

EXPLAIN_CALL = (EXPLAIN, {})


async def _turn(model: Runs, text: str) -> tuple[Any, RecordedApi]:
    api = RecordedApi({})
    return await ApiAgent(model, _real_tools()).run(api, text, facts="Only one site: Asus garden. Use it."), api  # type: ignore[arg-type]


def _tools(turn: Any) -> list[str]:
    return [c["tool"] for c in turn.calls]


async def test_the_reported_question_is_marked_and_writes_nothing() -> None:
    model = Runs([[EXPLAIN_CALL], "Mesiri-kk site-il ninnulla updates record cheyyaam: attendance, materials, work, issues."])
    turn, api = await _turn(model, "മേസിരി എന്തൊക്കെ ചെയ്യാൻ പറ്റും")
    assert _tools(turn) == [EXPLAIN] and api.seen == [] and not turn.pending and not turn.saved
    assert "attendance" in turn.reply


async def test_sibling_english_question_is_marked_the_same() -> None:
    model = Runs([[EXPLAIN_CALL], "I record attendance, materials, work and issues, answer questions, and send the report."])
    turn, _ = await _turn(model, "what can you do?")
    assert _tools(turn) == [EXPLAIN]


async def test_the_tool_is_offered_and_the_sop_says_when() -> None:
    seen: list[list[str]] = []

    class Spy(Runs):
        async def run_tools(self, system: str, messages: list, tools: Any, *args: Any, **kwargs: Any) -> Any:
            seen.append([t.name for t in tools])
            return await super().run_tools(system, messages, tools, *args, **kwargs)

    await _turn(Spy(["Hello!"]), "hi")
    assert EXPLAIN in seen[0]
    assert "explain_mesiri" in SOP


async def test_guard_an_entry_is_not_marked() -> None:
    model = Runs(["Hello Ilan! Site-ile update ayakkaamo?"])
    turn, _ = await _turn(model, "Hello sukhamaano")
    assert EXPLAIN not in _tools(turn)
