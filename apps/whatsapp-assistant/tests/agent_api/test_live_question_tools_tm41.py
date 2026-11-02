"""TM-41: the Live page tells a v3 question by its lookup tools; every v3 name it lists must be a real v3 tool,
so a renamed route can't silently empty the page again."""

from __future__ import annotations

from agent_api.tools import ALLOWED
from mesiri.domains.dpr.router import QUESTION_TOOLS

CLASSIC = {"query_labour", "query_materials", "query_work_log", "query_project", "request_dpr"}


def test_every_v3_question_tool_is_an_allowed_lookup() -> None:
    lookups = {a.name for a in ALLOWED if a.method == "GET"}
    v3 = set(QUESTION_TOOLS) - CLASSIC
    assert v3 and v3 <= lookups, sorted(v3 - lookups)
