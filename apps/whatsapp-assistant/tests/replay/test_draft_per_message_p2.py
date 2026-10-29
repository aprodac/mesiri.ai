"""Request 127, P2 of docs/architecture/ADR-draft-per-message.md: one test (or
more) per item of the 27 Oct live re-test with ``draft_v2`` on.

1. A correction after Save is a "Change ..." card; before Save it edits the line.
2. One read path for day / period figures (project_day.read_period).
3. The "Replace or add?" question is said once.
4. A line waiting on a question is ON the card, and its buttons answer it.
5. A site named while setting up the team does not become today's site; a new
   card beside an old Yes / No question says so.

The model is scripted; everything after it is the real journey, as in
``test_agent_replay``. Real-database checks of the same rules are in
``tests/integration/test_draft_change_postgres.py``.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest
from tests.replay.test_agent_replay import _Catalog, _make_world, _MemoryRedis
from tests.replay.test_draft_per_message_p1 import TODAY_13, _Workforce, open_items, press, titles

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent.cards import CardStore
from runtime.agent.draft_flow import PENDING_YES_NO
from runtime.agent.draft_store import MemoryDraftStore

LABOUR_6_2 = ("save_labour", {"workers": [{"trade": "mason", "headcount": 6}, {"trade": "helper", "headcount": 2}]})
CEMENT = ("save_material_receipt", {"material": "cement", "quantity": 50, "unit": "bags", "supplier": "Sharma Traders"})


def fix(headcount: int, **extra: Any) -> tuple[str, dict[str, Any]]:
    return ("update_pending_card", {"item_index": 1, "changes": {"workers": [{"trade": "mason", "headcount": headcount}]}, **extra})


class _Undo:
    """``undo_facts``: takes the saved entries back (records what it was asked)."""

    def __init__(self, refuse: str = "") -> None:
        self.asked: list[Any] = []
        self.refuse = refuse

    async def __call__(self, facts):  # noqa: ANN001, ANN204
        self.asked.extend(facts)
        if self.refuse:
            return SimpleNamespace(done=[], refused=[self.refuse], already=0)
        return SimpleNamespace(done=list(facts), refused=[], already=0)


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.cards = CardStore(_MemoryRedis())
    world.undo_facts = _Undo()
    return world


async def _saved(world) -> None:
    """6 mason 2 helper on a card, saved by tap."""
    result = await world.say(FakeToolCallingProvider([[LABOUR_6_2], "Check it."]), "6 mason 2 helper")
    await press(world, result.reply, "✅ Save")
    assert len(world.dispatcher.dispatched) == 1


def _lines(confirmed) -> list[tuple[str, int]]:  # noqa: ANN001
    return [(x["trade"], x["headcount"]) for x in confirmed.draft_action.fields["lines"]]


# -- 1. corrections ----------------------------------------------------------------


async def test_1_a_correction_after_save_is_a_change_card_and_its_save_replaces_the_entry(world):
    """Live: "alla, 5 mason aanu" after Saving 6 mason, 2 helper -> "card-ile oru line
    maattan ippo pattilla… Cancel tap cheythu…" (the card was already saved)."""
    await _saved(world)
    result = await world.say(FakeToolCallingProvider([[fix(5)], "Sheri, 5 mason."]), "alla, 5 mason aanu")

    assert "Change today's labour: mason 6 → 5 (total 7)" in result.reply.text
    assert "Cancel tap" not in result.reply.text
    assert titles(result.reply) == ["✅ Save", "❌ Cancel"]
    assert world.undo_facts.asked == [] and len(world.dispatcher.dispatched) == 1  # nothing before the tap

    out, _ = await press(world, result.reply, "✅ Save")
    (saved_fact,) = world.undo_facts.asked  # the saved entry was taken back...
    assert saved_fact[0] == "labour_report"
    assert _lines(world.dispatcher.dispatched[-1]) == [("mason", 5), ("helper", 2)]  # ...and the corrected one written
    assert out.text.startswith("✅ Saved")
    assert await world.drafts.open_for(world.actor.organization_id, world.actor.user_id) is None


async def test_1_the_change_writes_what_saving_the_corrected_figures_writes():
    """The labour data identity, at the journey level (the database rows are
    compared in tests/integration/test_draft_change_postgres.py)."""
    from tests.replay.test_draft_per_message_p1 import _written

    legacy = await _make_world(site_keys=(seed.SITE_A1,))
    corrected = ("save_labour", {"workers": [{"trade": "mason", "headcount": 5}, {"trade": "helper", "headcount": 2}]})
    await legacy.say(FakeToolCallingProvider([[corrected], "Done."]), "5 mason 2 helper")

    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2, world.drafts = True, MemoryDraftStore()
    world.cards, world.undo_facts = CardStore(_MemoryRedis()), _Undo()
    await _saved(world)
    result = await world.say(FakeToolCallingProvider([[fix(5)], "Sheri."]), "alla, 5 mason aanu")
    await press(world, result.reply, "✅ Save")

    new, old = _written(world)[-1], _written(legacy)[0]
    # Request 136: the one site of the sender is on the record (the fixture's legacy
    # path places none: see test_draft_per_message_p1._same_records).
    assert old["site"] is None and new["site"] == world.site_ids.get(world.actor.sites[0].id, world.actor.sites[0].id)
    assert {**new, "site": None} == old


async def test_1_a_second_correction_before_its_save_edits_the_same_change_line(world):
    await _saved(world)
    result = await world.say(FakeToolCallingProvider([[fix(5)], "Sheri."]), "alla, 5 mason aanu")
    draft = (await open_items(world))
    assert len(draft) == 1
    # Now the open card is the change card: the model names it by its number on that card.
    result = await world.say(FakeToolCallingProvider([[fix(4)], "Sheri."]), "alla, 4 mason")
    (item,) = await open_items(world)
    assert item.kind == dr.KIND_CHANGE and item.summary == "Change today's labour: mason 6 → 4 (total 6)"
    assert "mason 6 → 4" in result.reply.text


async def test_1_cancel_on_a_change_card_leaves_the_saved_entry_as_it_was(world):
    await _saved(world)
    result = await world.say(FakeToolCallingProvider([[fix(5)], "Sheri."]), "alla, 5 mason aanu")
    out, _ = await press(world, result.reply, "❌ Cancel")
    assert out.text == dr.CANCELLED
    assert world.undo_facts.asked == [] and len(world.dispatcher.dispatched) == 1


async def test_1_a_saved_entry_that_cannot_be_taken_back_writes_nothing_and_says_why(world):
    world.undo_facts = _Undo(refuse="that day's report is already confirmed")
    await _saved(world)
    result = await world.say(FakeToolCallingProvider([[fix(5)], "Sheri."]), "alla, 5 mason aanu")
    out, _ = await press(world, result.reply, "✅ Save")
    assert out.text.startswith("Nothing was saved.") and "already confirmed" in out.text
    assert len(world.dispatcher.dispatched) == 1  # only the first save


async def test_1_the_model_is_told_about_the_saved_card_it_may_change():
    line = dr.saved_context_line(["8 workers (6 mason, 2 helper)"], "ab12cd")
    assert "1. 8 workers (6 mason, 2 helper)" in line and "update_pending_card with card_id ab12cd" in line
    assert "nothing changes before that" in line
    assert dr.saved_context_line([], "x") is None


# -- 2. one read path -----------------------------------------------------------------


class _Reads:
    def __init__(self) -> None:
        self.asked: list[tuple[str, dt.date, dt.date]] = []

    async def search(self, **kw: Any) -> dict[str, Any]:
        self.asked.append(("work", kw["start_date"], kw["end_date"]))
        return {"activities": [{"work_type": "plastering"}], "activity_count": 1, "open_issues": [], "open_issue_count": 0}

    async def summarize_attendance(self, **kw: Any) -> dict[str, Any]:
        self.asked.append(("labour", kw["start_date"], kw["end_date"]))
        return {
            "headcount": 8, "trades": ["mason", "helper"], "days": 1,
            "rows": [{"trade": "mason", "headcount": 6}, {"trade": "helper", "headcount": 2}],
        }


async def test_2_what_was_done_today_includes_the_days_workers():
    """Live: "innu enthokke cheythu?" left out today's 8 workers."""
    from mesiri_contracts.assistant.planner_decision import WorkflowKey
    from runtime.agent.query_entry import _one_name_per_trade
    from runtime.inbound_journey import seeding
    from workflows.activity_query.nodes import generate_activity_search_reply

    reads = _Reads()
    event = SimpleNamespace(fields={}, project_id=None, site_id=None)
    decision = SimpleNamespace(workflow_key=WorkflowKey.ACTIVITY_QUERY)
    await seeding._seed_activity_search(
        event, decision, reads, SimpleNamespace(organization_id="org-1"), "Asia/Kolkata", labour_query_service=reads
    )
    _one_name_per_trade(event.fields["activity_search_results"]["labour"])
    reply = generate_activity_search_reply({"collected_fields": event.fields})["pending_prompt"]
    assert "Plastering" in reply and "👷 8 workers (6 Mason, 2 Helper)" in reply
    (work, labour) = reads.asked
    assert work[1:] == labour[1:]  # the same day, read the one way


async def test_2_yesterday_on_the_labour_question_is_yesterday():
    from mesiri_contracts.assistant.planner_decision import WorkflowKey
    from runtime.agent.tools import QUERY_LABOUR, ScopeLookup, to_candidate
    from runtime.inbound_journey import seeding

    candidate = to_candidate(QUERY_LABOUR, {"date": "yesterday"}, ScopeLookup(projects=(), sites=()))
    assert candidate.fields["date"] == "yesterday"
    reads = _Reads()
    event = SimpleNamespace(fields=dict(candidate.fields), project_id=None, site_id=None)
    await seeding._seed_labour_query(
        event, SimpleNamespace(workflow_key=WorkflowKey.LABOUR_QUERY), reads, SimpleNamespace(organization_id="o"),
        "Asia/Kolkata",
    )
    from runtime.agent.project_day import project_yesterday

    ((_, start, end),) = reads.asked
    assert start == end == project_yesterday("Asia/Kolkata")
    assert event.fields["labour_results"]["date_range_label"].startswith("yesterday")


async def test_2_the_today_so_far_line_counts_the_days_workers():
    from runtime.today_context import build_today_line

    reads = _Reads()
    actor = SimpleNamespace(organization_id="o", full_name="Anil K", sites=[SimpleNamespace(id="s", name="Site A1", project_id="p")])
    line = await build_today_line(reads, actor, timezone_name="Asia/Kolkata", labour_query_service=reads)
    assert line == "Today so far: Anil, Site A1. Saved today: plastering, 8 workers."


def test_2_the_draft_report_line_counts_open_issues_as_the_list_does():
    """Live: the DPR draft said "1 open issue" while "open issues?" listed 2."""
    from runtime.site_day_review import day_lines

    payload = {
        "activity_count": 0,
        "issues": [{"status": "OPEN", "issue_type": "WEATHER"}],
        "carried_issues": [{"status": "OPEN", "issue_type": "EQUIPMENT_BREAKDOWN"}],
        "open_issue_count": 2,  # the assembly's, by backend application/dpr/open_issues.py
    }
    assert "• Issues: 2 open" in day_lines(payload)
    # Only an earlier day's open issue: still "nothing logged today".
    assert day_lines({"issues": [], "carried_issues": [{"status": "OPEN"}], "open_issue_count": 1}) == []


# -- 3. the question is said once -------------------------------------------------------


async def test_3_the_replace_or_add_question_is_said_once(world):
    """Live: the "Today already 13… Replace or add?" line was printed twice when
    labour was the only item (the model wrote it, and the card showed it)."""
    world.workforce = _Workforce(TODAY_13)
    question = "Today already 13 workers (8 mason, 5 helper). Replace it with 6 workers (6 mason), or add to it?"
    provider = FakeToolCallingProvider(
        [[("save_labour", {"workers": [{"trade": "mason", "headcount": 6}]})], f"Sheri, 6 mason.\n{question}"]
    )
    result = await world.say(provider, "6 mason aanu")
    assert result.reply.text.count("Today already 13") == 1
    assert titles(result.reply) == ["❌ Cancel", "Replace", "Add"]


# -- 4. a line waiting on a question is on the card, and its buttons answer it ----------


async def test_4_a_line_waiting_on_its_question_is_on_the_card_and_a_tap_answers_it(world):
    world.catalog = _Catalog()  # "s" is several of their materials: which one?
    usage = ("save_material_usage", {"material": "s", "quantity": 20, "unit": "bags"})
    result = await world.say(FakeToolCallingProvider([[CEMENT, usage], "Check it."]), "cement vannu, 20 bag s used")

    text = result.reply.text
    assert "Cement in: 50 bags" in text
    assert '• S used: 20 bags (❓ Which material is "s"?)' in text  # on the card, with its question
    assert text.count('Which material is "s"?') == 1
    assert "steel" in titles(result.reply) and "✅ Save" in titles(result.reply)
    assert world.dispatcher.dispatched == []

    card, _ = await press(world, result.reply, "steel")
    assert "Steel used: 20 bags" in card.text and "❓" not in card.text
    assert titles(card) == ["✅ Save", "❌ Cancel"]
    assert [i.state for i in await open_items(world)] == [dr.OK, dr.OK]
    await press(world, card, "✅ Save")
    assert len(world.dispatcher.dispatched) == 2


async def test_4_a_typed_answer_turns_the_waiting_line_into_the_entry(world):
    world.catalog = _Catalog()
    await world.say(
        FakeToolCallingProvider([[("save_material_usage", {"material": "s", "quantity": 20, "unit": "bags"})], "Which?"]),
        "20 bag s used",
    )
    result = await world.say(
        FakeToolCallingProvider([[("save_material_usage", {"material": "steel", "quantity": 20, "unit": "bags"})], "Check it."]),
        "steel",
    )
    (item,) = await open_items(world)
    assert item.state == dr.OK and item.summary.startswith("Steel used: 20 bags")
    assert "❓" not in result.reply.text


def test_4_a_waiting_line_survives_the_store():
    import json

    item = dr.DraftItem(
        kind=dr.KIND_MATERIAL_OUT, tool="save_material_usage", args={"material": "steel"}, summary="Steel used: 20 rod",
        state=dr.NEEDS_ANSWER, question="1 rod = how many kg?", options=["2", "Other"], awaiting="unit",
    )
    clone = dr.DraftItem.from_json(json.loads(json.dumps(item.to_json())))
    assert clone == item and clone.pending_answer
    draft = dr.MessageDraft.new(organization_id="o", user_id="u")
    draft.items.append(clone)
    assert dr.card_text(draft) == "📝 To save: Steel used: 20 rod (❓ 1 rod = how many kg?)"
    assert [r.title for r in dr.card_rows(draft)] == ["❌ Cancel", "2", "Other"]


# -- 5. site carry-over, and the old Yes / No question ------------------------------------


class _Active:
    def __init__(self) -> None:
        self.set: list[Any] = []

    async def get_active_context(self, **kw: Any) -> None:
        return None

    async def set_active_context(self, **kw: Any) -> None:
        self.set.append(kw["site_id"])


@pytest.mark.parametrize(
    "key, remembered",
    [("ADD_PROJECT_MEMBER", False), ("SITE_CREATE", False), ("ACTIVITY_CORRECTION", False),
     ("LABOUR_ATTENDANCE", True), ("MATERIAL_RECEIPT", True), ("SITE_UPDATE", True), ("SITE_ISSUE_REPORT", True)],
)
async def test_5_only_a_report_from_a_site_makes_it_todays_site(key, remembered):
    """Live: after "Site B-il Rajesh-ine supervisor aakku" (a Yes / No card), the next
    "ഇന്ന് 4 മേസൺ വന്നു" was put on Site B without asking: the add-member entry had
    made Site B today's site."""
    from mesiri_contracts.assistant.planner_decision import WorkflowKey
    from runtime.agent.change_entry import ChangeEntry

    active = _Active()
    entry = ChangeEntry(None, None, SimpleNamespace(sites=[], timezone=None), active_context=active)
    ready = SimpleNamespace(decision=SimpleNamespace(workflow_key=WorkflowKey[key]), scope=("o", "u", "p", "site-b"))
    await entry.remember(ready)
    assert active.set == (["site-b"] if remembered else [])


@pytest.mark.parametrize(
    "action, remembered",
    [("ADD_PROJECT_MEMBER", False), ("CREATE_SITE", False), ("CLOSE_SITE_ISSUE", False),
     ("RECORD_LABOUR_ATTENDANCE", True), ("ADD_PROGRESS_UPDATE", True)],
)
async def test_5_a_confirmed_save_moves_todays_site_only_for_a_site_report(world, action, remembered):
    from mesiri_contracts.assistant.draft_action import DraftActionType

    seen: list[str] = []

    async def set_today(project_id, site_id):  # noqa: ANN001, ANN202
        seen.append(site_id)
        return "Site B"

    gateway = world.gateway("x")
    gateway.set_today_site = set_today
    draft = SimpleNamespace(site_id="site-b", project_id="p", action_type=DraftActionType[action])
    await gateway._remember_site(SimpleNamespace(result=SimpleNamespace(confirmed_action=SimpleNamespace(draft_action=draft))))
    assert seen == (["site-b"] if remembered else [])


async def test_5_a_new_card_beside_a_waiting_yes_no_question_says_so(world):
    async def waiting() -> str:
        return "Add Rajesh as supervisor? Reply YES or NO"

    world.pending_confirmation = waiting
    result = await world.say(FakeToolCallingProvider([[LABOUR_6_2], "Check it."]), "6 mason 2 helper")
    assert PENDING_YES_NO in result.reply.text
    assert titles(result.reply) == ["✅ Save", "❌ Cancel"]


async def test_5_no_note_when_nothing_waits(world):
    async def nothing() -> None:
        return None

    world.pending_confirmation = nothing
    result = await world.say(FakeToolCallingProvider([[LABOUR_6_2], "Check it."]), "6 mason 2 helper")
    assert PENDING_YES_NO not in result.reply.text
