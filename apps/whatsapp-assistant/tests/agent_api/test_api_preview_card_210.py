"""WA-210 (Ilan, 5 Nov: "before saving itself you get the image card, and you save after that; make sure edit and
delete are there"): a ready list goes out as its TO SAVE card, the header image of the Save / Edit / Cancel message.
The text drops the lines the card shows (less to read, fewer words to write); Edit offers 🗑️ Remove for one line;
after a Save of a previewed list the reply is "✅ Saved." with its links and no second (SAVED) card.

Guards: no builder, a failed or slow drawing, and lines with no card keep today's text list; a Save of a list that was
never previewed keeps the full Saved text and the SAVED card.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from tests.agent_api.standin import STAND_IN_TOOLS, two_receipts_model
from tests.agent_api.test_api_receipts_132 import CTX, Cards, _message, _service

from agent_api import whatsapp as wa
from agent_api.agent import PendingWrite
from agent_api.receipts import preview_card, slip_for
from channel.whatsapp.outbound import WhatsAppSender
from runtime.agent.wording import say

UPDATE = "50 bag cement, 50 TMT vannu, Main block"


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):  # noqa: ANN001, ANN202 -- as test_api_whatsapp_119 does
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


async def _previewed() -> tuple[Any, list, Cards, list]:
    cards, order = Cards(preview=True), []
    service, sent = _service(two_receipts_model(), cards, order)
    await service.handle(_message(UPDATE), CTX)
    return service, sent, cards, order


# -- the preview --------------------------------------------------------------------------------------------------


async def test_a_ready_list_goes_out_on_its_to_save_card_with_save_edit_cancel() -> None:
    _service_, sent, cards, _ = await _previewed()
    reply = sent[-1]
    assert reply.header_image == b"PREVIEW"
    assert [b.title for b in reply.buttons] == ["Save", wa.EDIT_TITLE, "Cancel"]
    (slip,) = cards.previews
    assert [(ln.number, ln.title, ln.quantity) for ln in slip.lines] == [(1, "Cement", "50"), (2, "TMT bar", "50")]
    assert slip.site == "Main block"


async def test_the_text_no_longer_repeats_the_lines_or_says_tap_save() -> None:
    _service_, sent, _, _ = await _previewed()
    text = sent[-1].text
    assert wa.READY_HEADING not in text
    assert "50 bags cement" not in text.split("\n", 1)[-1] or text.count("50 bags cement") <= 1
    assert say("api.press_save", "manglish") not in text and wa.PRESS_SAVE not in text
    assert text.strip()  # WhatsApp needs a body under the image


async def test_no_builder_keeps_the_text_list() -> None:
    order: list = []
    service, sent = _service(two_receipts_model(), Cards(), order)
    service._receipts = None
    await service.handle(_message(UPDATE), CTX)
    assert sent[-1].header_image is None and wa.READY_HEADING in sent[-1].text


async def test_a_card_that_cannot_be_drawn_keeps_the_text_list() -> None:
    order: list = []
    cards = Cards(preview=False)
    service, sent = _service(two_receipts_model(), cards, order)
    await service.handle(_message(UPDATE), CTX)
    assert cards.previews and sent[-1].header_image is None and wa.READY_HEADING in sent[-1].text


async def test_a_slow_card_never_holds_the_reply(monkeypatch) -> None:  # noqa: ANN001
    class Slow(Cards):
        async def build_slip(self, slip: Any) -> bytes:  # noqa: ANN401
            await asyncio.sleep(1)
            return b"LATE"

    monkeypatch.setattr(wa, "PREVIEW_SECONDS", 0.05)
    order: list = []
    service, sent = _service(two_receipts_model(), Slow(), order)
    started = time.monotonic()
    await service.handle(_message(UPDATE), CTX)
    assert time.monotonic() - started < 0.9
    assert sent[-1].header_image is None and wa.READY_HEADING in sent[-1].text


def test_the_slip_carries_every_line_so_the_text_keeps_none() -> None:
    entries = [
        PendingWrite("add_material", "POST", "/materials", {}, {"name": "Wash Basin"}, "Add Wash Basin", "k1"),
        PendingWrite("record_receipt", "POST", "/materials/inflows", {}, {}, "20 nos Wash Basin, Green Villa", "k2"),
    ]
    text = "\n\n".join(["Ithaa.", f"{wa.READY_HEADING}\n1. Add Wash Basin\n2. 20 nos Wash Basin, Green Villa",
                        wa.PRESS_SAVE])
    assert wa.without_listed_lines(text, entries, "english") == "Ithaa."
    slip = slip_for(entries, CTX, ({}, {}))
    assert [(ln.number, ln.kind, ln.title, ln.new) for ln in slip.lines] == [
        (1, "list", "Wash Basin", True), (2, "material", "Material", False)]


def test_slip_rows_in_plain_words() -> None:
    def entry(tool: str, body: dict) -> PendingWrite:
        return PendingWrite(tool, "POST", "/x", {}, body, "x", "k")

    lines = slip_for([
        entry("record_attendance", {"lines": [{"trade": "helper", "headcount": 10}]}),
        entry("record_attendance", {"lines": [{"trade": "mason", "headcount": 6}, {"trade": "helper", "headcount": 4}]}),
        entry("record_work", {"work_type": "Plastering", "narrative": "2nd floor"}),
        entry("record_expense", {"amount": 1250.5, "description": "Tea and snacks", "vendor_text": "Chai Point"}),
        entry("report_issue", {"narrative": "Water tank leak", "severity": "CRITICAL"}),
    ], CTX, ({}, {})).lines
    assert [(ln.title, ln.note, ln.quantity) for ln in lines] == [
        ("Helpers", "at work", "10"), ("Workers", "Mason 6 · Helper 4", "10"), ("Plastering", "2nd floor", ""),
        ("Tea and snacks", "Chai Point", "₹1,250.5"), ("Water tank leak", "Critical issue", "")]


def test_the_slip_html_says_draft_and_has_no_record_number() -> None:
    from channel.receipt.draft_slip import Slip, SlipLine, render_slip_html

    html = render_slip_html(Slip("Green Villa", "5 Nov, 2:43 pm", [SlipLine(1, "material", "<Cement>", "came", "30",
                                                                             "bags", new=True)]))
    assert "DRAFT · NOT SAVED" in html and "&lt;Cement&gt;" in html and ">NEW<" in html and "1 line<" in html
    many = render_slip_html(Slip("x", "y", [SlipLine(i, "work", f"w{i}") for i in range(1, 12)]))
    assert "+4 more on the list" in many and ">w7<" in many and ">w8<" not in many


async def test_a_material_being_added_in_the_same_list_is_named_on_the_card() -> None:
    cards = Cards(preview=True)
    entry = PendingWrite("record_receipt", "POST", "/materials/inflows", {},
                         {"material_id": "new:GI roofing sheet", "quantity": 5, "project_id": None, "site_id": None},
                         "5 GI roofing sheets", "k1")

    class Client:
        async def call(self, method: str, path: str, **kw: Any) -> Any:  # noqa: ANN401
            from types import SimpleNamespace

            return SimpleNamespace(ok=True, body={"items": []})

    assert await preview_card(cards, [entry], CTX, Client(), "cor_x") == b"PREVIEW"
    (slip,) = cards.previews
    assert slip.lines[0].title == "GI roofing sheet" and slip.lines[0].new is True


# -- Save after the preview --------------------------------------------------------------------------------------


async def test_save_after_the_preview_says_saved_once_and_sends_no_second_card() -> None:
    service, sent, cards, order = await _previewed()
    order.clear()
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    assert order == ["text"] and cards.asked == []  # no SAVED card: they saw the card before Save
    text = sent[-1].text
    assert text.startswith(say("api.saved_short", "manglish"))
    assert "50 bags cement" not in text  # the card showed the lines; the reply doesn't list them again


async def test_save_of_a_list_never_previewed_keeps_the_full_text_and_the_saved_card() -> None:
    order: list = []
    cards = Cards(preview=False)
    service, sent = _service(two_receipts_model(), cards, order)
    await service.handle(_message(UPDATE), CTX)
    order.clear()
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    assert order[0] == "text" and order[1][0] == "image" and cards.asked
    assert "50 bags cement" in sent[-2 if sent[-1].header_image else -1].text


# -- Remove (delete one line) ------------------------------------------------------------------------------------


async def _edit_first_line(service: Any, sent: list) -> str:
    edit = sent[-1].buttons[1].id
    batch = edit.split(":", 2)[2]
    await service.handle(_message("1", tap=f"{wa.EDIT_LINE_PREFIX}{batch}:1"), CTX)
    return batch


async def test_the_edit_question_offers_remove_and_cancel() -> None:
    service, sent, _, _ = await _previewed()
    batch = await _edit_first_line(service, sent)
    assert [b.title for b in sent[-1].buttons] == [wa.REMOVE_TITLE, "Cancel"]
    assert sent[-1].buttons[0].id == f"{wa.REMOVE_PREFIX}{batch}:1"
    assert all(len(b.title) <= 20 for b in sent[-1].buttons)


async def test_remove_takes_off_only_that_line_and_shows_the_rest_on_a_new_card() -> None:
    service, sent, cards, _ = await _previewed()
    old = await _edit_first_line(service, sent)
    await service.handle(_message("Remove", tap=sent[-1].buttons[0].id), CTX)
    reply = sent[-1]
    assert reply.text.startswith(say("api.removed", "manglish", item="50 bags cement, Main block").split("*")[0])
    assert reply.header_image == b"PREVIEW" and len(cards.previews[-1].lines) == 1
    save = reply.buttons[0].id
    assert save.startswith(wa.SAVE_PREFIX) and not save.endswith(old)  # a new list: the old buttons no longer act


async def test_removing_the_last_line_leaves_nothing_waiting() -> None:
    service, sent, _, _ = await _previewed()
    await _edit_first_line(service, sent)
    await service.handle(_message("Remove", tap=sent[-1].buttons[0].id), CTX)
    await _edit_first_line(service, sent)
    await service.handle(_message("Remove", tap=sent[-1].buttons[0].id), CTX)
    assert not sent[-1].buttons
    state = await service._state(CTX)
    assert not state.get("pending") and not state.get("batch")


async def test_a_remove_tap_on_an_old_list_does_nothing() -> None:
    service, sent, _, _ = await _previewed()
    await service.handle(_message("Remove", tap=f"{wa.REMOVE_PREFIX}oldbatch:1"), CTX)
    assert sent[-1].text == wa.NOTHING_WAITING
    assert len((await service._state(CTX))["pending"]) == 2


# -- "typing..." after the ✅ ------------------------------------------------------------------------------------


class _Http:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    async def post(self, url: str, json: dict, headers: dict) -> Any:  # noqa: A002, ANN401
        from types import SimpleNamespace

        self.posts.append(json)
        return SimpleNamespace(status_code=200, text="", json=lambda: {"messages": [{"id": "wamid.out"}]})


def _sender() -> tuple[WhatsAppSender, _Http]:
    http = _Http()
    return WhatsAppSender(client=http, access_token="t", phone_number_id="p"), http  # type: ignore[arg-type]


async def test_typing_comes_back_after_the_reaction() -> None:
    sender, http = _sender()
    since = time.monotonic()
    await sender.send_reaction("9198", "wamid.in")
    assert await sender.keep_typing("9198", "wamid.in", since) is True
    assert http.posts[-1] == {"messaging_product": "whatsapp", "status": "read", "message_id": "wamid.in",
                              "typing_indicator": {"type": "text"}}


async def test_typing_never_comes_back_once_the_reply_went() -> None:
    sender, http = _sender()
    since = time.monotonic()
    await sender.send_text("9198", "Saved.")
    posts = len(http.posts)
    assert await sender.keep_typing("9198", "wamid.in", since) is False
    assert len(http.posts) == posts
    assert await sender.keep_typing("9199", "wamid.other", since) is True  # someone else's chat is unaffected


async def test_the_journey_shows_typing_again_right_after_the_tick(monkeypatch) -> None:  # noqa: ANN001
    """The real journey: the ✅ reaction, then "typing..." again on the same message, while the reply is worked on."""
    from tests.unit.test_reply_composer import _build, _saved_attendance
    from tests.unit.test_reply_composer import _message as _journey_message

    on_normalized, deps, _choices, _setup = _build(monkeypatch)
    deps["interaction_handler"].handle_fast_path.return_value = _saved_attendance()
    await on_normalized(_journey_message(), {})
    sender = deps["sender"]
    sender.send_reaction.assert_awaited_once_with("919876543210", "wamid.in.1", "✅")
    wa_id, message_id, since = sender.keep_typing.await_args.args
    assert (wa_id, message_id) == ("919876543210", "wamid.in.1") and isinstance(since, float)
    names = [c[0] for c in sender.mock_calls]
    assert names.index("send_reaction") < names.index("keep_typing")


async def test_the_keeper_stops_when_the_reply_has_gone(monkeypatch) -> None:  # noqa: ANN001
    import runtime.message_journey as mj

    monkeypatch.setattr(mj, "TYPING_REFRESH_S", 0.01)
    from tests.unit.test_reply_composer import _build, _saved_attendance
    from tests.unit.test_reply_composer import _message as _journey_message

    on_normalized, deps, _choices, _setup = _build(monkeypatch)
    answers = iter([True, True, False])
    deps["sender"].keep_typing.side_effect = lambda *a: next(answers)
    deps["interaction_handler"].handle_fast_path.return_value = _saved_attendance()
    original = deps["sender"].send_button.side_effect

    async def slow_reply(*a, **kw):  # noqa: ANN002, ANN003, ANN202 -- a turn long enough for three refreshes
        await asyncio.sleep(0.1)
        return original(*a, **kw) if original else True

    deps["sender"].send_button.side_effect = slow_reply
    await on_normalized(_journey_message(), {})
    assert deps["sender"].keep_typing.await_count == 3  # True, True, then False: stopped, never again


# -- WA-214: every card type says TO SAVE before Save ------------------------------------------------------------


@pytest.mark.parametrize("tool", sorted(__import__("agent_api.receipts", fromlist=["CARD_TYPES"]).CARD_TYPES))
def test_every_card_type_says_to_save_before_save_and_saved_after(tool: str) -> None:
    import datetime as dt

    from tests.agent_api.test_api_receipts_132 import BODIES, _entry
    from tests.agent_api.test_api_receipts_132 import CTX as CARD_CTX

    from agent_api.receipts import _pair
    from channel.receipt.builder import RecordReceiptBuilder
    from channel.receipt.data import STATUS_DRAFT, STATUS_SAVED

    pair = _pair(_entry(tool, BODIES[tool]).pending, "preview", CARD_CTX, ({}, {}), "cor_x")
    assert pair is not None
    now = dt.datetime.now(dt.UTC)
    assert RecordReceiptBuilder._data(pair[0], pair[1], CARD_CTX, now, False).status == STATUS_DRAFT
    assert RecordReceiptBuilder._data(pair[0], pair[1], CARD_CTX, now, True).status == STATUS_SAVED
