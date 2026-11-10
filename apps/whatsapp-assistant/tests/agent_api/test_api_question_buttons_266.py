"""WA-266 (reliability plan, step 2; request [278], Aprodac 7 Nov 14:48: a tap on buttons that belonged to another
question dropped a cement request): a question's buttons carried only a number (``apiag:opt:0``), and the tap came
in as its title alone. A short reply is "an answer", so a tap on an EARLIER question's button answered whatever was
open by then, or reached the model as two words with no meaning.

Now every question's buttons name their question. A tap on the open question goes on as the answer, as before; a tap
on an earlier one is answered by the code, changes nothing, and shows what is waiting now.
"""

from __future__ import annotations

from tests.agent_api.standin import BAG, CEMENT, receipt_call
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message, _stand_in_tools  # noqa: F401

from agent_api import whatsapp as wa
from mesiri_ai.fakes import FakeToolCallingProvider

TRADE = ("ask", {"question": "Which trade?", "options": ["Mason", "Helper"]})
SHIFT = ("ask", {"question": "Which shift?", "options": ["Morning", "Evening"]})
#: These chats are Manglish, so the code's line is too (the last test checks the English one).
CLOSED = "Aa chodyam ippo close aayi, athukondu aa utharam njan eduthittilla."


def _options(h: Harness) -> list[str]:
    return [b for b in h.buttons() if b.startswith(wa.OPTION_PREFIX)]


async def _say(h: Harness, text: str, script: list, tap: str | None = None) -> None:
    """One message with the model's script for that turn (the stand-in model plays its whole script every turn)."""
    h.service._agent._provider = FakeToolCallingProvider(script)
    await h.service.handle(_message(text, tap=tap), CTX)


async def _asked(question: tuple) -> Harness:
    h = Harness(FakeToolCallingProvider([[question], question[1]["question"]]))
    await h.service.handle(_message("5 per vannu"), CTX)
    return h


async def test_a_questions_buttons_name_their_question() -> None:
    h = await _asked(TRADE)
    state = await h.service._state(CTX)
    assert state["asked_id"] and _options(h) == [f"apiag:opt:{state['asked_id']}:0", f"apiag:opt:{state['asked_id']}:1"]
    assert [wa.question_of(b) for b in _options(h)] == [state["asked_id"]] * 2


async def test_guard_a_tap_on_the_open_question_is_the_answer_as_before() -> None:
    h = await _asked(TRADE)
    await _say(h, "Mason", ["Sheri, 5 mason."], tap=_options(h)[0])
    assert h.sent[-1].text.startswith("Sheri, 5 mason.")


async def test_guard_a_button_from_before_they_named_a_question_is_still_the_answer() -> None:
    h = await _asked(TRADE)
    assert wa.question_of("apiag:opt:0") is None
    await _say(h, "Mason", ["Sheri, 5 mason."], tap="apiag:opt:0")
    assert h.sent[-1].text.startswith("Sheri, 5 mason.")


async def test_the_reported_tap_on_an_earlier_question_never_answers_the_one_open_now() -> None:
    h = await _asked(TRADE)
    old = _options(h)
    await _say(h, "vere oru karyam: ethu shift ennu chodikku", [[SHIFT], "Which shift?"])  # a new question replaces it
    new = _options(h)
    before = await h.service._state(CTX)
    assert new and new != old
    await _say(h, "Mason", ["THE MODEL MUST NOT BE ASKED"], tap=old[0])
    reply = h.sent[-1]
    assert reply.text.startswith(CLOSED) and "Which shift?" in reply.text  # the open question, again
    assert [b.id for b in reply.buttons] == new and [b.title for b in reply.buttons] == ["Morning", "Evening"]
    assert await h.service._state(CTX) == before  # nothing answered, dropped or saved
    await _say(h, "Morning", ["Sheri, morning shift."], tap=new[0])  # and its own button still answers it
    assert h.sent[-1].text.startswith("Sheri, morning shift.")


async def test_sibling_with_a_list_waiting_the_earlier_tap_shows_the_list_and_save_and_keeps_every_line() -> None:
    line = receipt_call(CEMENT, BAG, "50 bags cement, Green Villa")
    h = await _asked(TRADE)
    old = _options(h)
    await _say(h, "athu vidu. 50 bag cement Green Villa-il vannu", [[line], "Sheri."])  # no question now: a list waits
    assert h.buttons()[0].startswith(wa.SAVE_PREFIX)
    await _say(h, "Helper", ["THE MODEL MUST NOT BE ASKED"], tap=old[1])
    reply = h.sent[-1]
    assert reply.text.startswith(CLOSED) and "1. 50 bags cement, Green Villa" in reply.text
    assert reply.buttons[0].id.startswith(wa.SAVE_PREFIX)
    state = await h.service._state(CTX)
    assert [e["summary"] for e in state["pending"]] == ["50 bags cement, Green Villa"] and h.posts() == 0
    await h.service.handle(_message("Save", tap=reply.buttons[0].id), CTX)  # that Save saves the line
    assert h.posts() == 1


async def test_sibling_with_nothing_waiting_the_earlier_tap_gets_the_one_line_and_no_model_turn() -> None:
    h = await _asked(TRADE)
    old = _options(h)
    await _say(h, "athu venda, njan pinne parayam ketto", ["Sheri."])  # the question is let go
    await _say(h, "Mason", ["THE MODEL MUST NOT BE ASKED"], tap=old[0])
    assert h.sent[-1].text == CLOSED and not h.sent[-1].buttons


async def test_sibling_the_closed_line_is_in_their_language() -> None:
    h = await _asked(TRADE)
    old = _options(h)
    await _say(h, "that one is not needed now, I will tell you later", ["OK."])
    await _say(h, "Mason", ["THE MODEL MUST NOT BE ASKED"], tap=old[0])
    assert h.sent[-1].text == wa.QUESTION_CLOSED
