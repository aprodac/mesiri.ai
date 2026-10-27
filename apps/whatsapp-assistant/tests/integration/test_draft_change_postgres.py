"""Request 127 (P2), against a real Postgres: a correction of something already
saved is a "Change ..." card; its Save takes the saved entry back and writes the
corrected one in ONE transaction, through the services today's flow uses.

- Data identity: the change writes the labour rows an edit in today's flow
  writes (withdraw the entry, save the corrected figures), and every read of the
  day (the labour answer) then counts the same.
- Atomicity: when the corrected write fails, the take-back is rolled back with
  it: the saved figures still count, and the card stays open.

Needs a local Postgres at the default settings (``-m integration``).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from tests.integration.test_draft_save_postgres import (
    _call,
    _FailsOn,
    _gateway,
    _open,
    world,  # noqa: F401 -- the fixture these tests take
)
from tests.replay.test_agent_replay import _MemoryRedis

from mesiri.infrastructure.postgres.repositories.workforce import counted_line_sql
from runtime.agent.cards import CardStore
from runtime.agent.tools import REPORT_ISSUE, SAVE_LABOUR
from runtime.labour_query_service import LabourQueryService

pytestmark = pytest.mark.integration

LABOUR_6_2 = (SAVE_LABOUR, {"workers": [{"trade": "mason", "headcount": 6}, {"trade": "helper", "headcount": 2}]})
LABOUR_5_2 = (SAVE_LABOUR, {"workers": [{"trade": "mason", "headcount": 5}, {"trade": "helper", "headcount": 2}]})
TO_FIVE = {"workers": [{"trade": "mason", "headcount": 5}]}
REPORT_ISSUE_UNSAVED = (REPORT_ISSUE, {"issue_type": "SAFETY", "narrative": "no helmets"})


def _with_cards(w, gateway, cards: CardStore):
    gateway.cards = cards
    gateway.undo_facts = lambda facts: w.handler.undo_facts(organization_id=str(w.org), user_id=w.user, facts=facts)
    return gateway


async def _counted(w) -> list[tuple[Any, ...]]:
    """The labour lines the day counts (live, saved, latest per trade)."""
    async with w.db.transaction() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT labour_attendance_lines.trade, labour_attendance_lines.headcount, "
                    "labour_attendance_reports.site_id, labour_attendance_reports.occurred_date "
                    "FROM labour_attendance_lines JOIN labour_attendance_reports "
                    "ON labour_attendance_reports.id = labour_attendance_lines.report_id "
                    "WHERE labour_attendance_reports.organization_id = :o "
                    "AND labour_attendance_reports.voided_at IS NULL "
                    f"AND {counted_line_sql('labour_attendance_lines', 'labour_attendance_reports')} "
                    "ORDER BY 1"
                ),
                {"o": w.org},
            )
        ).all()
    return [tuple(r) for r in rows]


async def _answer(w) -> int:
    today = dt.datetime.now(dt.UTC).astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).date()
    summary = await LabourQueryService(w.db).summarize_attendance(
        organization_id=str(w.org), project_id=None, site_id=None, start_date=today, end_date=today
    )
    return int(summary["headcount"])


async def _start_over(w) -> None:
    async with w.db.transaction() as conn:
        await conn.execute(text("DELETE FROM message_drafts WHERE organization_id = :o"), {"o": w.org})
        await conn.execute(text("DELETE FROM fact_reviews WHERE organization_id = :o"), {"o": w.org})
        await conn.execute(
            text("DELETE FROM labour_attendance_lines WHERE report_id IN "
                 "(SELECT id FROM labour_attendance_reports WHERE organization_id = :o)"), {"o": w.org}
        )
        await conn.execute(text("DELETE FROM labour_attendance_reports WHERE organization_id = :o"), {"o": w.org})


async def _saved_by_tap(w, cards: CardStore) -> None:
    """6 mason 2 helper, on a card, saved by tap: the saved card is kept."""
    gateway = _with_cards(w, _gateway(w, draft=True), cards)
    await _call(w, gateway, *LABOUR_6_2)
    reply = await _with_cards(w, _gateway(w, draft=True), cards).save_draft(await _open(w))
    assert reply.text.startswith("✅ Saved"), reply.text


async def test_a_change_writes_the_labour_rows_an_edit_in_todays_flow_writes(world):  # noqa: F811 -- the imported fixture
    # Today's flow (flag off): the message writes it as a draft; "alla, 5 mason"
    # withdraws that entry and saves the corrected figures; the Save tap confirms.
    from runtime.agent.save_button import fact_of

    legacy = _gateway(world, draft=False)
    await _call(world, legacy, *LABOUR_6_2)
    first = [fact_of(h) for h in legacy.handled]
    undone = await world.handler.undo_facts(organization_id=str(world.org), user_id=world.user, facts=first)
    assert undone.done == first
    again = _gateway(world, draft=False)
    await _call(world, again, *LABOUR_5_2)
    await world.handler.settle_drafts(
        organization_id=str(world.org), user_id=world.user, keep=True, facts=[fact_of(h) for h in again.handled]
    )
    today_rows, today_answer = await _counted(world), await _answer(world)
    assert [(r[0], r[1]) for r in today_rows] == [("helper", 2), ("mason", 5)]
    await _start_over(world)

    # Drafts: saved by tap, then corrected after the Save -> a change card.
    cards = CardStore(_MemoryRedis())
    await _saved_by_tap(world, cards)
    gateway = _with_cards(world, _gateway(world, draft=True), cards)
    (item,) = (await cards.get(world.actor)).items
    step = await gateway.change_saved_item(item, TO_FIVE)
    assert step.status == "drafted" and step.summary.startswith("Change today's labour"), step
    assert step.summary.endswith("mason 6 → 5 (total 7)"), step.summary
    assert [(r[0], r[1]) for r in await _counted(world)] == [("helper", 2), ("mason", 6)]  # nothing before the tap

    reply = await _with_cards(world, _gateway(world, draft=True), cards).save_draft(await _open(world))
    assert reply.text.startswith("✅ Saved"), reply.text
    assert await _counted(world) == today_rows
    assert await _answer(world) == today_answer == 7
    # The saved card now holds the corrected entry, so a second correction starts from 5.
    (kept,) = (await cards.get(world.actor)).items
    assert kept.args["workers"][0]["headcount"] == 5


async def test_a_failed_change_rolls_the_take_back_back_too(world):  # noqa: F811 -- the imported fixture
    cards = CardStore(_MemoryRedis())
    await _saved_by_tap(world, cards)
    gateway = _with_cards(world, _gateway(world, draft=True), cards)
    (item,) = (await cards.get(world.actor)).items
    await gateway.change_saved_item(item, TO_FIVE)
    draft = await _open(world)

    failing = _with_cards(world, _gateway(world, draft=True, dispatcher=_FailsOn(world.router, 1)), cards)
    reply = await failing.save_draft(draft)

    assert reply.text.startswith("Nothing was saved. Couldn't save"), reply.text
    # The saved 6 + 2 still count: the take-back was undone with the failed write.
    assert [(r[0], r[1]) for r in await _counted(world)] == [("helper", 2), ("mason", 6)]
    assert await _answer(world) == 8
    assert (await _open(world)).id == draft.id


# -- one open-issue rule: "open issues?" and the day's report say the same number ----


async def _issue(w, *, days_ago: int, narrative: str, status: str = "OPEN") -> uuid.UUID:
    issue_id = uuid.uuid4()
    when = dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago)
    async with w.db.transaction() as conn:
        await conn.execute(
            text(
                "INSERT INTO site_issues (id, organization_id, project_id, site_id, issue_type, occurred_at, status, narrative) "
                "VALUES (:id, :o, :p, :s, 'EQUIPMENT_BREAKDOWN', :at, CAST(:st AS site_issue_status), :n)"
            ),
            {"id": issue_id, "o": w.org, "p": w.actor.projects[0].id, "s": w.sites[0].id, "at": when, "st": status, "n": narrative},
        )
    return issue_id


async def test_open_issues_and_the_days_report_count_by_the_same_rule(world):  # noqa: F811 -- the imported fixture
    """27 Oct: the draft said "1 open issue" while "open issues?" listed 2 (the
    mixer from an earlier day and today's rain)."""
    from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository
    from runtime.activity_search_service import ActivitySearchService
    from runtime.dpr_request_query import only_kept
    from runtime.site_day_review import day_lines

    await _issue(world, days_ago=2, narrative="mixer breakdown")  # an earlier day, still open
    await _issue(world, days_ago=0, narrative="rain stopped work")  # today
    await _issue(world, days_ago=0, narrative="Question for your engineer: which tiles?")  # a note, not an issue
    await _issue(world, days_ago=0, narrative="crane fixed", status="RESOLVED")
    await _call(world, _gateway(world, draft=False), REPORT_ISSUE_UNSAVED[0], REPORT_ISSUE_UNSAVED[1])  # Save not tapped

    today = dt.datetime.now(dt.UTC).astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).date()
    listed = await ActivitySearchService(world.db).search(
        organization_id=str(world.org), project_id=str(world.actor.projects[0].id), site_id=str(world.sites[0].id),
        start_date=today, end_date=today,
    )
    async with world.db.transaction() as conn:
        payload, items = await PostgresDprRepository(conn).assemble_site_day(
            organization_id=world.org, project_id=uuid.UUID(str(world.actor.projects[0].id)),
            site_id=uuid.UUID(str(world.sites[0].id)), report_date=today,
        )
    kept = only_kept(payload, items)

    assert listed["open_issue_count"] == 2, listed["open_issues"]
    assert kept["open_issue_count"] == 2
    assert "• Issues: 2 open" in day_lines(kept)
