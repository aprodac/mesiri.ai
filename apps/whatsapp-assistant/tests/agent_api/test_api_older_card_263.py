"""WA-263 (Aprodac 8 Nov 02:02:20 and 02:05:41; Ilan: "sometimes when you click save it says there is nothing to save"):
every reply gives the waiting list a new card, and a Save on the message before the newest one said "There is nothing
waiting to save" while its lines WERE still waiting (the next tap, on the newest card, saved them). A Cancel on a done
card also got "nothing waiting to save" (test company, 3 Nov), and a "tap *Save*" line could go out with no button.

Now an older card's Save / Cancel acts on its own lines that are still waiting, and leaves the newer card working for
the rest; a card that is really done says what may have happened; "tap *Save*" always has its button.
"""

from __future__ import annotations

from tests.agent_api.standin import BAG, CEMENT, receipt_call, two_receipts_model
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message, _stand_in_tools  # noqa: F401

from agent_api import whatsapp as wa
from channel.replies import ListRow, ReplySpec
from mesiri_ai.fakes import FakeToolCallingProvider


async def _two_cards(second_model: FakeToolCallingProvider) -> tuple[Harness, str, list[str]]:
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    old_save = h.buttons()[0]
    h.service._agent._provider = second_model
    await h.service.handle(_message("ok"), CTX)
    return h, old_save, h.buttons()


async def test_the_reported_save_on_the_previous_card_saves_its_lines() -> None:
    h, old_save, new = await _two_cards(FakeToolCallingProvider(["Sheri."]))
    assert new[0].startswith(wa.SAVE_PREFIX) and new[0] != old_save  # the list was drawn again, on a new card
    await h.service.handle(_message("Save", tap=old_save), CTX)
    assert h.posts() == 2 and wa.NOTHING_WAITING not in h.sent[-1].text
    assert h.sent[-1].text.startswith("Saved.")


async def test_sibling_the_older_card_saves_only_its_own_lines_and_the_newer_card_still_works() -> None:
    third = receipt_call(CEMENT, BAG, "20 bags cement, Green Villa")
    third[1]["quantity"] = 20
    h, old_save, new = await _two_cards(FakeToolCallingProvider([[third], "Sheri."]))
    await h.service.handle(_message("Save", tap=old_save), CTX)
    assert h.posts() == 2  # the two lines that card showed
    state = await h.service._state(CTX)
    assert [e["summary"] for e in state["pending"]] == ["20 bags cement, Green Villa"]
    await h.service.handle(_message("Save", tap=new[0]), CTX)  # the newer card's button still acts
    assert h.posts() == 3


async def test_sibling_cancel_on_the_older_card_cancels_only_its_lines() -> None:
    third = receipt_call(CEMENT, BAG, "20 bags cement, Green Villa")
    third[1]["quantity"] = 20
    h, _old, new = await _two_cards(FakeToolCallingProvider([[third], "Sheri."]))
    first_cancel = [b for b in (await _first_card_buttons(h)) if b.startswith(wa.CANCEL_PREFIX)][0]
    await h.service.handle(_message("Cancel", tap=first_cancel), CTX)
    state = await h.service._state(CTX)
    assert [e["summary"] for e in state["pending"]] == ["20 bags cement, Green Villa"] and h.posts() == 0
    await h.service.handle(_message("Save", tap=new[0]), CTX)
    assert h.posts() == 1


async def _first_card_buttons(h: Harness) -> list[str]:
    return [b.id for b in h.sent[0].buttons or ()]


async def test_guard_a_card_really_done_says_so_and_a_cancel_never_says_save() -> None:
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    save, _edit, cancel = h.buttons()
    await h.service.handle(_message("Save", tap=save), CTX)
    await h.service.handle(_message("Save", tap="apiag:save:gone1234"), CTX)
    from runtime.agent.wording import say

    assert h.sent[-1].text == say("api.nothing_on_card", "manglish") and h.posts() == 2  # in their language
    assert "nothing waiting to save" not in h.sent[-1].text
    await h.service.handle(_message("Cancel", tap="apiag:cancel:gone1234"), CTX)
    assert h.sent[-1].text == say("api.nothing_to_cancel", "manglish")


def test_a_tap_save_line_always_has_its_button() -> None:
    state = {"batch": "b1", "pending": [{"tool": "record_receipt", "method": "POST", "path": "/x", "params": {},
                                         "body": {}, "summary": "x", "idempotency_key": "k1"}]}
    bare = wa.with_save_button(ReplySpec(text="Ithokke record cheyyaan *Save* amarthuka."), state)
    assert [b.id for b in bare.buttons] == ["apiag:save:b1", "apiag:edit:b1", "apiag:cancel:b1"]
    asked = wa.with_save_button(ReplySpec(text="Which one? Then *Save*.", buttons=(ListRow(id="o1", title="A"),)), state)
    assert [b.id for b in asked.buttons] == ["o1", "apiag:save:b1"]


def test_guard_nothing_waiting_the_save_line_comes_out_and_other_replies_are_untouched() -> None:
    out = wa.with_save_button(ReplySpec(text="Sheri.\nIthokke record cheyyaan *Save* amarthuka."), {})
    assert out.text == "Sheri." and not out.buttons
    plain = ReplySpec(text="Saved. 🔗 link")
    assert wa.with_save_button(plain, {}) is plain
