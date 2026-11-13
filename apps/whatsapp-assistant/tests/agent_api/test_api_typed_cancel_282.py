"""WA-282 (live test on Mesiri Test Builders, 13 Nov 2026): a 3-line card with the code's size question open ("1 Numbers
Steel-il ethra Kilograms undu?"). "cancel all" and then "Cancel" each got "Cancel cheythu ... ellaam drop cheythu,
onnum save aayilla" while all three lines stayed waiting: no tool was called. Only the card's Cancel button dropped them.

Root cause: the code answered a typed cancel itself only when nothing was waiting (WA-274); with lines waiting it went
to the model, which said it cancelled and did not. And "cancel all" was not a cancel to the code at all.
Fix: (1) a cancel typed while lines wait does what the card's Cancel does, for the whole list and its open question,
with no model turn; "cancel all / everything / ellam venda" are cancels too. (2) The class: a reply that claims a
cancel or a drop while every entry is still waiting gets one more try, and the claim is taken out if it stays.
Guards: a cancel with nothing waiting still says so (WA-274); a message that only starts with cancel is the model's.
"""

from __future__ import annotations

from tests.agent_api.standin import two_receipts_model
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message, _stand_in_tools  # noqa: F401

from agent_api import whatsapp as wa
from agent_api.reply_guard import claims_cancelled, without_cancel_claims
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.material_direction import is_cancel

#: What the model said, live, with no tool called.
SAID = "Cancel cheythu. Ella entriesum drop cheythu, onnum save aayilla."


async def test_sibling_a_typed_cancel_on_a_plain_list_is_the_same_as_the_button() -> None:
    typed = Harness(two_receipts_model())
    await typed.service.handle(_message(), CTX)
    typed.service._agent._provider = model = FakeToolCallingProvider([SAID])
    await typed.service.handle(_message("cancel all"), CTX)
    tapped = Harness(two_receipts_model())
    await tapped.service.handle(_message(), CTX)
    _save_id, _edit, cancel = tapped.buttons()
    await tapped.service.handle(_message("Cancel", tap=cancel), CTX)
    assert model.calls == 0 and typed.posts() == 0
    assert typed.sent[-1].text == tapped.sent[-1].text
    assert [b.id for b in typed.sent[-1].buttons] == [b.id for b in tapped.sent[-1].buttons]
    # The reason tapped next names what was cancelled, as after the button (WA-146).
    await typed.service.handle(_message("Wrong site", tap=typed.sent[-1].buttons[0].id), CTX)
    about = typed.trace.log_stage.await_args.kwargs["stage_payload"]["calls"][0]["args"]["about"]
    assert "50 bags cement" in about and "wrong site" in about


async def test_guard_after_a_typed_cancel_the_next_update_is_a_new_card() -> None:
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    await h.service.handle(_message("cancel"), CTX)
    h.service._agent._provider = two_receipts_model()
    await h.service.handle(_message(), CTX)
    assert [b.title for b in h.sent[-1].buttons] == ["Save", "✏️ Edit", "Cancel"]


async def test_guard_nothing_waiting_still_says_so_and_cancel_the_order_is_the_models() -> None:
    h = Harness(FakeToolCallingProvider(["-"]))
    await h.service.handle(_message("cancel all"), CTX)
    assert h.sent[-1].text == wa.NOTHING_TO_CANCEL
    model = FakeToolCallingProvider(["Ethu order aanu?"])
    h = Harness(model)
    await h.service.handle(_message("cancel the KK order"), CTX)
    assert model.calls >= 1


def test_the_cancel_words() -> None:
    for yes in ("cancel", "Cancel.", "cancel all", "Cancel everything!", "cancel it", "ellam venda", "ellaam cancel",
                "venda", "വേണ്ട", "എല്ലാം വേണ്ട", "sab cancel", "रद्द"):
        assert is_cancel(yes), yes
    for no in ("cancel the KK order", "cancel 2", "don't cancel", "cancel steel only", "all good", "everything came"):
        assert not is_cancel(no), no


# -- the class: a claimed cancel ---------------------------------------------------------------------------------------

class PerTurn(FakeToolCallingProvider):
    """One script per call of the model: the first answer, then what it does when the code asks again."""

    def __init__(self, *scripts: list) -> None:
        super().__init__(scripts[0])
        self._scripts = list(scripts)

    async def run_tools(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        self._script = list(self._scripts[min(self.calls, len(self._scripts) - 1)])
        return await super().run_tools(*args, **kwargs)


def test_a_cancel_claim_is_read_per_clause() -> None:
    assert claims_cancelled(SAID)
    assert claims_cancelled("Ellaam cancel cheythu, onnum waiting illa.")  # the second live reply
    assert claims_cancelled("Done, I removed the sand line.") and claims_cancelled("Sab hata diya.")
    for no in ("Nothing was cancelled.", "Should I cancel it?", "Tap Cancel to drop them.", "50 bags cement came."):
        assert not claims_cancelled(no), no
    assert without_cancel_claims("Cancel cheythu. Steel ethra kg?") == "Steel ethra kg?"


async def test_the_class_a_model_that_says_dropped_and_drops_nothing_gets_one_more_try() -> None:
    """A cancel the code does not take (it names one line), so the model answers; it claims and calls nothing."""
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    model = PerTurn(["TMT drop cheythu."], [[(wa.DROP_READY, {"numbers": [2]})], "TMT drop cheythu."])
    h.service._agent._provider = model
    await h.service.handle(_message("TMT venda, cement mathi"), CTX)
    assert model.calls == 2  # told it dropped nothing, it dropped the line
    pending = (await h.redis.get_json(h.service._key(CTX)))["pending"]
    assert [p["summary"] for p in pending] == ["50 bags cement, Green Villa"]
    assert "TMT" not in h.sent[-1].text  # the card is drawn again with the cement only


async def test_guard_a_claim_that_stays_false_is_taken_out_of_the_words() -> None:
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    h.service._agent._provider = PerTurn(["TMT drop cheythu. Cement mathi alle?"], ["TMT drop cheythu. Cement mathi alle?"])
    await h.service.handle(_message("TMT venda, cement mathi"), CTX)
    reply = h.sent[-1].text
    assert "drop cheythu" not in reply and "Cement mathi alle?" in reply  # the claim goes, the question stays
    pending = (await h.redis.get_json(h.service._key(CTX)))["pending"]
    assert len(pending) == 2  # nothing was dropped, and nothing says it was
