"""Request 203: the API agent's material lines settle a real unit id; a refusal is plain words.

Production: every material line failed with "unit_id is not a valid active unit". The units
route answers ``{"items": [...]}`` and the facts read only a bare list, so the model was given
no unit ids and wrote "bags" / invented ids. Now the words are matched in code (the shared
unit-word table), an unknown unit goes back to the model to ask, and a refusal never shows
the API's validation text.
"""

from __future__ import annotations

from tests.agent_api.standin import (
    ACTOR,
    BAG,
    CEMENT,
    NOS,
    TMT,
    receipt_call,
    stand_in_api,
    stand_in_tools,
)
from tests.agent_api.test_api_whatsapp_119 import (
    CTX,
    Harness,
    _message,
    _stand_in_tools,  # noqa: F401
)

from agent_api.agent import ApiAgent, PendingWrite
from agent_api.client import ApiClient
from agent_api.units import plain_refusal, resolve_unit, unit_rows
from mesiri_ai.fakes import FakeToolCallingProvider

UNITS = unit_rows({"items": [
    {"id": BAG, "code": "bag", "display_name": "Bags", "is_active": True},
    {"id": NOS, "code": "nos", "display_name": "Numbers", "is_active": True},
]})


def test_units_read_from_the_items_answer_and_from_a_list() -> None:
    assert len(UNITS) == 2 and len(unit_rows(UNITS)) == 2
    assert unit_rows({"items": [{"id": "x", "is_active": False}]}) == []


def test_the_words_sites_use_name_the_org_unit() -> None:
    for said in ("bags", "Bag", "chaakku", "ചാക്ക്", BAG, "Bags"):
        assert resolve_unit(UNITS, said)["id"] == BAG, said
    for said in ("nos", "ennam", "എണ്ണം", "numbers", "bars", "rod", "pcs"):
        assert resolve_unit(UNITS, said)["id"] == NOS, said
    assert resolve_unit(UNITS, "furlongs") is None and resolve_unit(UNITS, "") is None


async def _run(call, app=None):  # noqa: ANN001, ANN202
    app = app or stand_in_api([])
    model = FakeToolCallingProvider([[call], "Ready."])
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(model, stand_in_tools(app)).run(client, "50 bags cement vannu")
    finally:
        await client.close()


async def test_a_unit_word_becomes_the_units_id_before_the_entry_is_held() -> None:
    turn = await _run(receipt_call(CEMENT, "bags", "50 bags cement"))
    assert [e.body["unit_id"] for e in turn.pending] == [BAG]


async def test_a_made_up_unit_id_is_replaced_never_sent() -> None:
    turn = await _run(receipt_call(TMT, "nos", "10 TMT"))
    assert turn.pending[0].body["unit_id"] == NOS


async def test_an_unknown_unit_goes_back_to_the_model_to_ask_not_into_the_list() -> None:
    turn = await _run(receipt_call(CEMENT, "furlongs", "50 furlongs cement"))
    assert turn.pending == []
    assert "not one of the company's units" in turn.calls[0]["result"]["error"]
    assert "bag" in turn.calls[0]["result"]["error"]


async def test_an_entry_held_with_the_word_is_fixed_when_saved() -> None:
    from agent_api.agent import PendingWrite, confirm
    from agent_api.client import new_idempotency_key

    app = stand_in_api([])
    body = receipt_call(CEMENT, "bags", "x")[1]
    body = {k: v for k, v in body.items() if k != "confirm_line"}
    entry = PendingWrite("record_receipt", "POST", "/materials/inflows", {}, body, "50 bags cement",
                         new_idempotency_key())
    client = ApiClient(ACTOR, app=app)
    try:
        results = await confirm(client, [entry])
    finally:
        await client.close()
    assert results[0].ok


def test_a_refusal_is_plain_words_in_their_language() -> None:
    raw = "unit_id is not a valid active unit"
    assert "unit_id" not in plain_refusal(raw, "english") and "unit" in plain_refusal(raw, "english")
    assert "Ethu unit" in plain_refusal(raw, "manglish")
    assert "യൂണിറ്റ്" in plain_refusal(raw, "malayalam")
    assert "material_id" not in plain_refusal("material_id is not a valid active catalog entry", "english")
    assert plain_refusal("Not authorized for this site", "english") == "Not authorized for this site"


def _ten(call: tuple[str, dict]) -> tuple[str, dict]:
    return (call[0], {**call[1], "quantity": 10})  # [229]: the number they said (50 cement, 10 TMT) stays with its item


async def test_replay_of_the_conversation_the_units_reach_the_model_and_save_works() -> None:
    """Ilan, 2 Nov: "50 bags of cement vennitund and 10 tmt steel bar use aki" -> Save."""
    model = FakeToolCallingProvider([
        [receipt_call(CEMENT, "bags", "50 bags cement received"), _ten(receipt_call(TMT, "nos", "10 TMT used"))],
        "Ready.",
    ])
    h = Harness(model)
    await h.service.handle(_message("50 bags of cement vennitund and 10 tmt steel bar use aki"), CTX)
    assert f"bag ({BAG})" in model.last_system_prompt  # the units reached the model's facts
    await h.service.handle(_message("Save", tap=h.buttons()[0]), CTX)
    assert h.sent[-1].text.startswith("Saved.") and "❌" not in h.sent[-1].text and h.posts() == 2


async def test_a_refusal_the_person_sees_is_never_the_validation_text() -> None:
    from agent_api.agent import PendingWrite, WriteResult
    from agent_api.whatsapp import _saved_text

    entry = PendingWrite("record_receipt", "POST", "/x", {}, {}, "50 bags cement", "k")
    text = _saved_text([WriteResult(entry, 422, {"detail": "unit_id is not a valid active unit"})], "manglish")
    assert "unit_id" not in text and "Ethu unit" in text and text.startswith("Not everything")


def test_a_copied_ready_block_in_the_models_words_is_not_printed_twice() -> None:
    from agent_api.whatsapp import without_ready_block

    block = "Done.\n\n*Ready to save:*\n1. 50 bags cement received"
    assert without_ready_block(block) == "Done."
    assert without_ready_block("Cement is ready.") == "Cement is ready."


def _entry(tool: str) -> PendingWrite:
    return PendingWrite(tool=tool, method="POST", path="/x", params={}, body={}, summary=tool, idempotency_key=tool)


def test_a_save_tap_never_sends_a_dpr_nobody_asked_for() -> None:
    """Production 2 Nov: a Save tap listed "today's DPR PDF" as saved beside material lines."""
    from agent_api.whatsapp import _without_stale_sends, dropping_stale_sends

    mixed = [_entry("record_receipt"), _entry("send_dpr")]
    assert [e.tool for e in _without_stale_sends(mixed)] == ["record_receipt"]
    assert [e.tool for e in _without_stale_sends([_entry("send_dpr")])] == ["send_dpr"]
    assert [e.tool for e in dropping_stale_sends(mixed)] == ["record_receipt"]


async def _hold(h, summary: str, unit: str) -> None:  # noqa: ANN001
    """Put one waiting receipt in the state, as an earlier turn would have (a unit the code cannot settle)."""
    from tests.agent_api.standin import ORG, PROJECT, SITE, USER

    entry = PendingWrite("record_receipt", "POST", "/materials/inflows", {},
                         {"material_id": TMT, "quantity": 10, "unit_id": unit, "site_id": SITE,
                          "project_id": PROJECT, "occurred_date": "2026-11-02"}, summary, "k1")
    await h.redis.set_json(f"agent_api:{ORG}:{USER}", {"pending": [entry.to_json()], "batch": "b1",
                                                      "pending_at": __import__("time").time()})


async def test_a_held_line_with_an_unsettled_unit_takes_it_from_its_words() -> None:
    """Ilan 2 Nov 21:45: "10 TMT steel bars" sat for hours; its words say bars -> nos."""
    h = Harness(FakeToolCallingProvider(["Ok."]))
    await _hold(h, "10 TMT steel bars used", "steel")
    await h.service.handle(_message("Save", tap="apiag:save:b1"), CTX)
    assert h.sent[-1].text.startswith("Saved.") and h.posts() == 1


async def test_a_held_line_nobody_can_settle_leaves_the_list_with_plain_words() -> None:
    from tests.agent_api.standin import ORG, USER

    h = Harness(FakeToolCallingProvider(["Ok."]))
    await _hold(h, "10 TMT used", "steel")
    await h.service.handle(_message("Save", tap="apiag:save:b1"), CTX)
    text = h.sent[-1].text
    assert "unit_id" not in text and h.posts() == 0 and not h.sent[-1].buttons
    state = await h.redis.get_json(f"agent_api:{ORG}:{USER}")
    assert state["pending"] == []  # it does not ride along on the next card


async def test_a_list_nobody_saved_for_hours_is_dropped_on_the_next_message() -> None:
    import time

    from tests.agent_api.standin import ORG, USER

    h = Harness(FakeToolCallingProvider(["Hello."]))
    await _hold(h, "10 TMT used", "steel")
    state = await h.redis.get_json(f"agent_api:{ORG}:{USER}")
    state["pending_at"] = time.time() - 5 * 3600
    await h.redis.set_json(f"agent_api:{ORG}:{USER}", state)
    await h.service.handle(_message("hi"), CTX)
    assert "10 TMT used" not in (h.model_system() if hasattr(h, "model_system") else "")
    assert (await h.redis.get_json(f"agent_api:{ORG}:{USER}"))["pending"] == []
