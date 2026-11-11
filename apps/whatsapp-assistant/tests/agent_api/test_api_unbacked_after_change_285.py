"""[285] (live, 11 Nov 12:57, New India): "Steel ennallathu maattittu TMT steel aakku" changed a card line and the same
reply said "last week (Nov 2 to Nov 8): 42 man-days reported; concrete and masonry going on", with nothing read: the
weekly report had failed a minute before. The [260] check ran only when no tool at all was called, so a turn that
only changed a card line skipped it.

Now every turn that READ nothing is checked. Guards: a figure on the card, or in a tool's own result, or one they
said, stands (no second try).
"""

from __future__ import annotations

from typing import Any

from tests.agent_api.standin import ACTOR
from tests.agent_api.test_api_change_material_285 import SAID, STEEL, _change, _on_steel, _store
from tests.agent_api.test_api_lose_nothing_198 import Runs
from tests.agent_api.test_api_new_material_210b import TOOLS, Store

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, build_tools


async def _turn(store: Store, runs: list[list], text: str, ready: list, history: list) -> tuple[Any, Runs]:
    app = store.api()
    model = Runs(*runs)
    client = ApiClient(ACTOR, app=app)
    try:
        tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in TOOLS))
        return await ApiAgent(model, tools).run(client, text, ready=ready, history=history), model
    finally:
        await client.close()

INVENTED = "Changed. Last week Green Villa-yil 42 man-days reported."
HONEST = "Changed: 30 ton TMT steel."


async def test_the_reported_turn_is_sent_back_once_and_answers_honestly() -> None:
    store = _store()
    ready = await _on_steel(store)
    turn, model = await _turn(store, [[[_change([("quantity", "30")], "30 ton TMT steel")], INVENTED], [HONEST]],
                              "Steel ennallathu maattittu TMT steel aakku", ready=ready, history=SAID)
    assert model.calls == 2 and "(42)" in model.prompts[1]
    assert turn.reply == HONEST
    assert "42" not in (turn.reply or "")


async def test_guard_a_figure_on_the_card_stands() -> None:
    store = _store()
    ready = await _on_steel(store)
    turn, model = await _turn(store, [[[_change([("quantity", "25")], "25 ton Steel")], "Changed to 25 ton."],
                                      ["never reached"]], "25 ton aakku", ready=ready, history=SAID)
    assert model.calls == 1 and turn.reply == "Changed to 25 ton."
    assert [e.body["material_id"] for e in turn.pending] == [STEEL]


async def test_guard_a_figure_they_said_stands_after_a_change() -> None:
    store = _store()
    ready = await _on_steel(store)
    turn, model = await _turn(store, [[[_change([("quantity", "30")], "30 ton Steel")], "Sheri, 2026 November."],
                                      ["never reached"]], "30 ton, 2026 November", ready=ready, history=SAID)
    assert model.calls == 1 and turn.reply == "Sheri, 2026 November."


def test_an_id_never_backs_a_figure() -> None:
    from agent_api.reply_guard import unbacked_figures

    facts = "site Green villa (site_id 48d26efa-915a-45ef-a2da-0283291283f8)"
    assert unbacked_figures("915 bags received", "ethra?", facts) == ["915"]
    assert unbacked_figures("915 bags received", "915 bags vannu", facts) == []
