"""WA-256 / WA-259 (Ilan's own chat, Aprodac, 8 Nov 02:02-02:05).

Six replies said "... ready aanu" with no tool called, so nothing was on the list ("There is a leak in the water tank
... Please save that" -> "Water tank leak Main block site-il oru issue aayitt ready aanu." -> Save -> "There is
nothing waiting to save."; "I need 50 bags of cement here" -> "... 50 bags Cement venam ennu ready aanu." twice, the
person swore). And the draft slip of a material request showed the model's Manglish sentence.

Now "ready" is the code's word: the model saying it with nothing prepared gets one corrective try, and if still nothing
is held the code says what is true. The slip and the text under it are structured (English, from the entry's fields),
then one human line in the person's language.
"""

from __future__ import annotations

from tests.agent_api.standin import ACTOR, PROJECT, SITE, stand_in_api, stand_in_tools

from agent_api.agent import ApiAgent, PendingWrite
from agent_api.client import ApiClient
from agent_api.receipts import caption_lines, slip_for
from agent_api.reply_guard import claims_ready, without_ready_claims
from agent_api.whatsapp import with_structured
from mesiri_ai.fakes import FakeToolCallingProvider

LEAK = "Water tank leak Main block site-il oru issue aayitt ready aanu."
CEMENT_READY = "Main block site-lekku 50 bags Cement venam ennu ready aanu."
CEMENT_ID, BAGS = "c0000000-0000-0000-0000-000000000001", "b0000000-0000-0000-0000-000000000001"
ISSUE = "d0000000-0000-0000-0000-000000000001"


async def _run(script: list, text: str, ready: list | None = None):  # noqa: ANN202
    model = FakeToolCallingProvider(script)
    app = stand_in_api([])
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(model, stand_in_tools(app)).run(client, text, ready=ready)
    finally:
        await client.close()
    return turn, model


async def test_the_reported_ready_with_nothing_prepared_is_never_sent() -> None:
    turn, model = await _run([LEAK, LEAK], "There is a leak in the water tank here. That is an issue. Please save that.")
    assert model.calls == 2  # one corrective try, told nothing is on the list
    assert "nothing is in the list" in model.last_messages[-1].text
    assert "ready" not in turn.reply.casefold() and turn.nothing_held  # the code says what is true instead


async def test_sibling_a_question_after_the_ready_keeps_the_question() -> None:
    turn, _ = await _run([CEMENT_READY + " Ethu divasam venam?"], "I need 50 bags of cement here")
    assert "ready" not in turn.reply.casefold() and "Ethu divasam venam?" in turn.reply


async def test_guard_a_list_already_waiting_is_ready_no_corrective_try() -> None:
    waiting = [PendingWrite(tool="record_receipt", method="POST", path="/materials/inflows", params={},
                            body={"project_id": PROJECT, "site_id": SITE, "material_id": CEMENT_ID, "quantity": 30,
                                  "unit_id": BAGS}, summary="30 bags Cement vannu", idempotency_key="k1")]
    turn, model = await _run(["Cement list-il ready aanu."], "ok", ready=waiting)
    assert model.calls == 1 and [e.idempotency_key for e in turn.pending] == ["k1"]


def test_guard_the_words_ready_as_a_question_or_negation_are_not_a_claim() -> None:
    assert claims_ready(LEAK) and claims_ready("5 kg Steel Main block-il upayogichath ready aanu.")
    assert not claims_ready("Is it ready?") and not claims_ready("Nothing is ready yet.")
    assert without_ready_claims("Sorry, athu njaan sheriyaakkam. 6 nos Steel ready aanu.") == "Sorry, athu njaan sheriyaakkam."


def _ctx():  # noqa: ANN202
    from types import SimpleNamespace

    return SimpleNamespace(sites=[SimpleNamespace(id=SITE, name="Main block")], projects=[], timezone="Asia/Kolkata")


def test_the_reported_material_request_slip_is_structured_not_the_models_sentence() -> None:
    entry = PendingWrite(tool="ask_for_material", method="POST", path="/procurement/requests", params={},
                         body={"project_id": PROJECT, "site_id": SITE, "material_id": CEMENT_ID, "quantity": 50,
                               "unit_id": BAGS, "source": "whatsapp"},
                         summary="50 bags Cement Main block-lekku venam", idempotency_key="r1")
    slip = slip_for([entry], _ctx(), ({CEMENT_ID: "Cement"}, {BAGS: "bags"}))
    (line,) = slip.lines
    assert (line.title, line.quantity, line.unit) == ("Cement", "50", "bags")
    assert line.kind == "request" and line.note == "Main block" and "venam" not in line.note


def test_siblings_close_issue_and_order_are_structured_too() -> None:
    close = PendingWrite(tool="resolve_issue", method="POST", path=f"/progress/issues/{ISSUE}/resolve", params={},
                         body={"resolution_notes": "fixed"}, summary="Water tank leak fix cheyyan", idempotency_key="i1")
    order = PendingWrite(tool="place_order", method="POST", path="/procurement/orders", params={},
                         body={"project_id": PROJECT, "site_id": SITE, "supplier": "ABC Traders",
                               "material_id": CEMENT_ID, "quantity": 100, "unit_id": BAGS, "rate": 380},
                         summary="ABC Traders-inu order", idempotency_key="o1")
    slip = slip_for([close, order], _ctx(), ({CEMENT_ID: "Cement"}, {BAGS: "bags"}),
                    targets={ISSUE: "Water tank leak"})
    first, second = slip.lines
    assert (first.title, first.kind, first.note) == ("Water tank leak", "issue_close", "fixed")
    assert (second.title, second.kind) == ("Cement", "order")
    assert second.note == "ABC Traders · ₹380 each · Main block"
    assert "cheyyan" not in first.note and "order" not in second.title


def test_the_text_under_the_slip_is_structured_then_one_human_line() -> None:
    entry = PendingWrite(tool="ask_for_material", method="POST", path="/procurement/requests", params={},
                         body={"project_id": PROJECT, "site_id": SITE, "material_id": CEMENT_ID, "quantity": 50,
                               "unit_id": BAGS}, summary="x", idempotency_key="r1")
    lines = caption_lines(slip_for([entry], _ctx(), ({CEMENT_ID: "Cement"}, {BAGS: "bags"})))
    text = with_structured(lines, "Ithu sheri aanenkil *Save* amarthuka.")
    assert text == "1. 📝 Request: *Cement* · Main block · 50 bags\n\nIthu sheri aanenkil *Save* amarthuka."


def test_guard_a_long_list_fits_whatsapps_limit_and_keeps_the_human_line() -> None:
    text = with_structured([f"{i}. *Cement* · Material request · Main block · {i} bags" for i in range(1, 60)], "Sheri?")
    assert len(text) <= 1024 and text.endswith("Sheri?") and "more on the card" in text
