"""Golden conversations for ADR-draft-per-message (request 123, phase P0).

Each test states how the assistant SHOULD behave under the draft-per-message
design (docs/architecture/ADR-draft-per-message.md) and is a strict expected
failure on today's code: it documents the bug, keeps CI green, and turns CI
red the moment a phase fixes it, so the marker is then removed (that is the
acceptance signal for P1/P2). The model is scripted (``FakeToolCallingProvider``);
everything after it is the real journey, as in ``test_agent_replay``.

Source: the root-cause map of request 123 (a, b, d, e, f; g4 is a placeholder) over the 25/27 Oct
live failures. Request 122's own repro list was not in the repository when this
was written; map each of its repros onto a test here or add one (ADR section 9).
"""

from __future__ import annotations

import datetime as dt

import pytest
from tests.replay.test_agent_replay import world  # noqa: F401  (fixture)
from tests.replay.test_request114_progress_card import _OpenPlastering

from mesiri_ai.fakes import FakeToolCallingProvider

pytestmark = pytest.mark.xfail(strict=True, reason="request 123: draft_v2 not built yet (ADR-draft-per-message)")

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


async def test_g1_nothing_is_written_until_save_is_tapped(world):  # noqa: F811
    """(a) A four-part note is ONE card; no domain row exists before the tap."""
    provider = FakeToolCallingProvider([[LABOUR, CEMENT, RAIN], "Check it and tap Save."])
    result = await world.say(provider, "3 masons 12 helpers, 50 bags cement from Sharma, rain stopped work 2 hours")

    assert world.dispatcher.dispatched == []
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]
    text = result.reply.text.casefold()
    assert "15 workers" in text and "cement" in text and "weather" in text


async def test_g2_labour_alone_is_a_draft_that_cancel_really_discards(world):  # noqa: F811
    """(d) Labour was written with the card only a label: Cancel then deleted rows
    that had already counted. Under drafts nothing exists to delete."""
    provider = FakeToolCallingProvider([[LABOUR], "Check it and tap Save."])
    result = await world.say(provider, "3 masons and 12 helpers today")

    assert world.dispatcher.dispatched == []
    assert [b.title for b in result.reply.buttons] == ["✅ Save", "❌ Cancel"]


async def test_g3_work_on_an_open_activity_does_not_hold_the_rest_of_the_message(world):  # noqa: F811
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


@pytest.mark.skip(reason="needs a card store in the replay world (the fake has none, open_card() is None); written in P2")
def test_g4_a_correction_never_claims_a_change_the_draft_did_not_make():
    """(e) Card items carried an empty tool/args, so the change was refused, yet the
    model said it had changed. Target: the reply is built from the draft's result."""


def test_g5_yesterday_is_yesterday_on_the_labour_read_path():
    """(f) The labour answer used its own date resolver and answered 'yesterday'
    with today; the DPR used another source (8 vs 13). One read helper decides."""
    from runtime.agent.project_day import project_yesterday
    from runtime.labour_query_service import resolve_date_range

    today = dt.date(2026, 10, 27)
    start, end, _label = resolve_date_range("yesterday", today=today)
    assert (start, end) == (project_yesterday("Asia/Kolkata", dt.datetime(2026, 10, 27, 10, 0, tzinfo=dt.UTC)),) * 2
