"""WA-193: basics 3 and 9 held by code. A reply never says saved when nothing saved; never shows an id or an API error.

Each has the failure, its siblings (languages, states) and the guards that must not change."""

from __future__ import annotations

import pytest
from tests.agent_api.standin import (
    ACTOR,
    BAG,
    CEMENT,
    TMT,
    receipt_call,
    stand_in_api,
    stand_in_tools,
)
from tests.agent_api.test_api_agent_124 import CTX, _message, _service

from agent_api import whatsapp as wa
from agent_api.agent import SAVE_READY, ApiAgent
from agent_api.client import ApiClient
from agent_api.reply_guard import claims_saved, without_ids, without_internals, without_saved_claims
from agent_api.tools import ALLOWED
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.wording import say

UUID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
LINE = "50 bags cement, Main block"
NAMES = {"record_receipt", "list_projects", "list_sites", "search_materials", "list_units"}


@pytest.fixture(autouse=True)
def _tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda o: real(o, tuple(a for a in ALLOWED if a.name in NAMES)))


@pytest.mark.parametrize("words", [
    "Saved ✅", "50 bags cement recorded.", "Added to your records.", "njan record cheythu", "save cheythu",
    "stock mein daal diya", "save kar diya", "സേവ് ചെയ്തു", "രേഖപ്പെടുത്തി", "सेव कर दिया", "दर्ज हो गया",
    # WA-195 (users' feedback, 3 Nov 19:07): "noted" with no tool called, and its siblings.
    "I have noted the information about the electrician's increased rate.", "Noted.", "Stored it for you.",
    "I've made a note of the rate.", "I kept a record of it.", "rate note cheythu", "njan kurichu vechittundu",
    "ezhuthi vechu", "rate note kar liya", "കുറിച്ചുവച്ചു", "नोट कर लिया",
])
def test_a_claim_in_any_language_is_seen(words: str) -> None:
    assert claims_saved(words)


@pytest.mark.parametrize("words", [
    "Nothing saved yet.", "It isn't saved yet.", "Not saved.", "It will be saved when you tap.", "Ready to be saved.",
    "You saved this an hour ago.", "Already saved at 10:00.", "Was it saved?", "save cheythittilla",
    "രേഖപ്പെടുത്തിയിട്ടില്ല", "सेव नहीं किया", "50 bags cement is ready", "Slab work done",
    # WA-195 guards: noted as a question / not yet / a change on the ready list / a note they are asked for.
    "Noted, which site?", "I haven't noted it anywhere.", "It will be noted once you tap Save.",
    "Updated the cement to 10 bags.", "Please send a note of the rate.", "note cheythittilla",
])
def test_what_is_no_claim_stays(words: str) -> None:
    assert not claims_saved(words)
    assert without_saved_claims(words) == words


def test_only_the_claim_is_cut() -> None:
    assert without_saved_claims("50 bag cement vannu, save cheythu.") == "50 bag cement vannu."
    assert without_saved_claims("Saved. Anything else?") == "Anything else?"


async def test_a_prepared_entry_called_saved_is_still_only_ready() -> None:
    model = FakeToolCallingProvider([[receipt_call(CEMENT, BAG, LINE)], "50 bags cement saved."])
    service, sent = _service(model)
    await service.handle(_message("50 bag cement vannu"), CTX)
    reply = sent[-1]
    assert "saved." not in reply.text.casefold().split("ready to save")[0]
    assert LINE in reply.text and [b.title for b in reply.buttons] == ["Save", "Cancel"]


async def test_saved_with_no_tool_gets_one_more_try_and_the_entry_is_prepared() -> None:
    call = receipt_call(CEMENT, BAG, LINE)
    model = FakeToolCallingProvider([lambda _: "Saved ✅" if model.calls == 1 else [call], "50 bags cement is ready."])
    service, sent = _service(model)
    await service.handle(_message("50 bags cement came"), CTX)
    assert model.calls == 2
    assert LINE in sent[-1].text and sent[-1].buttons


async def test_saved_with_no_tool_twice_says_nothing_is_ready() -> None:
    model = FakeToolCallingProvider(["Saved ✅"])
    service, sent = _service(model)
    await service.handle(_message("50 bags cement came"), CTX)
    assert sent[-1].text == say("api.nothing_held", "english") and not sent[-1].buttons


async def test_a_look_up_answer_about_an_earlier_record_stays() -> None:
    answer = "Ravi saved 50 bags cement this morning."
    first = "Ravi saved 50 bags cement."
    model = FakeToolCallingProvider([lambda _: first if model.calls == 1 else [("list_units", {})], answer])
    service, sent = _service(model)
    await service.handle(_message("did anyone report cement"), CTX)
    assert answer in sent[-1].text


async def _waiting(app) -> list:
    client = ApiClient(ACTOR, app=app)
    try:
        model = FakeToolCallingProvider([[receipt_call(CEMENT, BAG, LINE)], "ready"])
        return (await ApiAgent(model, stand_in_tools(app)).run(client, "50 bag cement")).pending
    finally:
        await client.close()


async def test_a_real_save_may_say_saved() -> None:
    app = stand_in_api([])
    ready = await _waiting(app)
    client = ApiClient(ACTOR, app=app)
    try:
        model = FakeToolCallingProvider([[(SAVE_READY, {})], "Saved ✅"])
        turn = await ApiAgent(model, stand_in_tools(app)).run(client, "save", ready=ready)
    finally:
        await client.close()
    assert turn.reply == "Saved ✅" and not turn.reply_fixed


async def test_a_refused_save_may_not_say_saved() -> None:
    app = stand_in_api([], refuse_tmt=True)
    client = ApiClient(ACTOR, app=app)
    try:
        held = FakeToolCallingProvider([[receipt_call(TMT, BAG, "10 TMT")], "ready"])
        ready = (await ApiAgent(held, stand_in_tools(app)).run(client, "10 TMT")).pending
        model = FakeToolCallingProvider([[(SAVE_READY, {})], "All saved."])
        turn = await ApiAgent(model, stand_in_tools(app)).run(client, "save", ready=ready)
    finally:
        await client.close()
    assert not any(r.ok for r in turn.saved) and turn.saved
    assert "saved" not in turn.reply.casefold() and "saved" in turn.reply_fixed


@pytest.mark.parametrize("words,clean", [
    (f"Cement (id: {UUID}) is on the list.", "Cement is on the list."),
    (f"Cement `{UUID}` is on the list.", "Cement is on the list."),
    (f"material_id={UUID}", ""),
    ("Add new:Primer to the list?", "Add Primer to the list?"),
    ("Trace cor_bd6fd016803c42de is logged.", "Trace is logged."),
    ("Could not save. unit_id is not a valid active unit", "Could not save."),
    ("Error 422 Unprocessable Entity", ""),
    ('{"detail": "Not found"}', ""),
])
def test_ids_and_api_errors_are_taken_out(words: str, clean: str) -> None:
    assert without_internals(words) == clean


@pytest.mark.parametrize("words", [
    f"Open it: https://app.mesiri.ai/sites/{UUID}/day",
    "422 bags cement came, tower 12.",
    "Ref 8fa51b",
    "Good morning Ravi!",
])
def test_links_and_real_numbers_stay(words: str) -> None:
    assert without_internals(words) == words


async def test_an_id_in_the_reply_and_on_the_card_never_reaches_the_person() -> None:
    call = receipt_call(CEMENT, BAG, f"50 bags {UUID}")
    model = FakeToolCallingProvider([[call], f"Cement ({UUID}) is ready."])
    service, sent = _service(model)
    await service.handle(_message("50 bag cement vannu"), CTX)
    assert UUID not in sent[-1].text


def test_without_ids_keeps_plain_words() -> None:
    assert without_ids(LINE) == LINE


async def test_noted_with_no_tool_is_cut_and_the_waiting_card_stays() -> None:
    """WA-195 (users' feedback, 3 Nov 19:07): a card was waiting; "he now wants 1300" got "I have noted the
    information about his increased rate." with no tool called. Nothing was kept, so the claim goes; the card stays."""
    app = stand_in_api([])
    ready = await _waiting(app)
    noted = "I have noted the information about the electrician's increased rate. One entry is ready for you."
    client = ApiClient(ACTOR, app=app)
    try:
        model = FakeToolCallingProvider([noted, noted])
        turn = await ApiAgent(model, stand_in_tools(app)).run(client, "electrician ini 1300 venam ennu", ready=ready)
    finally:
        await client.close()
    assert model.calls == 2  # one more try, as for "saved"
    assert "noted" not in turn.reply.casefold() and "One entry is ready for you." in turn.reply
    assert "saved" in turn.reply_fixed
    assert [e.summary for e in turn.pending] == [e.summary for e in ready]
