"""TM-30: POST /projects/{project_id}/members is a v3 tool (add_project_member), added by scripts/allow_route.py."""

from __future__ import annotations

from agent_api.app import build_api_app
from agent_api.tools import ALLOWED, build_tools


def test_add_project_member_is_a_tool_from_the_real_api() -> None:
    tools = build_tools(build_api_app(None).openapi(), tuple(a for a in ALLOWED if a.name == "add_project_member"))
    tool = tools["add_project_member"]
    assert (tool.method, tool.path) == ("POST", "/projects/{project_id}/members")
    assert tool.is_write is True  # a write waits for the person's Save
