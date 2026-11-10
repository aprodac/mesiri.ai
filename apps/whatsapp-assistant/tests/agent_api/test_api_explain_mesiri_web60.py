"""WEB-60 (5 Nov, Ilan's voice note "മേസിരി എന്തൊക്കെ ചെയ്യാൻ പറ്റും"): the question about what Mesiri can do left no
sign in the turn (no tool: the answer came from the prompt's "What Mesiri does" block), so the dashboard's Live could
not play Mesiri's introduction for it. The model now calls ``explain_mesiri`` first (SOP rule 11): it writes nothing and
is in the turn's calls, where the Live feed reads it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from tests.agent_api.replaykit import RecordedApi, _real_tools
from tests.agent_api.test_api_lose_nothing_198 import Runs

from agent_api.agent import EXPLAIN, SOP, ApiAgent
from agent_api.tools import what_mesiri_does

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


async def test_show_me_what_you_can_do_is_the_same_question() -> None:
    """6 Nov 00:30 (Ilan): "ഹലോ നിനക്ക് ചെയ്യാൻ പറ്റുന്നതൊക്കെ ഒന്ന് കാണിക്ക്" got a link to the day's summary. Rule 11 now
    names "show me what you can do" (a demonstration, never a link or the day's summary)."""
    assert "show me what you can do" in SOP and "never a link or a summary of the day" in SOP
    model = Runs([[EXPLAIN_CALL], "I record attendance, materials, work and issues from your messages."])
    turn, api = await _turn(model, "ഹലോ നിനക്ക് ചെയ്യാൻ പറ്റുന്നതൊക്കെ ഒന്ന് കാണിക്ക്")
    assert _tools(turn) == [EXPLAIN] and api.seen == []


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


async def test_the_block_is_sent_by_the_call_not_on_every_message() -> None:
    """WA-272 (10 Nov: about 43,000 input tokens on every model call): the "What Mesiri does" block (about 2,400 of
    them) rode on every message for a question asked now and then. It comes back from ``explain_mesiri`` instead."""
    tools = _real_tools()
    agent = ApiAgent(Runs(["Hello!"]), tools)  # type: ignore[arg-type]
    assert "What Mesiri does (from your tools" not in agent.system_prompt(sender_name="Ravi", today=dt.date(2026, 11, 10))

    model = Runs([[EXPLAIN_CALL], "I record attendance, materials, work and issues."])
    turn, _ = await _turn(model, "what can you do?")
    returned = turn.calls[0]["result"]["what_mesiri_does"]
    assert returned == what_mesiri_does(tools) and "Record (" in returned
