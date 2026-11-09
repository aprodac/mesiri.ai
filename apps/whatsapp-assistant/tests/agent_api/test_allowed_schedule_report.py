"""TM-30: POST /reports/schedules is a v3 tool (schedule_report), added by scripts/allow_route.py."""

from __future__ import annotations

from agent_api.app import build_api_app
from agent_api.tools import ALLOWED, build_tools


def test_schedule_report_is_a_tool_from_the_real_api() -> None:
    tools = build_tools(build_api_app(None).openapi(), tuple(a for a in ALLOWED if a.name == "schedule_report"))
    tool = tools["schedule_report"]
    assert (tool.method, tool.path) == ("POST", "/reports/schedules")
    assert tool.is_write is True  # a write waits for the person's Save
