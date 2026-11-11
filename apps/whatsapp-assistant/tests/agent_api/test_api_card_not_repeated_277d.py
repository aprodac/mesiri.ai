"""WA-277 step D (live, New India, 11 Nov 2026 12:56 to 12:59): four replies in a row began with the same three card
lines, the last one above a stock answer. Mechanism: every reply with a list waiting drew the whole list again (text
and picture), whatever the reply was about.

Now an answer given while the SAME list waits ends with one short line ("3 still waiting ...") over the same Save /
Edit / Cancel buttons; the list is neither written nor drawn again.

Siblings: any language (the line is the code's, in five languages); a report send; a turn that only looked something
up. Guards: a list that changed is listed in full; a question with options keeps its card; a bare "OK." over the
list is the full list (nothing else was said); the buttons still save.
"""

from __future__ import annotations

from tests.agent_api.standin import BAG, CEMENT, receipt_call, two_receipts_model
from tests.agent_api.test_api_whatsapp_119 import (  # noqa: F401
    CTX,
    Harness,
    _message,
    _stand_in_tools,
)

from agent_api import whatsapp as wa
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.wording import LINES

LINE_1, LINE_2 = "50 bags cement, Green Villa", "50 TMT bars, Green Villa"


async def _with_card() -> Harness:
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    assert LINE_1 in h.sent[-1].text
    return h


async def _then(h: Harness, script: list, words: str = "stock ethra und?") -> str:
    h.service._agent._provider = FakeToolCallingProvider(script)
    await h.service.handle(_message(words), CTX)
    return h.sent[-1].text


async def test_the_reported_answer_over_a_waiting_list_does_not_repeat_it() -> None:
    h = await _with_card()
    text = await _then(h, ["Green Villa-il 322 bags cement stock und."])
    assert "322 bags cement stock" in text
    assert LINE_1 not in text and LINE_2 not in text and wa.READY_HEADING not in text
    assert LINES["api.still_waiting"]["manglish"].format(count="2") in text  # in the language of their message
    assert [b.title for b in h.sent[-1].buttons] == ["Save", "✏️ Edit", "Cancel"]


async def test_the_buttons_under_the_short_line_still_save_the_list() -> None:
    h = await _with_card()
    await _then(h, ["Green Villa-il 322 bags cement stock und."])
    await h.service.handle(_message(None, tap=h.buttons()[0]), CTX)
    assert h.posts() == 2  # both lines of the list above were saved


async def test_sibling_several_answers_in_a_row_never_repeat_it() -> None:
    h = await _with_card()
    for answer in ("Nale mazha undaakum.", "Site B-il 4 mason.", "Report 9 pm-inu pokum."):
        text = await _then(h, [answer])
        assert answer in text and LINE_1 not in text and "⏳ 2 " in text and "*Save*" in text


async def test_sibling_the_line_is_the_codes_in_every_language() -> None:
    assert set(LINES["api.still_waiting"]) == {"english", "manglish", "malayalam", "hindi", "hinglish"}
    for line in LINES["api.still_waiting"].values():
        assert "{count}" in line and "*Save*" in line  # with_save_button keeps the Save button under it
    assert LINES["api.still_waiting"]["english"] == wa.STILL_WAITING


async def test_guard_a_list_that_changed_is_listed_in_full() -> None:
    h = await _with_card()
    text = await _then(h, [[receipt_call(CEMENT, BAG, "30 bags cement, Green Villa")], "Ready."],
                       "30 bag cement koodi vannu")
    assert LINE_1 in text and "30 bags cement, Green Villa" in text and "⏳" not in text


async def test_guard_a_question_with_options_keeps_the_list() -> None:
    h = await _with_card()
    text = await _then(h, [[("ask", {"question": "Ethu site?", "options": ["Green Villa", "Site B"]})], "Ethu site?"])
    assert LINE_1 in text and "⏳" not in text


async def test_guard_a_bare_ok_over_the_list_is_the_full_list() -> None:
    h = await _with_card()
    text = await _then(h, ["OK."], "hmm")
    assert LINE_1 in text and LINE_2 in text and "⏳" not in text


async def test_guard_a_reply_that_only_copies_the_list_is_the_full_list() -> None:
    h = await _with_card()
    text = await _then(h, [f"1. {LINE_1}\n2. {LINE_2}"], "enthokkeya ullathu?")
    assert LINE_1 in text and wa.READY_HEADING in text
