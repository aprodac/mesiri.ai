"""WA-268 (reliability plan, step 4; requests [272] [273], Ilan, 6 Nov 13:44-13:47: to "how many bags in one cubic
metre of M-sand?" he answered by voice "I don't know, M-sand would be in cubic metres" and got the same question
again; only the exact words of the "🤷 Don't know" button were taken).

Root cause: "don't know" was recognised by the code only as the button's own title; any other wording went to the
model, which had no way to say "they don't know" and so asked again or dropped the line.
Fix: while a size question is open the model has one call for it (``size_not_known``); the code then answers exactly
as it does for the button (save in the unit said when the material has no stock yet, else hold the line), with no
word list. Each test walks the journey and asserts what is offered, held or saved.
"""

from __future__ import annotations

from tests.agent_api.test_api_size_direction_232 import (
    ADMIN,
    ENGINEER,
    NOS,
    TMT_LOAD,
    TmtStore,
    _message,  # noqa: F401
    _save,
    _say,
    _started,
    _tools,  # noqa: F401 -- the autouse fixture
)

from agent_api.agent import SIZE_NOT_KNOWN

NOT_KNOWN = [[(SIZE_NOT_KNOWN, {})], "Ariyillenkil oru load-il ethra bar undennu supplier-odu chodikku."]
SPOKEN = "enikku ariyilla, athu supplier-odu chodikkanam ennu thonnunnu"


OPEN_NOTE = "A size you asked is still open"


async def test_the_model_is_told_of_the_call_only_while_a_size_question_is_open() -> None:
    h = await _started(TmtStore())
    await _say(h, SPOKEN, NOT_KNOWN)
    prompt = h.service._agent._provider.last_system_prompt
    assert OPEN_NOTE in prompt and "1 Loads TMT Steel Bars = how many Numbers?" in prompt


async def test_the_reported_dont_know_in_their_own_words_gets_the_way_out_the_button_gives() -> None:
    store = TmtStore()
    h = await _started(store)
    reply = await _say(h, SPOKEN, NOT_KNOWN)
    assert [b.title for b in reply.buttons][:2] == ["Size parayam", "30 nos aayi save"]
    assert "supplier-odu chodikku" not in reply.text  # the code's words, not the model's
    state = await h.state()
    assert "size_needed" in state and [p["body"]["quantity"] for p in state["pending"]] == [30]  # the line is kept
    await _say(h, "30 nos aayi save", [], tap=reply.buttons[1].id)
    await _save(h)
    assert store.received == [("TMT Steel Bars", 30.0)]
    assert next(m for m in store.catalog if m["id"] == TMT_LOAD)["default_unit_id"] == NOS


async def test_sibling_the_same_words_and_the_button_give_the_same_reply() -> None:
    spoken = await _say(await _started(TmtStore()), SPOKEN, NOT_KNOWN)
    tapped = await _say(await _started(TmtStore()), "🤷 Ariyilla", [], tap="apiag:opt:0")
    assert spoken.text == tapped.text and [b.title for b in spoken.buttons] == [b.title for b in tapped.buttons]


async def test_sibling_a_material_with_stock_is_held_for_the_admin_when_an_engineer_does_not_know() -> None:
    store = TmtStore()
    store.unmoved.discard(TMT_LOAD)
    h = await _started(store, ENGINEER)
    reply = await _say(h, SPOKEN, NOT_KNOWN, ENGINEER)
    assert "admin-nodu chodichittundu" in reply.text and len(store.size_requests) == 1
    assert store.size_requests[0]["held_lines"][0]["body"]["quantity"] == 30  # nothing lost


async def test_sibling_an_admin_who_does_not_know_is_not_told_their_admin_was_asked() -> None:
    store = TmtStore()
    store.unmoved.discard(TMT_LOAD)
    h = await _started(store, ADMIN)
    reply = await _say(h, SPOKEN, NOT_KNOWN, ADMIN)
    assert "admin-nodu" not in reply.text and len(store.size_requests) == 1


async def test_guard_a_number_is_still_the_answer_and_the_model_is_not_offered_the_call() -> None:
    store = TmtStore()
    h = await _started(store)
    await _say(h, "oru load-il 200 bar undakum", ["Ready."])
    assert OPEN_NOTE not in h.service._agent._provider.last_system_prompt  # the code took the size: none is open
    await _save(h)
    assert store.received and "size_needed" not in await h.state()


async def test_guard_with_no_size_question_open_the_call_is_not_offered_and_changes_nothing() -> None:
    from tests.agent_api.test_api_stock_unit_165 import Harness

    from mesiri_ai.fakes import FakeToolCallingProvider

    h = Harness(TmtStore(), FakeToolCallingProvider(["Hello."]))
    await h.hold(language="manglish")
    await _say(h, "namaskaram", ["Namaskaram."])
    assert OPEN_NOTE not in h.service._agent._provider.last_system_prompt
    assert h.sent[-1].text.startswith("Namaskaram.") and not (await h.state()).get("pending")
