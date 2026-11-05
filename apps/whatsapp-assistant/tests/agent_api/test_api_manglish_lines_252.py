"""[252] (5 Nov, Adarsh): a Malayalam-script voice note got card lines in Malayalam script, which the code turned
into Latin letter by letter for his Manglish replies: "10 chaakku simantu sairril labhichchu". A card line is now
written in the reply language with construction words in English; one in script is sent back to the model once.

Guards: a Malayalam reply keeps script lines; a second script line is held as it is (the code then transliterates,
never loses the entry); English and Manglish lines go straight through.
"""

from __future__ import annotations

from typing import Any

from tests.agent_api.standin import ACTOR, BAG, CEMENT, receipt_call, stand_in_api

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, build_tools
from mesiri_ai.fakes import FakeToolCallingProvider

SCRIPT_LINE = "10 ചാക്ക് സിമന്റ് സൈറ്റിൽ ലഭിച്ചു"
MANGLISH_LINE = "10 bags cement, Green Villa"


async def _run(script: list, language: str | None) -> tuple[Any, FakeToolCallingProvider]:  # noqa: ANN401
    app = stand_in_api([])
    client = ApiClient(ACTOR, app=app)
    model = FakeToolCallingProvider(script)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "record_receipt"))
    try:
        return await ApiAgent(model, tools).run(client, "10 ചാക്ക് സിമന്റ് വന്നു", language=language), model
    finally:
        await client.close()


async def test_a_script_line_is_sent_back_once_and_the_manglish_one_is_kept() -> None:
    turn, _ = await _run([[receipt_call(CEMENT, BAG, SCRIPT_LINE)], [receipt_call(CEMENT, BAG, MANGLISH_LINE)],
                          "Ready."], "manglish")
    assert [e.summary for e in turn.pending] == [MANGLISH_LINE]


async def test_guard_a_malayalam_reply_keeps_its_script_line() -> None:
    turn, _ = await _run([[receipt_call(CEMENT, BAG, SCRIPT_LINE)], "Ready."], "malayalam")
    assert [e.summary for e in turn.pending] == [SCRIPT_LINE]


async def test_guard_a_second_script_line_is_held_never_lost() -> None:
    turn, _ = await _run([[receipt_call(CEMENT, BAG, SCRIPT_LINE)], [receipt_call(CEMENT, BAG, SCRIPT_LINE)],
                          "Ready."], "manglish")
    assert [e.summary for e in turn.pending] == [SCRIPT_LINE]


async def test_guard_a_latin_line_goes_straight_through() -> None:
    turn, _ = await _run([[receipt_call(CEMENT, BAG, MANGLISH_LINE)], "Ready."], "manglish")
    assert [e.summary for e in turn.pending] == [MANGLISH_LINE]
