"""PRC-32 (7 Nov, WhatsApp check of the purchase requests, 22:12): "Need 3000 bricks and 10 loads of M sand at Green
Villa by Monday" got "nothing is ready to save, send it again" -- the model called no tool and wrote the Save line.

Root cause: since WA-210 a ready list goes out on its TO SAVE card (the header image) and the text is only the caption
("Ithokke record cheyyaan *Save* amarthuka."). ``for_memory`` kept the list as a note only when the TEXT had it, so the
conversation remembered every card turn as  request -> "tap Save"  and nothing else. The model copied that reply for the
next request instead of preparing it (the 15-token answer of cor_986e7be6), and "athu 250 aakku" had nothing to point to.

Fix: the lines on the card are remembered as the same note the text list had ("(under this reply, waiting for the Save
button: ...)"), whichever way the list went out. Guards: a text list keeps its note as before; a reply with no list is
kept word for word.
"""

from __future__ import annotations

import pytest
from tests.agent_api.standin import STAND_IN_TOOLS, two_receipts_model
from tests.agent_api.test_api_receipts_132 import CTX, Cards, _message, _service

from agent_api import whatsapp as wa
from runtime.agent.wording import say

UPDATE = "50 bag cement, 50 TMT vannu, Main block"


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):  # noqa: ANN001, ANN202 -- as test_api_preview_card_210 does
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


async def _remembered(service) -> list[str]:  # noqa: ANN001
    return [m.text for m in await service._memory.load(CTX) if m.role == "model"]


async def test_a_card_turn_remembers_its_lines_not_only_the_save_caption() -> None:
    service, sent = _service(two_receipts_model(), Cards(preview=True), [])
    await service.handle(_message(UPDATE), CTX)
    assert sent[-1].header_image == b"PREVIEW"  # the list went out on the card
    (kept,) = await _remembered(service)
    assert "(under this reply, waiting for the Save button:" in kept
    assert "cement" in kept.casefold() and "tmt" in kept.casefold()
    # never only the caption: that is the reply the model copied for the next request
    assert kept.strip() not in {wa.PRESS_SAVE, say("api.press_save", "manglish")}


async def test_guard_a_text_list_keeps_its_note_as_before() -> None:
    service, sent = _service(two_receipts_model(), Cards(), [])
    service._receipts = None  # no card: the list is in the text
    await service.handle(_message(UPDATE), CTX)
    assert sent[-1].header_image is None and wa.READY_HEADING in sent[-1].text
    (kept,) = await _remembered(service)
    assert kept.count("(under this reply, waiting for the Save button:") == 1
    assert "*Ready to save:*" not in kept


def test_guard_the_note_is_built_one_way_for_both() -> None:
    assert wa.for_memory("Hello Ravi.") == "Hello Ravi."
    assert wa.for_memory("Hello Ravi.", ["50 bags cement"]) == (
        "Hello Ravi.\n(under this reply, waiting for the Save button: 50 bags cement)")
    # a text list that is also passed is noted once
    sent = "Ok.\n\n*Ready to save:*\n1. 50 bags cement"
    assert wa.for_memory(sent, ["50 bags cement"]) == wa.for_memory(sent)


# PRC-32 (7 Nov 23:06, 23:08: "What is still to come?" / "is PO-0001 late?" -> "I could not get the purchase orders
# right now. Please try again in a minute." with no tool called). One real outage at 19:01; the sentence was then copied
# from the conversation seven times, each copy feeding the next. A "could not / cannot" reply is remembered marked.

OUTAGE = "I could not get the purchase orders right now. Please try again in a minute."


def test_a_could_not_reply_is_read_back_as_a_passing_problem() -> None:
    from agent_api.memory import PASSING_NOTE, _read

    kept = _read("model", OUTAGE, None).text
    assert kept.startswith(PASSING_NOTE) and kept.endswith(OUTAGE)
    issues = "I could not check for open issues right now, so please try again in a minute if it is still open."
    assert _read("model", issues, None).text.startswith(PASSING_NOTE)
    assert _read("user", OUTAGE, None).text == OUTAGE  # only Mesiri's own replies


async def test_a_reply_stored_before_the_fix_is_marked_when_read() -> None:
    from agent_api.memory import PASSING_NOTE

    service, _ = _service(two_receipts_model(), Cards(), [])
    await service._memory.remember(CTX, "What is still to come?", OUTAGE)  # stored as it was, unmarked
    (kept,) = await _remembered(service)
    assert kept.startswith(PASSING_NOTE) and kept.endswith(OUTAGE)


def test_guard_ordinary_answers_and_other_peoples_could_not_are_read_word_for_word() -> None:
    from agent_api.memory import _read

    for said in ("asus aanu Green Villa-yile Steel order cheythathu.", "The supplier could not come today.",
                 "Could you send the bill photo?"):
        assert _read("model", said, None).text == said
