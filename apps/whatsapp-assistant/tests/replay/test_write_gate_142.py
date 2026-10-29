"""Request 142 (A): every write tool is a line of the card, and the only write is Save.

The model is scripted; everything after it is the real journey (as in
``test_golden_draft_per_message``). Two spies stand for "a write": the
dispatcher (a confirmed action reaching the backend) and ``runtime.start`` (a
workflow started for a record).
"""

from __future__ import annotations

import dataclasses

import pytest
from tests.replay.test_agent_replay import _make_world
from tests.replay.test_draft_per_message_p1 import press

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.draft_store import MemoryDraftStore

EXPENSE = ("save_expense", {"amount": 450, "description": "diesel for the mixer", "category": "fuel"})
OPENING = ("save_opening_stock", {"material": "cement", "quantity": 40, "unit": "bags", "new_material": True})
TRANSFER_MATERIAL = ("transfer_material", {"material": "cement", "quantity": 10, "unit": "bags", "to_site": "Site A2"})
TRANSFER_MONEY = ("transfer_money", {"amount": 5000, "from_account": "Cash", "to_account": "Petty cash"})


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1, seed.SITE_A2), usual_site=seed.SITE_A1)
    world.draft_v2 = True
    world.actor = dataclasses.replace(world.actor, role="ADMIN")
    world.drafts = MemoryDraftStore()
    started: list = []
    real = world.runtime.start

    async def spy(decision, event):
        started.append(decision.workflow_key)
        return await real(decision, event)

    world.runtime.start = spy
    world.started = started

    class _Issues:
        async def find_latest(self, **kwargs):  # noqa: ANN003
            return {"site_issue_id": "i7", "issue_type": "EQUIPMENT_BREAKDOWN", "severity": "HIGH",
                    "narrative": "Mixer breakdown aayi"}

    world.change = {"site_issue_query": _Issues()}
    return world


ISSUE_STATUS = ("update_issue", {"action": "reopen"})
GATED = [EXPENSE, OPENING, TRANSFER_MATERIAL, TRANSFER_MONEY, ISSUE_STATUS]


@pytest.mark.parametrize("call", GATED, ids=lambda c: c[0])
async def test_the_tool_adds_a_line_and_writes_nothing_until_save(world, call):
    provider = FakeToolCallingProvider([[call], "Check it and tap Save."])
    result = await world.say(provider, "x")

    assert world.started == [] and world.dispatcher.dispatched == []
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]
    assert "To save" in result.reply.text

    saved, _gateway = await press(world, result.reply, "✅ Save")
    print(saved.text)
    assert world.started and world.dispatcher.dispatched, saved.text
    assert saved.text.startswith("✅ Saved")


@pytest.mark.parametrize("call", GATED, ids=lambda c: c[0])
async def test_cancel_discards_the_line_and_nothing_was_ever_written(world, call):
    provider = FakeToolCallingProvider([[call], "Check it and tap Save."])
    result = await world.say(provider, "x")
    cancelled, _gateway = await press(world, result.reply, "❌ Cancel")

    assert world.started == [] and world.dispatcher.dispatched == []
    assert "nothing saved" in cancelled.text.casefold()


# -- B: the journal ---------------------------------------------------------------

from runtime.agent import journal as jr  # noqa: E402

LABOUR = ("save_labour", {"workers": [{"trade": "mason", "headcount": 3}]})
CEMENT = ("save_material_receipt", {"material": "cement", "quantity": 50, "unit": "bags", "supplier": "Sharma Traders"})


class _Undo:
    """Stands for the modules' own undo (``interaction_handler.undo_facts``)."""

    def __init__(self) -> None:
        self.calls: list = []

    async def __call__(self, facts):
        from types import SimpleNamespace

        self.calls.append(list(facts))
        return SimpleNamespace(done=list(facts), refused=[], already=0)


@pytest.fixture
async def jworld(world):
    world.journal = jr.MemoryJournalStore()
    world.undo_facts = _Undo()
    return world


async def _save(world, *calls):
    provider = FakeToolCallingProvider([list(calls), "Check it and tap Save."])
    result = await world.say(provider, "x")
    saved, gateway = await press(world, result.reply, "✅ Save")
    return saved


async def test_each_save_writes_one_journal_entry_with_a_reference_to_every_fact(jworld):
    await _save(jworld, LABOUR, CEMENT)
    entries = await jworld.journal.recent(jworld.actor.organization_id, jworld.actor.user_id)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.user_id == str(jworld.actor.user_id) and entry.organization_id == str(jworld.actor.organization_id)
    assert {f.tool for f in entry.facts} == {"save_labour", "save_material_receipt"}
    assert all(f.fact_id and f.fact_type and f.line for f in entry.facts)
    assert entry.site_id


async def test_a_cancelled_card_leaves_no_journal_entry(jworld):
    provider = FakeToolCallingProvider([[LABOUR], "Check it."])
    result = await jworld.say(provider, "x")
    await press(jworld, result.reply, "❌ Cancel")
    assert await jworld.journal.recent(jworld.actor.organization_id, jworld.actor.user_id) == []


async def test_undo_asks_first_and_removes_only_on_the_yes_tap(jworld):
    await _save(jworld, LABOUR)
    provider = FakeToolCallingProvider([[("change_or_undo", {"target": "last"})], "Okay, I will remove it if you confirm."])
    result = await jworld.say(provider, "undo")

    assert jworld.undo_facts.calls == []  # nothing removed by the message
    assert [b.title for b in result.reply.buttons] == [jr.YES_TITLE, jr.KEEP_TITLE]
    assert "Remove this?" in result.reply.text and "3 workers" in result.reply.text

    action, entry_id, numbers = jr.parse_tap(result.reply.buttons[0].id)
    reply = await jworld.gateway("tap").journal_tap(action, entry_id, numbers)
    assert reply.text.startswith("✅ Removed: 3 workers")
    assert len(jworld.undo_facts.calls) == 1
    # a second tap finds it gone and removes nothing more
    again = await jworld.gateway("tap").journal_tap(action, entry_id, numbers)
    assert again.text == jr.GONE and len(jworld.undo_facts.calls) == 1


async def test_keep_leaves_everything_as_it_is(jworld):
    await _save(jworld, LABOUR)
    provider = FakeToolCallingProvider([[("change_or_undo", {"target": "last"})], "Confirm?"])
    result = await jworld.say(provider, "undo")
    action, entry_id, numbers = jr.parse_tap(result.reply.buttons[1].id)
    reply = await jworld.gateway("tap").journal_tap(action, entry_id, numbers)

    assert reply.text == jr.KEPT and jworld.undo_facts.calls == []


async def test_undo_last_goes_through_the_same_confirm_card(jworld):
    """The old tool name no longer removes without asking (Malayalam undo had no confirm)."""
    await _save(jworld, LABOUR)
    provider = FakeToolCallingProvider([[("undo_last", {})], "ശരി."])
    result = await jworld.say(provider, "ആ എൻട്രി കളയൂ")

    assert jworld.undo_facts.calls == []
    assert [b.title for b in result.reply.buttons] == [jr.YES_TITLE, jr.KEEP_TITLE]


async def test_a_description_picks_the_one_line_of_a_save(jworld):
    await _save(jworld, LABOUR, CEMENT)
    provider = FakeToolCallingProvider([[("change_or_undo", {"target": "the cement"})], "Confirm?"])
    result = await jworld.say(provider, "cement venda")

    assert "cement" in result.reply.text.casefold() and "workers" not in result.reply.text
    _a, _e, numbers = jr.parse_tap(result.reply.buttons[0].id)
    assert numbers is not None and len(numbers) == 1


async def test_with_nothing_saved_there_is_nothing_to_undo(jworld):
    provider = FakeToolCallingProvider([[("change_or_undo", {"target": "last"})], "Nothing to undo."])
    result = await jworld.say(provider, "undo")
    assert result.reply.buttons is None and jworld.undo_facts.calls == []


async def test_a_sender_can_only_ever_undo_their_own_entries_in_their_own_company(jworld):
    await _save(jworld, LABOUR)
    store = jworld.journal
    org, user = jworld.actor.organization_id, jworld.actor.user_id
    entry = (await store.recent(org, user))[0]

    assert await store.recent(org, "someone-else") == []
    assert await store.recent("another-company", user) == []
    assert await store.get(entry.id, "another-company", user) is None
    assert await store.get(entry.id, org, "someone-else") is None
    await store.mark_undone(entry.id, "another-company", user, [f.fact_id for f in entry.facts])
    assert (await store.get(entry.id, org, user)).live  # a foreign mark changed nothing

    # and the tap of a foreign entry id removes nothing
    reply = await jworld.gateway("tap").journal_tap(jr.UNDO, uuid_hex(), None)
    assert reply.text == jr.EXPIRED and jworld.undo_facts.calls == []


def uuid_hex() -> str:
    import uuid

    return uuid.uuid4().hex


def test_the_taps_round_trip_and_reject_garbage():
    entry = uuid_hex()
    assert jr.parse_tap(jr.tap_id(jr.UNDO, entry, [1, 3])) == (jr.UNDO, entry, [1, 3])
    assert jr.parse_tap(jr.tap_id(jr.KEEP, entry)) == (jr.KEEP, entry, None)
    assert jr.parse_tap("agj:undo:short") is None and jr.parse_tap("agd:save:" + entry) is None
    assert jr.parse_tap(f"agj:undo:{entry}:x") is None


def test_typed_yes_and_no_are_the_two_buttons():
    from runtime.reply_composer import resolve_choice

    entry = uuid_hex()
    rows = [
        jr.ListRow(jr.tap_id(jr.UNDO, entry, [1]), jr.YES_TITLE),
        jr.ListRow(jr.tap_id(jr.KEEP, entry), jr.KEEP_TITLE),
    ]
    assert resolve_choice("yes", rows) is rows[0]
    assert resolve_choice("sheri", rows) is rows[0]
    assert resolve_choice("no", rows) is rows[1]
    assert resolve_choice("venda", rows) is rows[1]


# -- A: no write tool escapes the gate -------------------------------------------------

from runtime.agent import draft as dr  # noqa: E402
from runtime.agent import tools as t  # noqa: E402

#: Write tools whose call is only a line of the card; the Save tap writes (tested above, and in
#: test_golden_draft_per_message / test_draft_actions_p1 / test_request104_*).
THROUGH_THE_CARD = set(dr.DRAFT_TOOLS) | {
    t.NOTE_FOR_ENGINEER,  # a pending action: the Send tap sends it
    t.REQUEST_MATERIAL,  # a pending action (request 143): the Send tap sends it
    t.SET_SITE_CONDITIONS,  # a pending action
    t.CORRECT_WORK_QUANTITY,  # a "Change" line (draft mode)
}
#: They remove or edit something already on a card / saved; a removal asks first.
TAKE_BACK = {t.UNDO_LAST, t.CHANGE_OR_UNDO, t.UPDATE_PENDING_CARD}
#: NOT behind Save yet, and why. Each needs the owner's ok (CLAUDE.md: security-sensitive or a company
#: setting) before it moves; until then the list is the honest picture and a new tool cannot join it silently.
NOT_YET_BEHIND_SAVE = {
    t.ADD_MEMBER: "grants access to a person (roles, phones): security-sensitive",
    t.CREATE_SITE: "role-gated creation of a site",
    t.CREATE_PROJECT: "role-gated creation of a project",
    t.SET_UNIT_CONVERSION: "a company-wide setting, asked as a question and answered on the spot",
}


def test_every_write_tool_is_behind_the_card_or_listed_as_not_yet():
    assert set(t.WRITE_TOOLS) == THROUGH_THE_CARD | TAKE_BACK | set(NOT_YET_BEHIND_SAVE), (
        "a write tool was added without saying how it waits for Save"
    )
    assert t.UPDATE_ISSUE in THROUGH_THE_CARD  # acknowledge / won't fix / reopen are card lines; resolving a pending action


# -- the transfer's destination ------------------------------------------------------


async def test_a_destination_pick_fills_the_transfer_and_never_sets_the_work_site(world):
    """Live 29 Oct: the tap on the destination ran set_work_site and the transfer was lost."""
    call = ("transfer_material", {"material": "cement", "quantity": 5, "unit": "bags", "to_site": "Moon base"})
    result = await world.say(FakeToolCallingProvider([[call], "Which site?"]), "x")
    assert world.started == []

    picked, _gateway = await press(world, result.reply, "Site A2")
    text = picked.text.casefold()
    assert "for your entries" not in text and "site a2" in text
    assert [b.title for b in picked.buttons][:1] == ["✅ Save"]

    saved, _gateway = await press(world, picked, "✅ Save")
    assert world.started and saved.text.startswith("✅ Saved")
