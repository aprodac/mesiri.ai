"""WA-197 (Ilan, 5 Nov: "should never become a blocker", the class of WA-194): a line whose size nobody knows ("1
load M-sand" when the company counts M-sand in bags) used to stop at a question: the line was not on the list and Save
was not offered until someone answered. Now it is held with " (1 Loads = how many Bags?)" and the size asked beside it; an
answer converts the waiting line, and a Save with no answer holds it for the admin (WA-168's size request), which
saves it by itself when they answer. Never called saved while it waits.
"""

from __future__ import annotations

from tests.agent_api.test_api_stock_unit_165 import (
    CEMENT_LINE,
    LOAD,
    MSAND,
    MSAND_LINE,
    SAID,
    Harness,
    Store,
    _message,
    _save,
    _tools,  # noqa: F401 -- the autouse fixture: the WhatsApp harness builds only these tools
    _turn,
)
from tests.agent_api.test_api_whatsapp_119 import CTX

from agent_api.agent import HELD_FOR_SIZE
from mesiri_ai.fakes import FakeToolCallingProvider


async def test_save_with_no_answer_holds_the_line_and_the_admins_answer_saves_it() -> None:
    store = Store()
    held = await _turn(store, [[CEMENT_LINE, MSAND_LINE], "1 load = ethra chaakku?"], SAID)
    results = await _save(store, held.pending)
    assert [r.status for r in results] == [201, 202] and results[1].body == {HELD_FOR_SIZE: True}
    assert store.received == [("Cement", 4.0)]
    request = store.size_requests[0]
    assert request["material_id"] == MSAND and request["from_unit_id"] == LOAD
    assert request["held_lines"][0]["summary"] == "1 ലോഡ് എംസാൻഡ് Tower A-ൽ എത്തിച്ചു."  # no "= ?" note kept


async def test_save_inside_a_model_turn_says_held_never_saved() -> None:
    store = Store()
    held = await _turn(store, [[MSAND_LINE], "?"], SAID)
    turn = await _turn(store, [[("save_ready_entries", {})], "Ok."], "save", ready=held.pending)
    result = turn.calls[0]["result"]["results"][0]
    assert result["saved"] is False and "admin" in result["held"]


async def test_guard_when_the_hold_fails_the_line_waits_as_before() -> None:
    store = Store()
    app = store.api()
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/materials/size-requests"
                         or "POST" not in getattr(r, "methods", set())]
    store.api = lambda: app  # type: ignore[method-assign]
    held = await _turn(store, [[MSAND_LINE], "?"], SAID)
    results = await _save(store, held.pending)
    assert results[0].status == 422 and store.received == []  # refused, not lost: WA-165 keeps it waiting


async def test_guard_a_line_with_a_known_size_is_never_asked_or_held() -> None:
    store = Store()
    store.one_unit[(MSAND, LOAD)] = 60.0
    turn = await _turn(store, [[MSAND_LINE], "Ready."], SAID)
    assert turn.size_needed == [] and turn.pending[0].summary.endswith("(= 60 Bags)")
    assert all(r.ok and r.status != 202 for r in await _save(store, turn.pending))


async def test_whatsapp_the_size_question_keeps_save_and_the_whole_list() -> None:
    store = Store()
    h = Harness(store, FakeToolCallingProvider([[CEMENT_LINE, MSAND_LINE],
                                                [("ask", {"question": "1 load = ethra chaakku?"})], "Ready."]))
    await h.service.handle(_message(SAID), CTX)
    reply = h.sent[-1]
    assert [b.title for b in reply.buttons][-1] == "Save"
    assert "(1 Loads = how many Bags?)" in reply.text  # the note reaches the card as written (the id cleaner keeps it)
    assert len((await h.state())["pending"]) == 2


async def test_no_unit_said_takes_the_materials_own_unit_and_shows_it() -> None:
    from tests.agent_api.test_api_stock_unit_165 import BAG, CEMENT, _receipt

    store = Store()
    line = _receipt(CEMENT, "cement", BAG, 50, "50 cement")
    del line[1]["unit_id"]
    turn = await _turn(store, [[line], "Ready."], "50 cement vannu")
    assert turn.pending[0].body["unit_id"] == BAG and turn.pending[0].summary == "50 cement · Bags"
    assert all(r.ok for r in await _save(store, turn.pending)) and store.received == [("Cement", 50.0)]


async def test_guard_a_unit_they_said_is_never_replaced() -> None:
    from tests.agent_api.test_api_stock_unit_165 import CEMENT, KG, _receipt

    store = Store()
    turn = await _turn(store, [[_receipt(CEMENT, "cement", KG, 50, "50 kg cement")], "?"], "50 kg cement")
    assert [e.body["unit_id"] for e in turn.pending] == [KG]  # held in kg, its size asked; never turned into bags
    assert turn.pending[0].summary == "50 kg cement (1 Bags = how many Kilograms?)"
