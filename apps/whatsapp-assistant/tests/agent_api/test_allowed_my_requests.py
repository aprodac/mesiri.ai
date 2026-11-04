"""TM-30: GET /me/requests is a v3 tool (my_requests), added by scripts/allow_route.py."""

from __future__ import annotations

from agent_api.app import build_api_app
from agent_api.tools import ALLOWED, build_tools


def test_my_requests_is_a_tool_from_the_real_api() -> None:
    tools = build_tools(build_api_app(None).openapi(), tuple(a for a in ALLOWED if a.name == "my_requests"))
    tool = tools["my_requests"]
    assert (tool.method, tool.path) == ("GET", "/me/requests")
    assert tool.is_write is False  # a write waits for the person's Save
