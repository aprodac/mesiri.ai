"""GM-06 (9 Nov 2026): "Anil will fix the water problem by Friday" puts Anil on the issue, through the dashboard's
own route, held for Save like every write. The name goes to the API as said (it finds the one person); the id is never
the model's to fill. Guard: reporting a new problem is still `report_issue`."""

from __future__ import annotations

from pathlib import Path

from tests.agent_api.replaykit import _real_tools


def test_assign_and_remind_are_the_dashboards_routes_and_held_for_save() -> None:
    tools = _real_tools()
    assign, remind = tools["assign_issue"], tools["remind_issue_owner"]
    assert (assign.method, assign.path) == ("PUT", "/progress/issues/{issue_id}/owner") and assign.is_write
    assert "assigned_user_name" in assign.body_fields and "assigned_user_id" in assign.hidden
    assert (remind.method, remind.path) == ("POST", "/progress/issues/{issue_id}/remind") and remind.is_write


def test_the_sop_finds_the_issue_first_and_keeps_new_problems_on_report_issue() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")
    assert "find the issue with `list_issues`" in sop and "`assign_issue` with the name as they said it" in sop
    assert "`report_issue`" in sop
