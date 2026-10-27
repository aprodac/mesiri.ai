"""Golden conversations for ADR-draft-per-message (request 123, phase P0).

Each test states how the assistant SHOULD behave under the draft-per-message
design (docs/architecture/ADR-draft-per-message.md). They were strict expected
failures on the code of P0 (the bug documented, CI green); each phase removes
the marker when it makes the test pass -- g1, g2 and g3 in P1 (request 124, a
company with ``draft_v2`` on), g4 and g5 in P2. The model is scripted
(``FakeToolCallingProvider``); everything after it is the real journey, as in
``test_agent_replay``.

Source: the root-cause map of request 123 (a, b, d, e, f; g4 is a placeholder) over the 25/27 Oct
live failures. Request 122's own repro list was not in the repository when this
was written; map each of its repros onto a test here or add one (ADR section 9).
"""

from __future__ import annotations

import datetime as dt

import pytest
from tests.replay.test_agent_replay import _make_world
from tests.replay.test_draft_per_message_p1 import press
from tests.replay.test_request114_progress_card import _OpenPlastering

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.draft_store import MemoryDraftStore


@pytest.fixture
async def world():
    """The seed company (one site) with ``draft_v2`` on: messages are held as one card."""
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    return world


LABOUR_6_2 = ("save_labour", {"workers": [{"trade": "mason", "headcount": 6}, {"trade": "helper", "headcount": 2}]})
LABOUR = ("save_labour", {"workers": [{"trade": "mason", "headcount": 3}, {"trade": "helper", "headcount": 12}]})
WORK_DONE = (
    "save_work_done",
    {
        "narrative": "plastering 50 sq ft done", "work_type": "plastering", "update_kind": "completed",
        "quantities": [{"work_type": "plastering", "quantity": 50, "unit": "sq ft"}], "continues": "plastering",
    },
)
CEMENT = ("save_material_receipt", {"material": "cement", "quantity": 50, "unit": "bags", "supplier": "Sharma Traders"})
RAIN = ("report_issue", {"issue_type": "WEATHER", "narrative": "rain stopped work", "delay_duration_minutes": 120})


async def test_g1_nothing_is_written_until_save_is_tapped(world):
    """(a) A four-part note is ONE card; no domain row exists before the tap."""
    provider = FakeToolCallingProvider([[LABOUR, CEMENT, RAIN], "Check it and tap Save."])
    result = await world.say(provider, "3 masons 12 helpers, 50 bags cement from Sharma, rain stopped work 2 hours")

    assert world.dispatcher.dispatched == []
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]
    text = result.reply.text.casefold()
    assert "15 workers" in text and "cement" in text and "weather" in text


async def test_g2_labour_alone_is_a_draft_that_cancel_really_discards(world):
    """(d) Labour was written with the card only a label: Cancel then deleted rows
    that had already counted. Under drafts nothing exists to delete."""
    provider = FakeToolCallingProvider([[LABOUR], "Check it and tap Save."])
    result = await world.say(provider, "3 masons and 12 helpers today")

    assert world.dispatcher.dispatched == []
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]


async def test_g3_work_on_an_open_activity_does_not_hold_the_rest_of_the_message(world):
    """(b) Work on an open activity parks behind a confirmation (parked_by=gate) and
    every later write in the turn is 'held' and comes back one at a time, or never."""
    world.site = {"activity_query": _OpenPlastering()}
    provider = FakeToolCallingProvider([[LABOUR, WORK_DONE, CEMENT], "Check it and tap Save."])
    result = await world.say(provider, "3 masons 12 helpers, plastering 50 sq ft done, 50 bags cement came")

    assert result.toolbox.parked is None
    assert not [c for c in result.run.calls if "held" in str(c.outcome.content).casefold()]
    text = result.reply.text.casefold()
    assert "15 workers" in text and "plastering" in text and "cement" in text  # all three on the one card
    assert world.dispatcher.dispatched == []


async def test_g4_a_correction_never_claims_a_change_the_draft_did_not_make(world):
    """(e) Card items carried an empty tool/args, so the change was refused, yet the
    model said it had changed. Now the reply is built from the draft's result: a
    correction on the open card edits its line, and one on a card already saved is
    a 'Change ...' card; either way what is claimed is what the card shows."""
    from runtime.agent.cards import CardStore
    from tests.replay.test_agent_replay import _MemoryRedis

    world.cards = CardStore(_MemoryRedis())
    fix = ("update_pending_card", {"item_index": 1, "changes": {"workers": [{"trade": "mason", "headcount": 5}]}})
    first = LABOUR_6_2

    # Before Save: the open card's line is redone, in place.
    result = await world.say(FakeToolCallingProvider([[first], "Check it."]), "6 mason 2 helper")
    result = await world.say(FakeToolCallingProvider([[fix], "Sheri, 5 mason."]), "alla, 5 mason aanu")
    (call,) = result.run.calls
    assert call.outcome.content["status"] == "waiting_for_save"
    assert "7 workers (5 mason, 2 helper)" in result.reply.text and "6 mason" not in result.reply.text
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]
    assert world.dispatcher.dispatched == []

    # After Save: the correction is a change line on a new card; the saved entry stands until its Save.
    card, _ = await press(world, result.reply, "✅ Save")
    assert "7 workers (5 mason, 2 helper)" in card.text
    result = await world.say(
        FakeToolCallingProvider([[("update_pending_card", {"item_index": 1, "changes": {"workers": [{"trade": "mason", "headcount": 4}]}})], "Sheri."]),
        "alla, 4 mason aanu",
    )
    (call,) = result.run.calls
    assert call.outcome.content["status"] == "waiting_for_save", call.outcome.content
    assert "Change today's labour: mason 5 → 4 (total 6)" in result.reply.text
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]
    assert len(world.dispatcher.dispatched) == 1


@pytest.mark.parametrize(
    "date_range, expected",
    [("today", dt.date(2026, 10, 27)), ("yesterday", dt.date(2026, 10, 26))],
)
def test_g5_yesterday_is_yesterday_on_the_labour_read_path(date_range, expected):
    """(f) The labour answer used its own date resolver and answered 'yesterday'
    with today; the DPR used another source (8 vs 13). One read helper decides: the
    labour resolver and the work-log one are the same project_day definition."""
    from runtime.agent.project_day import period_for, project_yesterday, resolve_period
    from runtime.labour_query_service import resolve_date_range

    today = dt.date(2026, 10, 27)
    start, end, _label = resolve_date_range(date_range, today=today)
    assert (start, end) == (expected, expected)
    assert (start, end, _label) == period_for(date_range, today)
    now = dt.datetime(2026, 10, 27, 10, 0, tzinfo=dt.UTC)
    assert project_yesterday("Asia/Kolkata", now) == dt.date(2026, 10, 26)
    # The tool's own words ("yesterday", an ISO date) win over the bucket, in the project's zone.
    assert resolve_period(None, "yesterday", "Asia/Kolkata", now)[:2] == (dt.date(2026, 10, 26),) * 2
    assert resolve_period("last_week", None, "Asia/Kolkata", now)[:2] == (dt.date(2026, 10, 19), dt.date(2026, 10, 25))


GOLDEN_MESSAGES = {
    "g1": "3 masons 12 helpers, 50 bags cement from Sharma, rain stopped work 2 hours",
    "g2": "3 masons and 12 helpers today",
}


@pytest.mark.provider
@pytest.mark.parametrize("name", list(GOLDEN_MESSAGES))
async def test_live_gemini_holds_the_message_as_one_card_and_writes_nothing(world, name):
    """The golden g1/g2 against a live model (marker ``provider``: not in CI;
    needs GEMINI_API_KEY): whatever tools it chooses, nothing is written before
    the tap, the card has Save and Cancel, and the labour is on it."""
    import os

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider
    from runtime.agent.runner import AgentRunner

    provider = GeminiProvider(
        GeminiSettings(api_key=SecretStr(key), model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    )
    text = GOLDEN_MESSAGES[name]
    result = await AgentRunner(provider).run(
        ctx=world.context(), user_text=text, gateway=world.gateway(text), scope=world.scope()
    )
    assert result.outcome == "ok"
    assert world.dispatcher.dispatched == []
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]
    assert "15 workers" in result.reply.text
    assert "saved" not in result.reply.text.casefold().replace("tap save", "")
