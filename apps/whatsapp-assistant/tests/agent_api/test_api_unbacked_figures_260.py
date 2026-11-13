"""[260] (5 Nov, 13:02): "how many workers are on site now?" got "10 helpers working" with no tool called: the 10
helpers were only on a card cancelled at 11:01. The next question, "today's total attendance?", looked it up and said
none was recorded. A reply with no tool that gives figures found neither in the person's words nor in the records
the turn started from gets one more try, told to look it up.

Guards: figures they said, figures in today's records, and lines waiting on the list stand; single digits stand.
"""

from __future__ import annotations

from typing import Any

from tests.agent_api.standin import ACTOR, stand_in_api
from tests.agent_api.test_api_lose_nothing_198 import Runs

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.reply_guard import unbacked_figures
from agent_api.tools import build_tools

INVENTED = "Ippol site-il 10 helpers work cheyyunnu."
LOOKED_UP = "Innu attendance onnum record cheythittilla."


async def _run(script: list, text: str, facts: str = "") -> tuple[Any, Runs]:  # noqa: ANN401
    app = stand_in_api([])
    client = ApiClient(ACTOR, app=app)
    model = Runs(*[[step] for step in script])
    try:
        return await ApiAgent(model, build_tools(app.openapi(), ())).run(client, text, facts=facts), model
    finally:
        await client.close()


async def test_the_reported_answer_is_looked_up_instead() -> None:
    turn, model = await _run([INVENTED, LOOKED_UP], "ethra workers ippo site-il work cheyyunnu?")
    assert model.calls == 2 and turn.reply == LOOKED_UP
    assert "(10)" in model.prompts[1] and "cancelled or never saved" in model.prompts[1]


async def test_guard_a_figure_they_said_stands() -> None:
    turn, model = await _run(["Sheri, 25 bags.", "never reached"], "25 bags cement ennu paranjathu sheri aano?")
    assert model.calls == 1 and turn.reply == "Sheri, 25 bags."


async def test_wa283_a_figure_only_in_todays_records_is_looked_up_on_an_answer() -> None:
    """WA-283 (live, 13 Nov) changed this guard: "today's records" in the facts are a partial list (the newest lines),
    and "how much cement came today?" was answered 45 from them when 95 had come. A turn that only answers takes its
    figures from a lookup; the facts no longer back them. (Before WA-283 this figure stood.)"""
    facts = "Today's records:\n- 12:27 30 bags Cement received, Green Villa"
    turn, model = await _run(["Site-il 30 chaakku cement und.", "Site-il 45 chaakku cement und."], "cement ethra und?",
                             facts=facts)
    assert model.calls == 2 and "(30)" in model.prompts[1]


async def test_guard_a_figure_in_todays_records_stands_on_a_turn_that_prepares_something() -> None:
    """The rule for a turn that does something is unchanged: a figure in today's records or on the card stands."""
    from agent_api.agent import SAVE_READY  # noqa: F401 -- the list tools exist; this turn prepares nothing new
    facts = "Today's records:\n- 12:27 30 bags Cement received, Green Villa"
    assert unbacked_figures("Sheri, 30 bags already came today.", "50 bag cement vannu", facts) == []


def test_the_check_itself() -> None:
    assert unbacked_figures("10 helpers work cheyyunnu", "ethra workers?", "") == ["10"]
    assert unbacked_figures("10 helpers", "ethra?", "- 10 helpers, Green Villa") == []
    assert unbacked_figures("3 things are ready", "x", "") == []  # single digits: counting words, list numbers
    assert unbacked_figures("See https://app.x/reports/2026-11-05/sites/1234", "x", "") == []  # links are not figures
    assert unbacked_figures("1,000 kg", "one ton = 1.000?", "") == []
