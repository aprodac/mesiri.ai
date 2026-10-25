"""Request 115: a reply over a Save / Cancel card that is still waiting never
says "Saved" or offers UNDO for it, and the card image drawn after the Save
tap says SAVED. Live 25 Oct: "plastering 50 sq ft done today" answered
"✅ Saved: Plastering, today: 50 sq ft (completed) ... Wrong? Reply UNDO."
above the "To save" card."""

from __future__ import annotations

import pytest
from tests.replay.test_agent_replay import world, world_two_sites  # noqa: F401  (fixtures)
from tests.replay.test_request114_progress_card import _OpenPlastering
from tests.unit.test_receipt_builder import ACTOR, MATERIAL, _Renderer, _saved

from channel.receipt.builder import RecordReceiptBuilder
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.draft_action import DraftActionType

WORK = {
    "narrative": "plastering 50 sq ft done today", "work_type": "plastering", "location": "today",
    "quantities": [{"work_type": "plastering", "quantity": 50, "unit": "sq ft"}], "update_kind": "completed",
    "continues": "plastering",
}
CARD = "📝 To save: Plastering, today: 50 sq ft (completed)"


@pytest.mark.parametrize(
    "model_text",
    [
        "Ok.\n\n✅ Saved: Plastering, today: 50 sq ft (completed)\n\nWrong? Reply UNDO.",
        "Ok. ✅ Saved: Plastering, today: 50 sq ft (completed). Wrong? Reply UNDO.",
        "Ok, check it.\n✅ Saved:\n• Plastering, today: 50 sq ft (completed)\nWrong? Reply UNDO.",
    ],
)
async def test_a_pending_card_is_never_called_saved(world_two_sites, model_text):  # noqa: F811
    world = world_two_sites  # noqa: F811
    world.site = {"activity_query": _OpenPlastering()}
    result = await world.say(FakeToolCallingProvider([[("save_work_done", WORK)], model_text]), "plastering 50 sq ft done today")

    reply = result.reply
    assert CARD in reply.text
    assert [b.title for b in reply.buttons] == ["✅ Save", "❌ Cancel"]
    low = reply.text.casefold()
    assert "saved" not in low and "undo" not in low and "wrong?" not in low
    assert world.dispatcher.dispatched == []


async def test_a_written_entry_beside_a_pending_card_keeps_its_own_saved_line(world_two_sites):  # noqa: F811
    world = world_two_sites  # noqa: F811
    world.site = {"activity_query": _OpenPlastering()}
    provider = FakeToolCallingProvider(
        [
            [("save_labour", {"workers": [{"trade": "mason", "headcount": 3}]}), ("save_work_done", WORK)],
            "Ok.\n\n✅ Saved: Plastering, today: 50 sq ft (completed)",
        ]
    )
    reply = (await world.say(provider, "3 masons and plastering 50 sq ft done today")).reply

    saved_part, _, card_part = reply.text.partition(CARD)
    assert "✅ Saved: 3 workers (3 mason)" in saved_part  # really written
    assert "plastering" not in saved_part.casefold()  # the pending one is not
    assert card_part.strip() == ""


async def test_the_card_after_the_save_tap_says_saved():
    renderer = _Renderer()
    progress = (DraftActionType.ADD_PROGRESS_UPDATE, {"work_type": "plastering", "update_kind": "COMPLETED", "quantities": [{"quantity": 50, "unit": "sq ft"}]})
    await RecordReceiptBuilder(renderer).build(*_saved(*progress, "aaaa-1"), ACTOR)
    await RecordReceiptBuilder(renderer).build(*_saved(*progress, "aaaa-1"), ACTOR, saved=True)
    await RecordReceiptBuilder(renderer).build(*_saved(*MATERIAL, "bbbb-2"), ACTOR, saved=True)
    before, after, material = renderer.html
    assert "TO SAVE" in before and "Tap Save to keep it" in before
    assert "SAVED" in after and "TO SAVE" not in after and "Tap Save to keep it" not in after
    assert "TO SAVE" not in material and "Tap Save to keep it" not in material


async def test_tapping_save_on_the_work_card_asks_for_the_saved_card(world):  # noqa: F811
    calls = []

    class _Spy:
        async def build(self, confirmed, execution, actor, **kwargs):  # noqa: ANN001, ANN202
            calls.append(kwargs)
            return b"png"

    world.handler._receipt_builder = _Spy()
    world.site = {"activity_query": _OpenPlastering()}
    await world.say(FakeToolCallingProvider([[("save_work_done", WORK)], "Ok."]), "plastering 50 sq ft done today")
    handled = await world.handler.handle_fast_path(world.actor.user_id, world.message("✅ Save"))
    assert await handled.receipt_coro == b"png"
    assert calls == [{"saved": True}]
