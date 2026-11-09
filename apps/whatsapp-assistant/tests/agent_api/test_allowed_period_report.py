"""TM-30: GET /reports/period is a v3 tool (period_report), added by scripts/allow_route.py."""

from __future__ import annotations

from agent_api.app import build_api_app
from agent_api.tools import ALLOWED, build_tools


def test_period_report_is_a_tool_from_the_real_api() -> None:
    tools = build_tools(build_api_app(None).openapi(), tuple(a for a in ALLOWED if a.name == "period_report"))
    tool = tools["period_report"]
    assert (tool.method, tool.path) == ("GET", "/reports/period")
    assert tool.is_write is False  # a write waits for the person's Save
