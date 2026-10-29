"""Request 124: the draft, its card and taps, its stores, its reminder (no I/O)."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import uuid
from typing import Any

import pytest

from runtime.agent import draft as dr
from runtime.agent.draft_flow import ready_from_json, ready_to_json
from runtime.agent.draft_store import MemoryDraftStore, PostgresDraftStore
from runtime.agent.entry_base import Ready
from runtime.agent.equipment import is_problem_only
from runtime.draft_reminder import REMINDER_LINE, reminder_due, reminder_payload

ORG, USER = str(uuid.uuid4()), str(uuid.uuid4())


def _draft(*items: dr.DraftItem) -> dr.MessageDraft:
    draft = dr.MessageDraft.new(organization_id=ORG, user_id=USER)
    draft.items.extend(items)
    return draft


def _item(summary: str, state: str = dr.OK, **kw: Any) -> dr.DraftItem:
    return dr.DraftItem(kind=dr.KIND_MATERIAL_IN, tool="save_material_receipt", args={}, summary=summary, state=state, **kw)


# -- taps -----------------------------------------------------------------------


def test_tap_ids_round_trip_and_name_the_draft():
    draft = _draft(_item("x"))
    assert dr.parse_tap(dr.tap_id(dr.SAVE, draft.id)) == (dr.SAVE, draft.id, ())
    assert dr.parse_tap(dr.tap_id(dr.CANCEL, draft.id)) == (dr.CANCEL, draft.id, ())
    assert dr.parse_tap(dr.tap_id(dr.ANSWER, draft.id, "ab12cd34", "1")) == (dr.ANSWER, draft.id, ("ab12cd34", "1"))


@pytest.mark.parametrize(
    "value",
    ["agt:save:abc", "agd:save:short", "agd:other:" + "a" * 32, "agd:ans:" + "a" * 32, "agd:ans:" + "z" * 32 + ":a:1", "", "x"],
)
def test_a_malformed_tap_is_nothing(value):
    assert dr.parse_tap(value) is None


def test_a_tap_id_fits_a_whatsapp_button():
    draft = _draft(_item("x"))
    assert len(dr.tap_id(dr.ANSWER, draft.id, "ab12cd34", "9")) < 200


# -- the card ---------------------------------------------------------------------


def test_the_card_lists_ready_lines_questions_and_what_could_not_be_read():
    draft = _draft(
        _item("Cement in: 50 bags"),
        _item("6 workers (6 mason)", dr.NEEDS_ANSWER, question="Today already 13 workers. Replace it, or add to it?", options=["Replace", "Add"]),
        _item("", dr.UNREADABLE, label="120 rft skirting"),
    )
    assert dr.card_text(draft) == (
        "📝 To save: Cement in: 50 bags\n❓ Today already 13 workers. Replace it, or add to it?\nCouldn't read: 120 rft skirting"
    )


def test_several_ready_lines_are_bullets_and_a_one_site_card_names_its_site():
    draft = _draft(_item("a"), _item("b"))
    assert dr.card_text(draft, site="Green Villa") == "📝 To save · Green Villa:\n• a\n• b"


def test_a_card_of_several_sites_names_the_site_on_each_line():
    draft = _draft(_item("a", site_id="s1", site="Block A"), _item("b", site_id="s2", site="Block B"))
    assert dr.card_text(draft, site="Block A") == "📝 To save:\n• a · Block A\n• b · Block B"


def test_buttons_are_save_cancel_then_the_options_of_the_first_question():
    draft = _draft(_item("ready"), _item("ask", dr.NEEDS_ANSWER, question="q?", options=["Replace", "Add"]))
    assert [r.title for r in dr.card_rows(draft)] == ["✅ Save", "❌ Cancel", "Replace", "Add"]
    assert dr.card_reply(draft).list_rows is not None  # more than three: a list
    only_ask = _draft(_item("ask", dr.NEEDS_ANSWER, question="q?", options=["Replace", "Add"]))
    assert [r.title for r in dr.card_rows(only_ask)] == ["❌ Cancel", "Replace", "Add"]  # nothing to save yet
    assert [r.title for r in dr.card_rows(_draft(_item("ready")))] == ["✅ Save", "❌ Cancel"]
    assert dr.card_rows(_draft(_item("", dr.UNREADABLE, label="x"))) == []


def test_a_draft_of_only_unreadable_lines_is_not_live():
    assert not _draft(_item("", dr.UNREADABLE, label="x")).live
    assert _draft(_item("a")).live


def test_a_draft_expires_with_the_card():
    draft = _draft(_item("a"))
    assert not draft.expired()
    assert draft.expired(draft.updated + dr.DRAFT_TTL_SECONDS + 1)


def test_the_model_is_told_nothing_is_written_and_how_to_change_a_line():
    draft = _draft(_item("Cement in: 50 bags"))
    line = dr.context_line(draft)
    assert "nothing is written" in line and "1. Cement in: 50 bags" in line
    # Request 127 (P2): a line is changed through the tool, never by the model's own words.
    assert f"update_pending_card with card_id {draft.id[:6]}" in line and "only when the tool says so" in line
    assert dr.context_line(None) is None
    assert dr.context_line(_draft(_item("", dr.UNREADABLE, label="x"))) is None


def test_items_survive_json():
    item = _item("a", dr.NEEDS_ANSWER, question="q?", options=["x", "y"], site_id="s", site="S", label="l")
    clone = dr.DraftItem.from_json(json.loads(json.dumps(item.to_json())))
    assert clone == item
    assert dr.DraftItem.from_json({"nonsense": 1}) is None


# -- labour: a day that already has a count ------------------------------------


def _fields(new: list[dict[str, Any]], old: list[dict[str, Any]]) -> dict[str, Any]:
    return {"lines": new, "day_counted_lines": old}


def test_replace_or_add_is_asked_only_when_the_new_count_repeats_the_day():
    day = [{"trade": "mason", "headcount": 8}, {"trade": "helper", "headcount": 5}]
    asked = dr.labour_question(_fields([{"trade": "mason", "headcount": 6}], day))
    assert asked is not None
    assert asked[0] == "Today already 13 workers (8 mason, 5 helper). Replace it with 6 workers (6 mason), or add to it?"
    assert asked[1] == [dr.REPLACE, dr.ADD]
    assert dr.labour_question(_fields([{"trade": "electrician", "headcount": 2}], day)) is None  # a second crew
    assert dr.labour_question(_fields([{"trade": "mason", "headcount": 8}], day)) is None  # the same figure
    assert dr.labour_question(_fields([{"trade": "mason", "headcount": 6}], [])) is None  # an empty day


def test_add_raises_only_the_repeated_lines():
    fields = _fields(
        [{"trade": "mason", "headcount": 6}, {"trade": "electrician", "headcount": 2}],
        [{"trade": "mason", "headcount": 8}, {"trade": "helper", "headcount": 5}],
    )
    added = dr.add_to_day(fields)
    assert [(x["trade"], x["headcount"]) for x in added["lines"]] == [("mason", 14), ("electrician", 2)]
    assert fields["lines"][0]["headcount"] == 6  # the original is not touched


def test_an_answer_settles_the_item_and_a_second_answer_does_nothing():
    item = dr.DraftItem(
        kind=dr.KIND_LABOUR, tool="save_labour", args={}, state=dr.NEEDS_ANSWER, question="q?", options=[dr.REPLACE, dr.ADD],
        ready={"decision": {"workflow_key": "labour.attendance"},
               "event": {"fields": _fields([{"trade": "mason", "headcount": 6}], [{"trade": "mason", "headcount": 8}])}},
    )
    assert dr.apply_answer(item, 1)
    assert item.state == dr.OK and item.question == "" and item.summary == "14 workers (14 mason)"
    assert not dr.apply_answer(item, 0)
    assert not dr.apply_answer(dr.DraftItem(kind="x", tool="t", args={}, state=dr.NEEDS_ANSWER, options=["a"]), 3)


# -- Ready <-> JSON -----------------------------------------------------------------


async def test_a_prepared_workflow_survives_json():
    from tests.replay.test_agent_replay import _make_world

    from context import seed
    from mesiri_ai.fakes import FakeToolCallingProvider

    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2, world.drafts = True, MemoryDraftStore()
    await world.say(
        FakeToolCallingProvider([[("save_material_receipt", {"material": "cement", "quantity": 50, "unit": "bags"})], "ok"]),
        "50 bags cement",
    )
    (item,) = (await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)).items
    ready = ready_from_json(json.loads(json.dumps(item.ready)))
    assert isinstance(ready, Ready)
    assert ready.event.fields["material_name"] == "cement" and float(ready.event.fields["quantity"]) == 50
    assert ready_to_json(ready)["event"] == item.ready["event"]


# -- the stores ----------------------------------------------------------------------


async def test_the_memory_store_keeps_one_open_draft_per_sender_and_claims_once():
    store = MemoryDraftStore()
    draft = _draft(_item("a"))
    await store.put(draft)
    again = await store.open_for(ORG, USER)
    assert again is not None and again.id == draft.id and again.items[0].summary == "a"
    assert await store.open_for(ORG, str(uuid.uuid4())) is None
    assert await store.get(draft.id, ORG, str(uuid.uuid4())) is None  # not theirs
    assert await store.claim(draft.id) is True
    assert await store.claim(draft.id) is False
    assert await store.open_for(ORG, USER) is None


async def test_the_memory_transaction_undoes_a_claim_when_the_block_fails():
    store = MemoryDraftStore()
    draft = _draft(_item("a"))
    await store.put(draft)
    with pytest.raises(RuntimeError):
        async with store.transaction():
            await store.claim(draft.id)
            raise RuntimeError("x")
    assert store.rows[draft.id].status == dr.OPEN


async def test_an_expired_draft_is_discarded_on_read():
    store = MemoryDraftStore()
    draft = _draft(_item("a"))
    await store.put(draft)
    store.rows[draft.id].updated -= dr.DRAFT_TTL_SECONDS + 5
    assert await store.open_for(ORG, USER) is None
    assert store.rows[draft.id].status == dr.DISCARDED


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self.rows = rows or []

    async def execute(self, statement, params=None):  # noqa: ANN001
        self.statements.append((str(statement), dict(params or {})))
        return _Rows(self.rows)


class _Db:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    @contextlib.asynccontextmanager
    async def transaction(self):
        yield self.conn


async def test_the_postgres_store_writes_the_draft_as_json_and_only_while_it_is_open():
    conn = _Conn()
    store = PostgresDraftStore(_Db(conn))
    draft = _draft(_item("a"))
    await store.put(draft)
    sql, params = conn.statements[0]
    assert "INSERT INTO message_drafts" in sql and "CAST(:items AS jsonb)" in sql
    assert "WHERE message_drafts.status = 'open'" in sql  # a saved draft is never overwritten
    assert json.loads(params["items"])[0]["summary"] == "a"
    assert params["org"] == uuid.UUID(ORG) and params["user"] == uuid.UUID(USER)


async def test_the_postgres_store_claims_with_one_conditional_update():
    conn = _Conn()
    store = PostgresDraftStore(_Db(conn))
    assert await store.claim(uuid.uuid4().hex) is False  # no row came back: already taken
    sql = conn.statements[0][0]
    assert "SET status = 'saved'" in sql and "WHERE id = :id AND status = 'open'" in sql and "RETURNING" in sql


async def test_the_postgres_store_reads_its_rows_back():
    draft = _draft(_item("a"))
    row = {
        "id": uuid.UUID(draft.id), "organization_id": uuid.UUID(ORG), "user_id": uuid.UUID(USER), "project_id": None,
        "site_id": None, "source_message_id": "m", "status": "open", "items": json.dumps([draft.items[0].to_json()]),
        "created_epoch": 1.0, "updated_epoch": 4_000_000_000.0,
    }
    store = PostgresDraftStore(_Db(_Conn([row])))
    got = await store.get(draft.id, ORG, USER)
    assert got is not None and got.id == draft.id and got.items[0].summary == "a" and got.status == "open"
    open_one = await store.open_for(ORG, USER)
    assert open_one is not None and open_one.persisted


# -- the reminder --------------------------------------------------------------------

CUTOFF, DEADLINE = dt.time(18, 0), dt.time(21, 0)


def _at(hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 10, 27, hour, minute)


@pytest.mark.parametrize(
    ("now", "updated", "due"),
    [
        (_at(17, 30), _at(15, 0), True),  # half an hour before the cutoff
        (_at(17, 29), _at(15, 0), False),  # not yet
        (_at(18, 10), _at(17, 55), True),  # after the cutoff, before the deadline
        (_at(20, 59), _at(19, 0), True),
        (_at(21, 0), _at(19, 0), False),  # the report has gone
        (_at(17, 40), _at(17, 35), False),  # still being built
        (_at(17, 40), _at(17, 20), True),  # idle for 20 minutes
    ],
)
def test_the_reminder_is_due_between_half_an_hour_before_the_cutoff_and_the_deadline(now, updated, due):
    assert reminder_due(local_now=now, cutoff=CUTOFF, deadline=DEADLINE, updated_local=updated) is due


@pytest.mark.parametrize(
    ("now", "updated", "due"),
    [
        (_at(15, 5), _at(10, 0), True),  # made at 10:00, gone at 16:00: reminded an hour before
        (_at(14, 50), _at(10, 0), False),  # not yet
        (_at(16, 1), _at(10, 0), False),  # expired: never saved, nothing to remind
        (_at(3, 0), _at(21, 30), False),  # in the small hours nothing goes out
        (_at(17, 40), _at(12, 0), True),  # (inside the cutoff window and still alive)
    ],
)
def test_a_card_that_would_expire_before_the_cutoff_window_is_reminded_before_it_expires(now, updated, due):
    if updated.date() != now.date():  # the case that crosses midnight
        updated = updated - dt.timedelta(days=1)
    assert reminder_due(local_now=now, cutoff=CUTOFF, deadline=DEADLINE, updated_local=updated) is due


def test_the_reminder_carries_the_card_and_its_two_taps():
    draft = _draft(_item("Cement in: 50 bags"))
    payload = reminder_payload(draft)
    assert payload["message"].startswith(REMINDER_LINE)
    assert "Cement in: 50 bags" in payload["message"]
    assert [b["title"] for b in payload["buttons"]] == ["✅ Save", "❌ Cancel"]
    assert [dr.parse_tap(b["id"])[:2] for b in payload["buttons"]] == [(dr.SAVE, draft.id), (dr.CANCEL, draft.id)]


# -- "<something> breakdown / problem" with nothing else -----------------------------


@pytest.mark.parametrize(
    "text",
    ["Green Villa mixer breakdown aayi", "mixer breakdown aayi", "pump problem", "mixer kedayi", "lift not working",
     "crane breakdown"],
)
def test_a_note_that_only_says_something_is_broken_is_an_issue(text):
    assert is_problem_only(text)


@pytest.mark.parametrize(
    "text",
    ["no problem", "mixer fixed now", "any problem?", "problem solved", "3 masons and mixer breakdown 2 hours",
     "JCB worked 6 hours", "", "50 bags cement came, mixer breakdown", "mixer problem illa"],
)
def test_other_notes_are_left_alone(text):
    assert not is_problem_only(text)


def test_tap_id_round_trips_every_fact_type_a_card_can_hold():
    """[141] "undo" crashed with KeyError: a progress update (request 137) had no tap code."""
    import uuid

    from runtime.agent.save_button import _CODES, UNDO, parse_tap, tap_id
    from runtime.day_facts import PROGRESS_UPDATE

    assert PROGRESS_UPDATE in _CODES
    assert len(set(_CODES.values())) == len(_CODES)
    facts = [(fact_type, uuid.uuid4()) for fact_type in _CODES]
    assert parse_tap(tap_id(UNDO, facts[:1])) == (UNDO, facts[:1])
    for fact in facts:
        assert parse_tap(tap_id(UNDO, [fact])) == (UNDO, [fact])
