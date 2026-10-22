"""Request 83: the four 22 Oct live messages through the real journey, the
model scripted the way the live one answered (floor left inside work_type,
status missing); what is checked is the To-save card the sender reads."""

from __future__ import annotations

from tests.replay.test_agent_replay import world  # noqa: F401  (fixture)

from mesiri_ai.fakes import FakeToolCallingProvider


def _lines(result):  # noqa: ANN001
    return result.reply.text.split("\n")


async def test_work_progress_keeps_floor_and_status(world):  # noqa: F811
    provider = FakeToolCallingProvider(
        [
            [
                ("save_work_done", {"narrative": "3rd floor slab concreting finished", "work_type": "slab concreting"}),
                ("save_work_done", {"narrative": "2nd floor plastering 70%", "work_type": "plastering", "progress_percent": 70}),
            ],
            "Got it, 3rd floor slab concreting finished, 2nd floor plastering 70%. Check it and tap Save.",
        ]
    )
    result = await world.say(provider, "3rd floor slab concreting finished, 2nd floor plastering 70%")
    lines = _lines(result)
    assert "• Slab concreting, 3rd floor (completed)" in lines
    assert "• Plastering, 2nd floor: 70%" in lines
    assert provider.calls == 1


async def test_the_floor_and_finished_the_model_did_give_are_kept(world):  # noqa: F811
    provider = FakeToolCallingProvider(
        [
            [("save_work_done", {"narrative": "slab concreting finished", "work_type": "slab concreting",
                                 "location": "3rd floor", "update_kind": "completed"})],
            "Ok, slab concreting theernnu. Shariyenkil Save tap cheyyu.",
        ]
    )
    result = await world.say(provider, "3rd floor slab concreting finished")
    assert "✅ Saved: Slab concreting, 3rd floor (completed)" in _lines(result)


async def test_mixed_message_card_plus_one_draft_line(world):  # noqa: F811
    provider = FakeToolCallingProvider(
        [
            [
                ("save_labour", {"workers": [{"trade": "mason", "headcount": 6}]}),
                ("save_material_usage", {"material": "cement", "quantity": 25, "unit": "bags"}),
                ("report_issue", {"issue_type": "MATERIAL_SHORTAGE", "narrative": "steel venam"}),
                ("request_dpr", {}),
            ],
            "Sheri, 6 mason, 25 bag cement, steel venam. Nokki Save tap cheyyu.",
        ]
    )
    result = await world.say(provider, "6 mason vannu, 25 bag cement use cheythu, nale steel venam. innathe report ayakku")
    text = result.reply.text
    assert text.count("6 workers (6 mason)") == 1 and text.count("Cement used: 25 bags") == 1
    assert text.count("Today's draft so far:") <= 1
    assert "Work details" not in text
