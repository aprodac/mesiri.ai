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

from agent_api.agent import ApiAgent
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
    for said in ("nos", "ennam", "എണ്ണം", "numbers"):
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


async def test_replay_of_the_conversation_the_units_reach_the_model_and_save_works() -> None:
    """Ilan, 2 Nov: "50 bags of cement vennitund and 10 tmt steel bar use aki" -> Save."""
    model = FakeToolCallingProvider([
        [receipt_call(CEMENT, "bags", "50 bags cement received"), receipt_call(TMT, "nos", "10 TMT used")],
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
