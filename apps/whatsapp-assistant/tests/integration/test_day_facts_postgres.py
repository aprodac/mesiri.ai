"""Request 137 against a real database: saved work, continued work, corrections and
the day's readers all read one set of facts (runtime/day_facts.py).

Run with a live database:
    pytest apps/whatsapp-assistant/tests/integration/test_day_facts_postgres.py -m integration
"""

from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from tests.integration.test_draft_save_postgres import _message, _open, _scope, world  # noqa: F401
from tests.replay.test_agent_replay import _MemoryRedis

from runtime.activity_query import ActivityQueryService
from runtime.activity_search_service import ActivitySearchService
from runtime.agent.cards import CardStore
from runtime.agent.journey_gateway import JourneyGateway
from runtime.agent.toolbox import NOT_A_CORRECTION, AgentToolbox
from runtime.agent.tools import SAVE_WORK_DONE, to_candidate
from runtime.day_facts import PROGRESS_UPDATE, DayFactsReader, project_today_for

pytestmark = pytest.mark.integration

TILING = {"narrative": "ground floor tiling", "work_type": "tiling", "location": "ground floor"}
PLASTER = {"narrative": "plastering 50 sq ft", "work_type": "plastering",
           "quantities": [{"work_type": "plastering", "quantity": 50, "unit": "sq ft"}]}


@pytest.fixture
def cards():
    return CardStore(_MemoryRedis())


def _gw(w, cards, said: str = "the message", *, draft: bool = True) -> JourneyGateway:  # noqa: ANN001
    return JourneyGateway(
        message=_message(said),
        save_now=lambda: w.handler.save_now(w.user, actor=w.actor),
        undo=lambda: None,
        followups=lambda handled: None,
        held_prompt=lambda journey: None,
        material_entry=w.material_entry,
        labour_entry=w.labour_entry,
        site_entry=w.site_entry,
        start_workflow=w.runtime.start,
        actor=w.actor,
        cards=cards,
        undo_facts=lambda facts: w.handler.undo_facts(organization_id=str(w.org), user_id=w.user, facts=facts),
        draft_v2=draft,
        drafts=w.drafts if draft else None,
        confirm_now=lambda: w.handler.confirm_now(w.user, actor=w.actor),
        settle_facts=lambda facts: w.handler.settle_drafts(
            organization_id=str(w.org), user_id=w.user, facts=facts, keep=True
        ),
        transaction=w.db.shared_transaction,
        day_facts=DayFactsReader(w.db),
    )


async def _add(w, cards, args: dict, said: str = "the message"):  # noqa: ANN001, ANN202
    gateway = _gw(w, cards, said)
    gateway.current_call = (SAVE_WORK_DONE, args)
    return await gateway.run(to_candidate(SAVE_WORK_DONE, args, _scope(w)), text=said)


async def _save(w, cards) -> str:  # noqa: ANN001
    reply = await _gw(w, cards).save_draft(await _open(w))
    assert reply.text.startswith("✅ Saved"), reply.text
    return reply.text


async def _say_and_save(w, cards, percent: int, **extra) -> None:  # noqa: ANN001
    step = await _add(w, cards, {**TILING, "progress_percent": percent, **extra})
    assert step.status == "drafted", step
    await _save(w, cards)


async def _correct(w, cards, said: str, **args):  # noqa: ANN001, ANN202
    toolbox = AgentToolbox(gateway=_gw(w, cards, said), scope=_scope(w), user_text=said)
    return await toolbox._run("correct_work_quantity", args)  # noqa: SLF001


async def _today_notes(w) -> list[str]:  # noqa: ANN001
    day = project_today_for(w.actor)
    work = await ActivitySearchService(w.db).search(
        organization_id=str(w.org), project_id=None, site_id=None, start_date=day, end_date=day
    )
    return [str(a["narrative"]) for a in work["activities"]]


async def test_a_continued_percent_is_what_today_says(world, cards):  # noqa: F811
    """F2 (28 Oct): "innu enthokke cheythu" after 70% then 80% read the 70%."""
    await _say_and_save(world, cards, 70)
    await _say_and_save(world, cards, 80, continues="tiling")
    assert await _today_notes(world) == ["Tiling, ground floor: 80%"]


async def test_the_continued_save_keeps_its_own_fact_and_undo_takes_back_only_it(world, cards):  # noqa: F811
    await _say_and_save(world, cards, 70)
    await _say_and_save(world, cards, 80, continues="tiling")
    card = await cards.get(world.actor)
    (item,) = card.items
    assert item.fact_type == PROGRESS_UPDATE

    undone = await world.handler.undo_facts(organization_id=str(world.org), user_id=world.user, facts=[item.fact])
    assert undone.done == [item.fact], undone
    assert await _today_notes(world) == ["Tiling, ground floor: 70%"]  # the activity and its 70% stay


async def test_a_newer_percent_is_never_a_correction(world, cards):  # noqa: F811
    await _say_and_save(world, cards, 70)
    step = await _correct(world, cards, "Green Villa ground floor tiling 80% aayi", new_quantity=80)
    assert step.status == NOT_A_CORRECTION


async def test_a_percent_correction_fixes_the_saved_line_found_in_the_day(world, cards):  # noqa: F811
    await _say_and_save(world, cards, 70)
    await _say_and_save(world, cards, 80, continues="tiling")
    step = await _correct(world, cards, "alla, 75%", new_quantity=75, unit="%")
    assert step.status == "drafted", step
    await _save(world, cards)
    assert await _today_notes(world) == ["Tiling, ground floor: 75%"]
    async with world.db.transaction() as conn:
        live = (await conn.execute(text(
            "SELECT count(*) FROM progress_updates pu JOIN activities a ON a.id = pu.activity_id "
            "WHERE a.organization_id = :o AND pu.deleted_at IS NULL"), {"o": world.org})).scalar_one()
    assert live == 1  # the 80% was taken back, the 75% written in its place


async def test_the_same_after_a_cancelled_tiling_card(world, cards):  # noqa: F811
    await _add(world, cards, {**TILING, "progress_percent": 60})
    await _gw(world, cards).cancel_draft(await _open(world))
    await _say_and_save(world, cards, 70)
    await _say_and_save(world, cards, 80, continues="tiling")
    assert await _today_notes(world) == ["Tiling, ground floor: 80%"]


async def test_a_quantity_correction_still_works(world, cards):  # noqa: F811
    step = await _add(world, cards, PLASTER)
    assert step.status == "drafted", step
    await _save(world, cards)
    step = await _correct(world, cards, "correction, it was 40 not 50", new_quantity=40)
    assert step.status == "drafted", step
    await _save(world, cards)
    async with world.db.transaction() as conn:
        amounts = (await conn.execute(text(
            "SELECT aq.quantity FROM activity_quantities aq JOIN activities a ON a.id = aq.activity_id "
            "WHERE a.organization_id = :o AND a.deleted_at IS NULL"), {"o": world.org})).scalars().all()
    assert [float(a) for a in amounts] == [40.0]
    assert "50" not in " ".join(await _today_notes(world))


async def test_continuing_an_activity_still_waiting_for_its_save_makes_it_count(world, cards):  # noqa: F811
    """F2's suspected path: the old flow saved tiling first, as a draft; a draft_v2
    card continues it. The update hung off a parent the readers hide; the Save now
    confirms that parent, so "what was done today" lists the work."""
    legacy = _gw(world, cards, draft=False)
    legacy.current_call = (SAVE_WORK_DONE, {**TILING, "progress_percent": 50})
    await legacy.run(to_candidate(SAVE_WORK_DONE, {**TILING, "progress_percent": 50}, _scope(world)), text="x")
    assert await _today_notes(world) == []  # a draft is not counted
    found = await ActivityQueryService(world.db).find_open_activity(
        organization_id=str(world.org), site_id=world.sites[0].id, reported_by_user_id=world.user
    )
    assert found is not None  # still continued, never a second tiling

    await _say_and_save(world, cards, 80, continues="tiling")
    assert await _today_notes(world) == ["Tiling, ground floor: 80%"]
    async with world.db.transaction() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM activities WHERE organization_id = :o"),
                                   {"o": world.org})).scalar_one() == 1


async def test_day_facts_count_only_saved_work(world, cards):  # noqa: F811
    await _add(world, cards, {**TILING, "progress_percent": 30})  # on the card, not saved
    day = project_today_for(world.actor)
    reader = DayFactsReader(world.db)
    assert await reader.work(organization_id=str(world.org), start=day, end=day) == []
    await _save(world, cards)
    (fact,) = await reader.work(organization_id=str(world.org), start=day, end=day)
    assert (fact.fact_type, fact.value, fact.location, fact.saved) == ("activity", 30.0, "ground floor", True)
    assert uuid.UUID(fact.fact_id)


async def test_save_continue_continue_correct_then_the_day_reads_the_last_figure(world, cards):  # noqa: F811
    """29 Oct re-test: 70% -> 80% -> 85%, then "alla, 82%", all saved, the work done
    at 00:30 IST (still the day before in UTC): the day read listed no tiling at all,
    because an update's date was its UTC date while its activity's was the project's."""
    await _say_and_save(world, cards, 70)
    await _say_and_save(world, cards, 80, continues="tiling")
    await _say_and_save(world, cards, 85, continues="tiling")
    step = await _correct(world, cards, "alla, 82%", new_quantity=82, unit="%")
    assert step.status == "drafted", step
    await _save(world, cards)
    day = project_today_for(world.actor)
    just_after_midnight_ist = dt.datetime.combine(day, dt.time(0, 30), tzinfo=ZoneInfo("Asia/Kolkata"))
    assert just_after_midnight_ist.astimezone(dt.UTC).date() < day  # the UTC date is the day before
    async with world.db.transaction() as conn:
        await conn.execute(text(
            "UPDATE progress_updates SET occurred_at = :at WHERE activity_id IN "
            "(SELECT id FROM activities WHERE organization_id = :o)"), {"at": just_after_midnight_ist, "o": world.org})
    assert await _today_notes(world) == ["Tiling, ground floor: 82%"]
    facts = await DayFactsReader(world.db).work(organization_id=str(world.org), start=day, end=day)
    assert [(f.fact_type, f.value) for f in facts][-1] == (PROGRESS_UPDATE, 82.0)
