"""The offline rows of docs/qa/CONVERSATION_SCORECARD.md (request 57, A1).

The model is scripted; the journey, canonicalization, gates, workflows and the
reply composer are real. What is checked is what the worker reads and what was
written -- the scorecard's 0/1/2 for each message.
"""

from __future__ import annotations

from tests.replay.test_agent_replay import world  # noqa: F401  (fixture)

from mesiri_ai.fakes import FakeToolCallingProvider


async def test_scorecard_1_labour_manglish(world):  # noqa: F811
    provider = FakeToolCallingProvider(
        [
            [("save_labour", {"workers": [{"trade": "mason", "headcount": 6}, {"trade": "helper", "headcount": 10}]})],
            "6 mason, 10 helper vannu",  # the model echoing the raw words
        ]
    )
    result = await world.say(provider, "6 mason, 10 helper vannu")
    assert result.reply.text.startswith("✅ Saved: 16 workers (6 mason, 10 helper)")
    assert "vannu" not in result.reply.text


async def test_scorecard_3_labour_english(world):  # noqa: F811
    provider = FakeToolCallingProvider(
        [
            [("save_labour", {"workers": [{"trade": "mason", "headcount": 12}, {"trade": "helper", "headcount": 5}]})],
            "Got it",
        ]
    )
    result = await world.say(provider, "12 masons and 5 helpers today")
    # WA-37: the model's words first, the saved line from the data under them.
    assert result.reply.text.startswith("Got it\n\n✅ Saved: 17 workers (12 mason, 5 helper)")


async def test_scorecard_4_percentage_is_progress_not_finished(world):  # noqa: F811
    """The model wrote 'finished' in Malayalam and called it completed; the
    saved data and the reply say 40%."""
    provider = FakeToolCallingProvider(
        [
            [
                (
                    "save_work_done",
                    {
                        "narrative": "രണ്ടാം നിലയിൽ പ്ലാസ്റ്ററിംഗ് കഴിഞ്ഞു",
                        "work_type": "plastering",
                        "location": "2nd floor",
                        "update_kind": "completed",
                        "progress_percent": 40,
                    },
                )
            ],
            "",
        ]
    )
    result = await world.say(provider, "Plastering 2nd floor 40% aayi")
    saved = world.dispatcher.dispatched[0].draft_action.fields
    assert saved["progress_percent"] == 40
    assert str(saved.get("update_kind", "")).lower() != "completed"
    assert saved["narrative"] == "Plastering, 2nd floor: 40%"
    assert result.reply.text.startswith("✅ Saved: Plastering, 2nd floor: 40%")
    assert "കഴിഞ്ഞു" not in result.reply.text


async def test_scorecard_6_finished_is_completed(world):  # noqa: F811
    provider = FakeToolCallingProvider(
        [
            [
                (
                    "save_work_done",
                    {
                        "narrative": "plastering finished 2nd floor",
                        "work_type": "plastering",
                        "location": "2nd floor",
                        "update_kind": "completed",
                    },
                )
            ],
            "",
        ]
    )
    result = await world.say(provider, "plastering finished 2nd floor")
    saved = world.dispatcher.dispatched[0].draft_action.fields
    assert "progress_percent" not in saved
    assert result.reply.text.startswith("✅ Saved: Plastering, 2nd floor")


async def test_scorecard_8_material_in(world):  # noqa: F811
    provider = FakeToolCallingProvider(
        [[("save_material_receipt", {"material": "cement", "quantity": 25, "unit": "bags"})], "ok"]
    )
    result = await world.say(provider, "25 bags cement vannu")
    assert result.reply.text.startswith("ok\n\n✅ Saved: Cement in: 25 bags")


async def test_scorecard_9_material_used(world):  # noqa: F811
    provider = FakeToolCallingProvider(
        [[("save_material_usage", {"material": "cement", "quantity": 5, "unit": "bags", "work_item": "slab"})], "ok"]
    )
    result = await world.say(provider, "5 bags cement use cheythu slab ku")
    assert result.reply.text.startswith("ok\n\n✅ Saved: Cement used: 5 bags")


async def test_scorecard_13_question_in_a_note_is_noted(world):  # noqa: F811
    provider = FakeToolCallingProvider(
        [
            [
                ("save_labour", {"workers": [{"trade": "mason", "headcount": 6}, {"trade": "helper", "headcount": 10}]}),
                ("note_for_engineer", {"question": "Nale slab concrete cheyyan pattumo?"}),
            ],
            "Nale slab concrete cheyyan pattumo?",
        ]
    )
    result = await world.say(provider, "6 mason, 10 helper vannu. Nale slab concrete cheyyan pattumo?")
    # WA-37: passed on, said once, never listed as a saved entry.
    assert "📨 Question for your engineer: Nale slab concrete cheyyan pattumo?" in result.reply.text
    assert result.reply.text.count("Nale slab concrete cheyyan pattumo?") == 1
    issue = world.dispatcher.dispatched[1].draft_action.fields
    assert issue["issue_type"] == "OTHER"
    assert issue["narrative"].startswith("Question for your engineer:")
