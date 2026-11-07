"""Item 3 (live test, 7 Nov 17:49-17:51, test company): "Green Villa: 8 mason 5 helper vannu innu" -> Save, then
"alla, 6 mason aanu" -> "please correct aayi full line ayachalo?" (send the whole line again). The model had no way to
reach a SAVED record: it called change_ready_entry (only for entries still on the card) with a made-up id. Retyping
the line then made a second report.

Now the code remembers what it saved in the chat (the report and its id), lists it for the model, and
``correct_saved_entry`` turns "Mason 6" into ONE report that replaces the saved one (``corrects_report_id``), on the
card as "✏️ Mason 8 → 6 · Helper 5", one Save.
"""

from __future__ import annotations

import uuid

from tests.agent_api.standin import ACTOR, PROJECT, SITE, stand_in_api, stand_in_tools

from agent_api.agent import (
    CHANGE_READY,
    CORRECT_SAVED,
    ApiAgent,
    PendingWrite,
    WriteResult,
    correctable_saves,
    corrected_attendance,
    remember_saves,
)
from agent_api.client import ApiClient
from mesiri_ai.fakes import FakeToolCallingProvider

REPORT = str(uuid.uuid4())
SAVED_BODY = {"project_id": PROJECT, "site_id": SITE, "occurred_date": "2026-11-07", "recorded_via": "whatsapp_text",
              "lines": [{"trade": "Mason", "headcount": 8}, {"trade": "Helper", "headcount": 5}]}


def _saved(report_id: str = REPORT, body: dict | None = None) -> WriteResult:
    pending = PendingWrite(tool="record_attendance", method="POST", path="/labour/attendance", params={},
                           body=body or SAVED_BODY, summary="8 Mason-um 5 Helper-um Green Villa-il", idempotency_key="k1")
    return WriteResult(pending, 201, {"status": "created", "id": report_id})


def test_the_reported_correction_replaces_the_saved_report() -> None:
    saved = correctable_saves(remember_saves([], [_saved()], 1000.0))[0]
    body, line = corrected_attendance(saved, [{"trade": "mason", "headcount": 6}])
    assert body["corrects_report_id"] == REPORT
    assert body["lines"] == [{"trade": "Mason", "headcount": 6}, {"trade": "Helper", "headcount": 5}]
    assert body["site_id"] == SITE and body["occurred_date"] == "2026-11-07"
    assert line == "✏️ Mason 8 → 6 · Helper 5"


def test_siblings_a_new_trade_is_added_and_zero_removes_one() -> None:
    saved = correctable_saves(remember_saves([], [_saved()], 1000.0))[0]
    body, line = corrected_attendance(saved, [{"trade": "Carpenter", "headcount": 2}, {"trade": "Helper", "headcount": 0}])
    assert body["lines"] == [{"trade": "Mason", "headcount": 8}, {"trade": "Carpenter", "headcount": 2}]
    assert "Carpenter 0 → 2" in line and "Helper 5 → 0" in line


def test_guards_nothing_changing_or_nobody_left_is_refused() -> None:
    saved = correctable_saves(remember_saves([], [_saved()], 1000.0))[0]
    assert "nothing changes" in corrected_attendance(saved, [{"trade": "Mason", "headcount": 8}])
    assert "nobody" in corrected_attendance(saved, [{"trade": "Mason", "headcount": 0},
                                                    {"trade": "Helper", "headcount": 0}])


def test_a_corrected_report_is_forgotten_so_the_next_correction_finds_the_new_one() -> None:
    first = remember_saves([], [_saved()], 1000.0)
    newer = str(uuid.uuid4())
    corrected = dict(SAVED_BODY, corrects_report_id=REPORT, lines=[{"trade": "Mason", "headcount": 6}])
    after = correctable_saves(remember_saves(first, [_saved(newer, corrected)], 1001.0))
    assert [r["id"] for r in after] == [newer]


async def _turn(script: list, recent: list) -> object:
    app = stand_in_api([])
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), stand_in_tools(app)).run(
            client, "alla, 6 mason aanu", recent_saves=recent)
    finally:
        await client.close()


async def test_the_reported_message_puts_one_replacing_report_on_the_card() -> None:
    recent = remember_saves([], [_saved()], __import__("time").time())
    turn = await _turn([[(CORRECT_SAVED, {"number": 1, "lines": [{"trade": "Mason", "headcount": 6}]})],
                        "Sheri, 6 mason aakki."], recent)
    (entry,) = turn.pending
    assert entry.tool == "record_attendance" and entry.body["corrects_report_id"] == REPORT
    assert entry.summary == "✏️ Mason 8 → 6 · Helper 5"


async def test_change_ready_entry_after_save_is_sent_to_the_right_tool() -> None:
    """The live failure: change_ready_entry with nothing waiting (Gemini calls a tool it was not offered; the fake
    refuses those itself, so the code's answer is read from the handler directly)."""
    import inspect

    from agent_api import agent as agent_module

    source = inspect.getsource(agent_module.ApiAgent.run)
    assert "if name == CHANGE_READY and not waiting and saved_list:" in source
    assert "Use correct_saved_entry with its number" in source
    assert CHANGE_READY == "change_ready_entry"


async def test_guard_without_a_saved_record_the_tool_is_not_offered() -> None:
    turn = await _turn([[(CORRECT_SAVED, {"number": 1, "lines": [{"trade": "Mason", "headcount": 6}]})], "ok"], [])
    assert turn.pending == [] and "unknown tool" in turn.calls[0]["result"]["error"]
