"""Request 124, P1: one draft per open card, written only on the Save tap
(docs/architecture/ADR-draft-per-message.md).

Maps request 122's repros onto tests (its numbering): 1 steel + cement, 2
plastering + skirting, 3 the four-part note (and Cancel's truth), 4 a correction
never claims a change, 5 "mixer breakdown aayi". Repro 6 (the figures disagree)
is the one read helper of P2 (g5 of the golden file stays an expected failure).
The model is scripted; everything after it is the real journey, as in
``test_agent_replay``; the Save / Cancel taps run the same code the journey's tap
handler runs (``press``).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import pytest
from tests.replay.test_agent_replay import _make_world
from tests.replay.test_request114_progress_card import _OpenPlastering

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.draft_action import DraftActionType
from runtime.agent import draft as dr
from runtime.agent.draft_store import MemoryDraftStore

LABOUR = ("save_labour", {"workers": [{"trade": "mason", "headcount": 3}, {"trade": "helper", "headcount": 12}]})
CEMENT = ("save_material_receipt", {"material": "cement", "quantity": 50, "unit": "bags", "supplier": "Sharma Traders"})
RAIN = ("report_issue", {"issue_type": "WEATHER", "narrative": "rain stopped work", "delay_duration_minutes": 120})


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    return world


async def press(world, reply, title: str) -> Any:
    """The tap on ``title`` of ``reply``: what the journey's tap handler does
    (runtime/message_journey.py ``_draft_tap_reply``) with a fresh gateway."""
    rows = [*(reply.buttons or ()), *(reply.list_rows or ())]
    row = next(r for r in rows if r.title.startswith(title))
    action, draft_id, extra = dr.parse_tap(row.id)
    draft = await world.drafts.get(draft_id, world.actor.organization_id, world.actor.user_id)
    if draft is None or draft.status != dr.OPEN:
        return world_reply(dr.ALREADY_DONE), None
    gateway = world.gateway("tap")
    if action == dr.SAVE:
        out = await gateway.save_draft(draft)
    elif action == dr.CANCEL:
        out = await gateway.cancel_draft(draft)
    else:
        out = await gateway.answer_draft(draft, extra[0], int(extra[1]))
    return out, gateway


def world_reply(text: str):
    from channel.replies import ReplySpec

    return ReplySpec(text=text)


async def open_items(world) -> list[dr.DraftItem]:
    draft = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    return draft.items if draft else []


def titles(reply) -> list[str]:
    """The choices under a reply: buttons (up to three) or list rows."""
    return [r.title for r in (reply.buttons or reply.list_rows or ())]


# -- repros --------------------------------------------------------------------


async def test_repro_1_steel_and_cement_are_both_on_the_card(world):
    """"20 rod steel use cheythu, 100 bags cement vannu" showed only cement."""
    provider = FakeToolCallingProvider(
        [
            [
                ("save_material_usage", {"material": "steel", "quantity": 20, "unit": "rods"}),
                ("save_material_receipt", {"material": "cement", "quantity": 100, "unit": "bags"}),
            ],
            "Steel 20 rods used and cement 100 bags came. Check it and tap Save.",
        ]
    )
    result = await world.say(provider, "20 rod steel use cheythu, 100 bags cement vannu")
    assert "Steel used: 20 rods" in result.reply.text
    assert "Cement in: 100 bags" in result.reply.text
    assert dr.CANT_READ not in result.reply.text
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]
    assert world.dispatcher.dispatched == []


async def test_repro_2_plastering_and_skirting_are_both_on_the_card(world):
    """"2nd floor plastering 60% aayi, 120 rft skirting theernnu" showed only plastering."""
    world.site = {"activity_query": _OpenPlastering()}
    provider = FakeToolCallingProvider(
        [
            [
                ("save_work_done", {"narrative": "2nd floor plastering 60%", "work_type": "plastering",
                                    "location": "2nd floor", "progress_percent": 60, "continues": "plastering"}),
                ("save_work_done", {"narrative": "skirting 120 rft done", "work_type": "skirting", "update_kind": "completed",
                                    "quantities": [{"work_type": "skirting", "quantity": 120, "unit": "rft"}]}),
            ],
            "Plastering is at 60% and 120 rft skirting is done. Check it and tap Save.",
        ]
    )
    result = await world.say(provider, "2nd floor plastering 60% aayi, 120 rft skirting theernnu")
    text = result.reply.text
    assert "Plastering, 2nd floor: 60%" in text
    assert "Skirting: 120 rft" in text
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]
    assert world.dispatcher.dispatched == []
    assert not [c for c in result.run.calls if "held" in str(c.outcome.content).casefold()]


FOUR_PART = (
    "5 mason 3 helper, ground floor tiling 40% aayi, 30 bags cement use cheythu, mixer breakdown aayi pani 2 hour ninnu"
)
FOUR_PART_CALLS = [
    ("save_labour", {"workers": [{"trade": "mason", "headcount": 5}, {"trade": "helper", "headcount": 3}]}),
    ("save_work_done", {"narrative": "ground floor tiling 40%", "work_type": "tiling", "location": "ground floor",
                        "progress_percent": 40}),
    ("save_material_usage", {"material": "cement", "quantity": 30, "unit": "bags"}),
    ("report_issue", {"issue_type": "EQUIPMENT_BREAKDOWN", "narrative": "mixer breakdown, work stopped",
                      "delay_duration_minutes": 120}),
]


async def test_repro_3_the_four_part_note_is_one_card_and_nothing_is_written_before_save(world):
    result = await world.say(FakeToolCallingProvider([FOUR_PART_CALLS, "Check it and tap Save."]), FOUR_PART)
    text = result.reply.text
    for line in ("8 workers (5 mason, 3 helper)", "Tiling, ground floor: 40%", "Cement used: 30 bags", "Issue (equipment breakdown)"):
        assert line in text
    assert "Saved:" not in text and "UNDO" not in text
    assert world.dispatcher.dispatched == []
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]


async def test_repro_3_cancel_cancels_everything_and_its_words_are_true(world):
    result = await world.say(FakeToolCallingProvider([FOUR_PART_CALLS, "Check it and tap Save."]), FOUR_PART)
    out, _ = await press(world, result.reply, "❌ Cancel")
    assert out.text == dr.CANCELLED
    assert world.dispatcher.dispatched == []  # nothing was ever written, so nothing to delete
    assert await open_items(world) == []
    again, _ = await press(world, result.reply, "✅ Save")  # a late tap on the old card
    assert again.text == dr.ALREADY_DONE
    assert world.dispatcher.dispatched == []


async def test_repro_3_save_writes_all_four(world):
    result = await world.say(FakeToolCallingProvider([FOUR_PART_CALLS, "Check it and tap Save."]), FOUR_PART)
    out, gateway = await press(world, result.reply, "✅ Save")
    assert out.text.startswith("✅ Saved: 8 workers (5 mason, 3 helper); ")
    assert [d.draft_action.action_type for d in world.dispatcher.dispatched] == [
        DraftActionType.RECORD_LABOUR_ATTENDANCE,
        DraftActionType.CREATE_ACTIVITY,
        DraftActionType.RECORD_MATERIAL_USAGE,
        DraftActionType.RECORD_SITE_ISSUE,
    ]
    assert len(gateway.handled) == 4
    assert await open_items(world) == []


async def test_repro_3_a_second_tap_on_save_writes_nothing_more(world):
    result = await world.say(FakeToolCallingProvider([[LABOUR, CEMENT], "Check it and tap Save."]), "labour and cement")
    await press(world, result.reply, "✅ Save")
    assert len(world.dispatcher.dispatched) == 2
    again, _ = await press(world, result.reply, "✅ Save")
    assert again.text == dr.ALREADY_DONE
    assert len(world.dispatcher.dispatched) == 2


async def test_repro_4_a_correction_claims_no_change_the_card_did_not_make(world):
    """"alla, 6 mason aanu" was answered "Sheri, 6 mason aakki." with nothing changed.
    P2 (request 127): the line IS changed on the card, and what is claimed is the
    tool's own result; a correction that names no line on the card changes nothing
    and says so."""
    await world.say(FakeToolCallingProvider([[LABOUR], "Check it."]), "3 masons 12 helpers")
    fix = {"workers": [{"trade": "mason", "headcount": 6}]}
    provider = FakeToolCallingProvider(
        [[("update_pending_card", {"card_id": "x", "item_index": 1, "changes": fix})], "Sheri, 6 mason aakki."]
    )
    result = await world.say(provider, "alla, 6 mason aanu")
    (call,) = result.run.calls
    assert call.outcome.content["status"] == "waiting_for_save"
    assert call.outcome.content["on_card"] == "18 workers (6 mason, 12 helper)"
    assert (await open_items(world))[0].summary == "18 workers (6 mason, 12 helper)"
    assert world.dispatcher.dispatched == []

    provider = FakeToolCallingProvider(
        [[("update_pending_card", {"item_index": 4, "changes": fix})], "Sheri, 6 mason aakki."]
    )
    result = await world.say(provider, "alla, 6 mason aanu")
    (call,) = result.run.calls
    # WA-82: a line that is not on the card is nothing to correct: the model is told it is
    # new information (to save with its tool), and the card is untouched.
    assert call.outcome.content["status"] == "not_a_correction"
    assert "Nothing was changed" in call.outcome.content["instruction"]
    assert (await open_items(world))[0].summary == "18 workers (6 mason, 12 helper)"  # untouched


async def test_repro_5_mixer_breakdown_with_no_tool_call_still_makes_an_issue_card(world):
    """"Green Villa mixer breakdown aayi" -> "…issue aayi kodukkaam." and no card."""
    provider = FakeToolCallingProvider(["Mixer breakdown aayi, issue aayi kodukkaam."])
    result = await world.say(provider, "Green Villa mixer breakdown aayi")
    assert "Issue (equipment breakdown): Green Villa mixer breakdown aayi" in result.reply.text
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]
    out, _ = await press(world, result.reply, "✅ Save")
    assert [d.draft_action.action_type for d in world.dispatcher.dispatched] == [DraftActionType.RECORD_SITE_ISSUE]
    assert out.text.startswith("✅ Saved")


@pytest.mark.parametrize(
    "text", ["no problem", "mixer fixed now", "any problem?", "3 mason, pump problem 2 hours", "JCB worked 6 hours"]
)
async def test_repro_5_the_rule_leaves_other_messages_alone(world, text):
    result = await world.say(FakeToolCallingProvider(["Okay."]), text)
    assert result.reply.buttons is None
    assert await open_items(world) == []


# -- work on an open activity: the Save tap is its confirmation ------------------------


OPEN_WORK = ("save_work_done", {
    "narrative": "plastering 50 sq ft done", "work_type": "plastering", "update_kind": "completed",
    "quantities": [{"work_type": "plastering", "quantity": 50, "unit": "sq ft"}], "continues": "plastering",
})


async def test_work_on_an_open_activity_is_confirmed_by_the_save_tap_not_held(world):
    world.site = {"activity_query": _OpenPlastering()}
    result = await world.say(FakeToolCallingProvider([[OPEN_WORK], "Check it."]), "plastering 50 sq ft done")
    assert "Plastering: 50 sq ft (completed)" in result.reply.text
    assert world.dispatcher.dispatched == []
    out, gateway = await press(world, result.reply, "✅ Save")
    (confirmed,) = world.dispatcher.dispatched
    assert confirmed.draft_action.action_type is DraftActionType.ADD_PROGRESS_UPDATE
    assert out.text.startswith("✅ Saved: Plastering: 50 sq ft (completed)")
    assert len(gateway.handled) == 1


async def test_the_same_work_on_an_open_activity_writes_what_todays_confirmation_wrote():
    legacy = await _make_world(site_keys=(seed.SITE_A1,))
    legacy.site = {"activity_query": _OpenPlastering()}
    await legacy.say(FakeToolCallingProvider([[OPEN_WORK], "Done."]), "plastering 50 sq ft done")
    assert legacy.dispatcher.dispatched == []  # today it waits for its Yes / Save too
    await legacy.handler.handle_fast_path(legacy.actor.user_id, legacy.message("✅ Save"))

    drafted = await _make_world(site_keys=(seed.SITE_A1,))
    drafted.draft_v2, drafted.drafts = True, MemoryDraftStore()
    drafted.site = {"activity_query": _OpenPlastering()}
    result = await drafted.say(FakeToolCallingProvider([[OPEN_WORK], "Check it."]), "plastering 50 sq ft done")
    await press(drafted, result.reply, "✅ Save")

    assert _written(drafted) == _written(legacy) and len(_written(legacy)) == 1


async def test_the_card_lines_are_the_lines_the_saved_records_are_worded_with(world):
    """The preview is made from the prepared event, not from a saved record:
    it must read exactly as the same entries did once written."""
    legacy = await _make_world(site_keys=(seed.SITE_A1,))
    calls = SAME_MESSAGES["all"]
    shown = await legacy.say(FakeToolCallingProvider([calls, "Done."]), "the same message")
    card = await world.say(FakeToolCallingProvider([calls, "Check it."]), "the same message")
    previews = [i.summary for i in await open_items(world)]
    assert previews == [i.summary for i in shown.toolbox.saved]
    assert all(line in card.reply.text for line in previews)


# -- one card for several messages -----------------------------------------------


async def test_several_messages_in_a_row_add_to_the_one_open_card(world):
    first = await world.say(FakeToolCallingProvider([[LABOUR], "Check it."]), "3 masons 12 helpers")
    second = await world.say(FakeToolCallingProvider([[CEMENT], "Check it."]), "50 bags cement from Sharma")
    assert len(await open_items(world)) == 2
    assert "15 workers" in second.reply.text and "Cement in: 50 bags" in second.reply.text  # the card shows both
    assert world.drafts.rows and len([r for r in world.drafts.rows.values() if r.status == dr.OPEN]) == 1
    out, _ = await press(world, second.reply, "✅ Save")
    assert len(world.dispatcher.dispatched) == 2
    assert first.reply.buttons is not None


async def test_a_message_that_changes_nothing_does_not_repeat_the_card(world):
    await world.say(FakeToolCallingProvider([[LABOUR], "Check it."]), "3 masons 12 helpers")
    result = await world.say(FakeToolCallingProvider(["Nothing else to do."]), "thanks")
    assert result.reply.buttons is None
    assert "To save" not in result.reply.text


async def test_a_later_labour_count_for_the_same_day_merges_into_the_card(world):
    await world.say(FakeToolCallingProvider([[LABOUR], "Check it."]), "3 masons 12 helpers")
    provider = FakeToolCallingProvider(
        [[("save_labour", {"workers": [{"trade": "mason", "headcount": 6}]})], "Check it."]
    )
    result = await world.say(provider, "alla, 6 mason aanu")
    items = await open_items(world)
    assert [i.kind for i in items] == ["labour"]
    assert items[0].summary == "18 workers (6 mason, 12 helper)"
    assert "18 workers (6 mason, 12 helper)" in result.reply.text


async def test_the_same_part_sent_twice_is_one_line(world):
    await world.say(FakeToolCallingProvider([[CEMENT], "Check it."]), "50 bags cement from Sharma")
    await world.say(FakeToolCallingProvider([[CEMENT], "Check it."]), "50 bags cement from Sharma")
    assert len(await open_items(world)) == 1


# -- a day that already has a count: replace or add? ----------------------------


class _Workforce:
    def __init__(self, counted: list[dict[str, Any]]) -> None:
        self.counted = counted

    async def list_worker_candidates(self, **kwargs):  # noqa: ANN003, ANN202
        return []

    async def find_existing_report_for_day(self, **kwargs):  # noqa: ANN003, ANN202
        return {"report_id": "r-1", "counted_lines": self.counted} if self.counted else None


TODAY_13 = [{"trade": "mason", "headcount": 8}, {"trade": "helper", "headcount": 5}]


async def test_a_second_labour_count_asks_replace_or_add_and_never_replaces_silently(world):
    world.workforce = _Workforce(TODAY_13)
    provider = FakeToolCallingProvider(
        [[("save_labour", {"workers": [{"trade": "mason", "headcount": 6}]})], "Check it."]
    )
    result = await world.say(provider, "6 mason aanu")
    text = result.reply.text
    assert "Today already 13 workers (8 mason, 5 helper). Replace it with 6 workers (6 mason), or add to it?" in text
    assert [b.title for b in result.reply.buttons] == ["❌ Cancel", "Replace", "Add"]  # no Save: nothing is ready
    assert world.dispatcher.dispatched == []

    card, _ = await press(world, result.reply, "Replace")
    assert [b.title for b in card.buttons] == ["✅ Save", "❌ Cancel"]
    await press(world, card, "✅ Save")
    (written,) = world.dispatcher.dispatched
    assert [(x["trade"], x["headcount"]) for x in written.draft_action.fields["lines"]] == [("mason", 6)]


async def test_add_raises_the_repeated_trade_by_what_the_day_already_counts(world):
    world.workforce = _Workforce(TODAY_13)
    provider = FakeToolCallingProvider(
        [[("save_labour", {"workers": [{"trade": "mason", "headcount": 6}]})], "Check it."]
    )
    result = await world.say(provider, "6 more mason")
    card, _ = await press(world, result.reply, "Add")
    assert "14 workers (14 mason)" in card.text
    await press(world, card, "✅ Save")
    (written,) = world.dispatcher.dispatched
    assert [(x["trade"], x["headcount"]) for x in written.draft_action.fields["lines"]] == [("mason", 14)]


async def test_a_second_crew_that_repeats_nothing_adds_on_without_a_question(world):
    world.workforce = _Workforce(TODAY_13)
    provider = FakeToolCallingProvider(
        [[("save_labour", {"workers": [{"trade": "electrician", "headcount": 2}]})], "Check it."]
    )
    result = await world.say(provider, "2 electricians")
    assert "❓" not in result.reply.text
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]


async def test_save_with_an_open_question_saves_the_ready_items_and_keeps_the_card_for_the_rest(world):
    world.workforce = _Workforce(TODAY_13)
    provider = FakeToolCallingProvider(
        [[CEMENT, ("save_labour", {"workers": [{"trade": "mason", "headcount": 6}]})], "Check it."]
    )
    result = await world.say(provider, "50 bags cement from Sharma, 6 mason")
    assert titles(result.reply) == ["✅ Save", "❌ Cancel", "Replace", "Add"]
    out, _ = await press(world, result.reply, "✅ Save")
    assert [d.draft_action.action_type for d in world.dispatcher.dispatched] == [DraftActionType.RECORD_MATERIAL_RECEIPT]
    assert out.text.startswith("✅ Saved 1 · still need: 6 workers (6 mason)")
    assert "Today already 13 workers" in out.text
    assert titles(out) == ["❌ Cancel", "Replace", "Add"]
    (left,) = await open_items(world)
    assert left.kind == "labour" and left.state == dr.NEEDS_ANSWER


# -- Save is all or nothing -------------------------------------------------------


class _FailsOn:
    """A dispatcher whose n-th write fails."""

    def __init__(self, inner, n: int) -> None:
        self.inner, self.n, self.seen = inner, n, 0

    @property
    def dispatched(self):
        return self.inner.dispatched

    async def dispatch(self, confirmed):  # noqa: ANN001
        self.seen += 1
        if self.seen == self.n:
            return ExecutionResult(status=ExecutionStatus.FAILED, idempotency_key=f"x{self.seen}")
        return await self.inner.dispatch(confirmed)


async def test_a_failed_item_rolls_the_whole_save_back_and_says_which(world):
    result = await world.say(FakeToolCallingProvider([[LABOUR, CEMENT, RAIN], "Check it."]), "labour, cement, rain")
    world.handler._dispatcher = _FailsOn(world.dispatcher, 2)  # the cement write fails
    out, gateway = await press(world, result.reply, "✅ Save")
    assert out.text.startswith("Nothing was saved. Couldn't save")
    assert "Cement in: 50 bags" in out.text
    assert gateway.handled == []
    # The transaction (the memory store's, standing in for the database's) undid the claim:
    assert [r.status for r in world.drafts.rows.values()] == [dr.OPEN]
    items = await open_items(world)
    assert [i.state for i in items] == [dr.OK, dr.UNREADABLE, dr.OK]
    # The rest can still be saved once the bad one is out of the way.
    assert [b.title for b in out.buttons] == ["✅ Save", "❌ Cancel"]


async def test_an_error_inside_the_transaction_leaves_the_card_open(world):
    result = await world.say(FakeToolCallingProvider([[LABOUR, CEMENT], "Check it."]), "labour and cement")

    async def boom(*_a, **_k):
        raise RuntimeError("database went away")

    world.runtime.start = boom  # type: ignore[method-assign]
    out, _ = await press(world, result.reply, "✅ Save")
    assert "Nothing was saved" in out.text
    assert [r.status for r in world.drafts.rows.values()] == [dr.OPEN]
    assert world.dispatcher.dispatched == []


# -- nothing is dropped silently (the coverage check, ADR 2.6) ----------------------


async def test_a_call_that_cannot_become_a_line_is_listed_as_couldnt_read(world):
    provider = FakeToolCallingProvider(
        [[LABOUR, ("save_material_receipt", {"material": "cement", "quantity": 0, "unit": "bags"})], "Check it."]
    )
    result = await world.say(provider, "labour and zero cement")
    assert "15 workers (3 mason, 12 helper)" in result.reply.text
    assert f"{dr.CANT_READ}0 bags cement" in result.reply.text
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]


async def test_calls_past_the_limit_are_listed_not_lost(world):
    calls = [("save_material_receipt", {"material": "cement", "quantity": n, "unit": "bags"}) for n in range(1, 11)]
    result = await world.say(FakeToolCallingProvider([calls, "Check it."]), "ten cement receipts")
    items = await open_items(world)
    assert len(items) <= dr.MAX_ITEMS + 3
    assert len([i for i in items if i.state == dr.OK]) <= dr.MAX_ITEMS
    assert dr.CANT_READ in result.reply.text


@dataclass
class _Call:
    tool: str
    args: dict[str, Any]
    ok: bool


def _random_calls(rng: random.Random) -> list[_Call]:
    calls = []
    for _ in range(rng.randint(1, 6)):
        kind = rng.choice(["labour", "material", "bad_material", "issue", "work"])
        if kind == "labour":
            calls.append(_Call("save_labour", {"workers": [{"trade": rng.choice(["mason", "helper", "carpenter"]), "headcount": rng.randint(1, 20)}]}, True))
        elif kind == "material":
            calls.append(_Call("save_material_receipt", {"material": rng.choice(["cement", "steel", "bricks"]), "quantity": rng.randint(1, 90), "unit": "bags"}, True))
        elif kind == "bad_material":
            calls.append(_Call("save_material_receipt", {"material": "cement", "quantity": 0, "unit": "bags"}, False))
        elif kind == "issue":
            calls.append(_Call("report_issue", {"issue_type": "WEATHER", "narrative": f"rain {rng.randint(1, 99)}"}, True))
        else:
            calls.append(_Call("save_work_done", {"narrative": f"slab {rng.randint(1, 99)} done", "work_type": "slab"}, True))
    return calls


@pytest.mark.parametrize("seed_value", range(25))
async def test_property_no_extracted_item_is_missing_from_the_card(seed_value):
    """Whatever the model extracted -- each call is on the card as a line, merged
    into a line already there, or listed as "Couldn't read" -- never silently gone."""
    rng = random.Random(seed_value)
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2, world.drafts = True, MemoryDraftStore()
    calls = _random_calls(rng)
    result = await world.say(FakeToolCallingProvider([[(c.tool, c.args) for c in calls], "Check it."]), "a note")
    draft = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    text = result.reply.text
    on_card = {i.label for i in (draft.items if draft else []) if i.state != dr.UNREADABLE}
    unread = {i.label for i in (draft.items if draft else []) if i.state == dr.UNREADABLE}
    for call in calls:
        label = dr.label_for(call.tool, call.args)
        if call.ok:
            assert label in on_card or any(label in line for line in text.splitlines()), (label, text)
        else:
            assert label in unread or label in text, (label, text)
    for item in draft.items if draft else []:
        if item.state == dr.UNREADABLE:
            assert item.label in text


# -- data identity: the same message saved by tap writes what today's flow writes ----

SAME_MESSAGES = {
    "labour": [LABOUR],
    "material_in": [CEMENT],
    "material_out": [("save_material_usage", {"material": "cement", "quantity": 30, "unit": "bags"})],
    "work": [("save_work_done", {"narrative": "ground floor tiling 40%", "work_type": "tiling",
                                 "location": "ground floor", "progress_percent": 40})],
    "issue": [RAIN],
    "all": [LABOUR, CEMENT, RAIN, FOUR_PART_CALLS[1], FOUR_PART_CALLS[2]],
}


def _written(world) -> list[dict[str, Any]]:
    """What reached the domain services, without what is minted per run."""
    out = []
    for confirmed in world.dispatcher.dispatched:
        draft = confirmed.draft_action
        out.append(
            {
                "type": draft.action_type.value,
                "org": draft.organization_id,
                "user": draft.user_id,
                "project": draft.project_id,
                "site": draft.site_id,
                "fields": draft.fields,
            }
        )
    return out


@pytest.mark.parametrize("name", list(SAME_MESSAGES))
async def test_the_same_message_saved_by_tap_writes_what_todays_flow_writes(name):
    calls = SAME_MESSAGES[name]
    text = "the same message"
    legacy = await _make_world(site_keys=(seed.SITE_A1,))
    await legacy.say(FakeToolCallingProvider([calls, "Done."]), text)

    drafted = await _make_world(site_keys=(seed.SITE_A1,))
    drafted.draft_v2, drafted.drafts = True, MemoryDraftStore()
    result = await drafted.say(FakeToolCallingProvider([calls, "Check it."]), text)
    assert drafted.dispatcher.dispatched == []
    await press(drafted, result.reply, "✅ Save")

    assert _written(drafted) == _written(legacy)
    assert len(_written(legacy)) == len(calls)


# -- flag off is today's behaviour --------------------------------------------------


@pytest.mark.parametrize("name", list(SAME_MESSAGES))
async def test_with_the_flag_off_nothing_changes_even_with_a_store_attached(name):
    calls = SAME_MESSAGES[name]
    plain = await _make_world(site_keys=(seed.SITE_A1,))
    plain_result = await plain.say(FakeToolCallingProvider([calls, "Done."]), "the same message")

    off = await _make_world(site_keys=(seed.SITE_A1,))
    off.drafts = MemoryDraftStore()  # attached, but the company's draft_v2 is off
    off_result = await off.say(FakeToolCallingProvider([calls, "Done."]), "the same message")

    assert off_result.reply == plain_result.reply
    assert _written(off) == _written(plain)
    assert len(_written(plain)) == len(calls)  # today: written on the message, before any tap
    assert off.drafts.rows == {}


async def test_with_the_flag_off_a_problem_note_stays_unhandled_as_today():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.drafts = MemoryDraftStore()
    result = await world.say(FakeToolCallingProvider(["Issue aayi kodukkaam."]), "Green Villa mixer breakdown aayi")
    assert result.toolbox.attempted_writes == 0
    assert world.dispatcher.dispatched == []
    assert result.reply.buttons is None
