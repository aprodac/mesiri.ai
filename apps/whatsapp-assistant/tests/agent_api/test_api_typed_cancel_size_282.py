"""WA-282, the reported case (live, 13 Nov 2026): a card with the code's size question open, and a typed cancel. See
test_api_typed_cancel_282.py for the root cause and the class."""

from __future__ import annotations

import pytest
from tests.agent_api.test_api_size_direction_232 import ADMIN, TmtStore, _started, _tools  # noqa: F401
from tests.agent_api.test_api_whatsapp_119 import _message

from agent_api import whatsapp as wa
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.wording import say

SAID = "Cancel cheythu. Ella entriesum drop cheythu, onnum save aayilla."


@pytest.mark.parametrize("typed", ["cancel all", "Cancel", "cancel everything", "ellam venda", "venda"])
async def test_the_reported_cancel_with_a_size_question_open_drops_everything_with_no_model_turn(typed) -> None:
    store = TmtStore()
    h = await _started(store)
    assert "size_needed" in await h.state() and (await h.state())["pending"]  # the reported state: lines + a question
    model = FakeToolCallingProvider([SAID])
    h.service._agent._provider = model
    await h.service.handle(_message(typed), ADMIN)
    state = await h.state()
    assert model.calls == 0  # the code did it
    assert not state.get("pending") and not state.get("size_needed") and not state.get("asked")
    reply = h.sent[-1]
    assert reply.text == say("api.cancelled_why", "manglish")  # the card's own Cancel reply, with the reasons
    assert [b.id for b in reply.buttons] == [f"{wa.WHY_PREFIX}{code}" for code in wa.CANCEL_REASONS]
    assert store.received == []  # nothing saved
