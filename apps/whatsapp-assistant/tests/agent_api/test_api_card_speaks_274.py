"""WA-274 (live run on the test company, 10 Nov 2026, the first conversation on gemini-3.5-flash-lite):

1. "Site B-il scaffolding loose aanu, danger aanu" was held right, and the line above the card said "safety issue aayi
   report cheythu" (reported) for an issue that was only held; the leak after it got the same. The model's words above
   a card it has just changed are talk about the card, so the card alone goes out (reliability plan, step 3).
2. A bare "cancel" with nothing waiting got the day's cement stock and the project count ([285], 7 Nov: the updates
   after such a cancel were swallowed). The code can tell from the words and the state, so the code answers.
"""

from __future__ import annotations

from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import BAG, CEMENT, receipt_call, two_receipts_model
from tests.agent_api.test_api_whatsapp_119 import (  # noqa: F401
    CTX,
    Harness,
    _message,
    _stand_in_tools,
)

from agent_api import whatsapp as wa
from mesiri_ai.fakes import FakeToolCallingProvider

CLAIM = "Cement Green Villa-il vannathu report cheythu."


def _one_receipt(words: str) -> FakeToolCallingProvider:
    return FakeToolCallingProvider([[receipt_call(CEMENT, BAG, "30 bags cement, Green Villa")], words])


async def test_the_reported_claim_above_a_held_card_is_not_sent() -> None:
    h = Harness(_one_receipt(CLAIM))
    await h.service.handle(_message("30 bag cement vannu"), CTX)
    text = h.sent[-1].text
    assert "report cheythu" not in text and "30 bags cement, Green Villa" in text
    assert h.buttons()[0].startswith(wa.SAVE_PREFIX) and h.posts() == 0  # held, with its Save, nothing saved


async def test_sibling_saved_and_ready_talk_in_other_languages_goes_the_same_way() -> None:
    for words in ("Saved the cement.", "सीमेंट दर्ज कर दिया।", "സിമന്റ് സേവ് ചെയ്തു.", "Ellam ready aanu 👍"):
        h = Harness(_one_receipt(words))
        await h.service.handle(_message("30 bag cement vannu"), CTX)
        assert words not in h.sent[-1].text and "30 bags cement, Green Villa" in h.sent[-1].text


async def test_guard_a_question_above_the_card_is_kept() -> None:
    h = Harness(_one_receipt("Steel ethra kg aanu?"))
    await h.service.handle(_message("30 bag cement vannu, steel um"), CTX)
    assert "Steel ethra kg aanu?" in h.sent[-1].text


async def test_guard_an_answer_while_a_card_waits_unchanged_is_kept() -> None:
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    h.service._agent._provider = FakeToolCallingProvider(["Nale mazha undaakum ennu kelkkunnu."])
    await h.service.handle(_message("nale mazha undo"), CTX)
    assert "Nale mazha undaakum" in h.sent[-1].text  # the list did not change: the words are the answer


def test_guard_words_after_a_lookup_are_the_answer() -> None:
    class Turn:
        pending, saved, options, question, not_held = [object()], [], [], "", []

    tools = _real_tools()
    read, write = "stock_summary", "record_receipt"
    assert not tools[read].is_write and tools[write].is_write
    said = "Stock 322 bags aanu."
    assert wa.card_speaks(Turn, [{"tool": write}], said, unchanged=False, tools=tools)
    assert not wa.card_speaks(Turn, [{"tool": write}, {"tool": read}], said, unchanged=False, tools=tools)
    assert not wa.card_speaks(Turn, [{"tool": write}, {"tool": "tell_the_team"}], said, unchanged=False, tools=tools)
    assert wa.card_speaks(Turn, [{"tool": wa.CHANGE_READY}], said, unchanged=False, tools=tools)


async def test_the_reported_bare_cancel_with_nothing_waiting_is_answered_by_the_code() -> None:
    model = FakeToolCallingProvider(["Green Villa-il 322 bags cement stock und."])
    h = Harness(model)
    await h.service.handle(_message("cancel"), CTX)
    assert h.sent[-1].text == wa.NOTHING_TO_CANCEL and model.calls == 0  # no model turn


async def test_sibling_venda_and_malayalam_are_the_same() -> None:
    for word in ("venda", "വേണ്ട", "Cancel."):
        model = FakeToolCallingProvider(["x"])
        h = Harness(model)
        await h.service.handle(_message(word), CTX)
        assert h.sent[-1].text == wa.NOTHING_TO_CANCEL and model.calls == 0


async def test_guard_a_cancel_with_a_list_waiting_is_never_nothing_to_cancel() -> None:
    """WA-282 changed who does it: the code drops the list (the card's own Cancel), no model turn. What this guard
    holds is unchanged: with a list waiting, "cancel" is never answered "nothing to cancel"."""
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    model = FakeToolCallingProvider([[(wa.DROP_READY, {})], "Cancel cheythu."])
    h.service._agent._provider = model
    await h.service.handle(_message("cancel"), CTX)
    assert h.sent[-1].text != wa.NOTHING_TO_CANCEL and model.calls == 0


async def test_guard_a_message_that_only_starts_with_cancel_goes_to_the_model() -> None:
    model = FakeToolCallingProvider(["Ethu order aanu?"])
    h = Harness(model)
    await h.service.handle(_message("cancel the KK order"), CTX)
    assert model.calls >= 1 and h.sent[-1].text != wa.NOTHING_TO_CANCEL
