"""TM-30: POST /reports/send is a v3 tool (send_report_to), added by scripts/allow_route.py."""

from __future__ import annotations

from agent_api.app import build_api_app
from agent_api.tools import ALLOWED, build_tools


def test_send_report_to_is_a_tool_from_the_real_api() -> None:
    tools = build_tools(build_api_app(None).openapi(), tuple(a for a in ALLOWED if a.name == "send_report_to"))
    tool = tools["send_report_to"]
    assert (tool.method, tool.path) == ("POST", "/reports/send")
    assert tool.is_write is True  # a write waits for the person's Save
