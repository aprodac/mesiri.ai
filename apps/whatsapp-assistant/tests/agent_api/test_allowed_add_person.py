"""TM-30: POST /projects/{project_id}/members/by-number is a v3 tool (add_person), added by scripts/allow_route.py."""

from __future__ import annotations

from agent_api.app import build_api_app
from agent_api.tools import ALLOWED, build_tools


def test_add_person_is_a_tool_from_the_real_api() -> None:
    tools = build_tools(build_api_app(None).openapi(), tuple(a for a in ALLOWED if a.name == "add_person"))
    tool = tools["add_person"]
    assert (tool.method, tool.path) == ("POST", "/projects/{project_id}/members/by-number")
    assert tool.is_write is True  # a write waits for the person's Save
