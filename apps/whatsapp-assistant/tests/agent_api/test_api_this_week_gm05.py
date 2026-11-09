"""GM-05 (9 Nov 2026): "what is planned this week" reads the week board (schedule + Tasks module) through the
dashboard's own route. Guard: "when will we finish" / "what is late" stay on `schedule`."""

from __future__ import annotations

from pathlib import Path

from tests.agent_api.replaykit import _real_tools

from agent_api.links import PAGES


def test_this_week_is_the_dashboards_route_read_only_with_its_page() -> None:
    tool = _real_tools()["this_week"]
    assert (tool.method, tool.path) == ("GET", "/projects/{project_id}/week") and not tool.is_write
    assert PAGES["this_week"][0] == "/planning/week?project={project_id}"


def test_the_sop_sends_the_week_to_this_week_and_keeps_finish_and_late_on_schedule() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")
    assert '"when will we finish", "is the slab on time", "handover\n   eppo": call `schedule`' in sop
    assert "`this_week` instead (GM-05)" in sop
